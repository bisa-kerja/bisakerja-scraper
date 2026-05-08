from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from core.errors import FetchError
from shared.http.rate_limit import (
    SourceRateLimitConfig,
    SourceRateLimiter,
    is_retriable_status,
)

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; BisakerjaScraper/0.1; +https://bisakerja.local)"


@dataclass(frozen=True)
class HttpClientConfig:
    source_platform: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    max_response_bytes: int
    default_headers: dict[str, str] = field(default_factory=dict)
    retry_backoff_seconds: float = 0.2
    rate_limit_per_minute: int | None = None
    circuit_breaker_failure_threshold: int = 3


class JsonHttpClient(Protocol):
    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return decoded JSON or raise FetchError."""


class SourceHttpClient:
    def __init__(
        self,
        config: HttpClientConfig,
        *,
        async_client: httpx.AsyncClient | None = None,
        rate_limiter: SourceRateLimiter | None = None,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if config.max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to zero")
        if config.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be greater than zero")
        if config.rate_limit_per_minute is not None and config.rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be greater than zero")
        if config.circuit_breaker_failure_threshold <= 0:
            raise ValueError("circuit_breaker_failure_threshold must be greater than zero")

        self.config = config
        headers = {"user-agent": DEFAULT_USER_AGENT, **config.default_headers}
        self._client = async_client or httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds),
        )
        self._owns_client = async_client is None
        self._rate_limiter = rate_limiter
        if self._rate_limiter is None and config.rate_limit_per_minute is not None:
            self._rate_limiter = SourceRateLimiter(
                SourceRateLimitConfig(
                    source_platform=config.source_platform,
                    requests_per_minute=config.rate_limit_per_minute,
                    initial_backoff_seconds=config.retry_backoff_seconds,
                    circuit_breaker_failure_threshold=config.circuit_breaker_failure_threshold,
                )
            )

    async def __aenter__(self) -> SourceHttpClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: FetchError | None = None
        attempts = self.config.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                return await self._request_json_once(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json_body=json_body,
                )
            except FetchError as error:
                last_error = error
                await self._record_request_error(error)
                if not error.retryable or attempt == attempts:
                    raise
                await self._backoff_after_failure()

        if last_error is not None:
            raise last_error
        raise FetchError(
            "request failed before execution",
            source_platform=self.config.source_platform,
        )

    async def request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        last_error: FetchError | None = None
        attempts = self.config.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                body = await self._request_bytes_once(method, url, params=None, headers=headers)
                return body.decode("utf-8")
            except FetchError as error:
                last_error = error
                await self._record_request_error(error)
                if not error.retryable or attempt == attempts:
                    raise
                await self._backoff_after_failure()

        if last_error is not None:
            raise last_error
        raise FetchError(
            "request failed before execution",
            source_platform=self.config.source_platform,
        )

    async def _request_json_once(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        body = await self._request_bytes_once(
            method,
            url,
            params=params,
            headers=headers,
            json_body=json_body,
        )

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(
                "source response is not valid JSON",
                source_platform=self.config.source_platform,
                details={"error": exc.__class__.__name__},
                retryable=False,
            ) from exc

        if not isinstance(decoded, dict):
            raise FetchError(
                "source response JSON root must be an object",
                source_platform=self.config.source_platform,
                retryable=False,
            )
        return decoded

    async def _request_bytes_once(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        json_body: dict[str, Any] | None = None,
    ) -> bytes:
        if self._rate_limiter is not None:
            await self._rate_limiter.wait_before_request()

        try:
            async with self._client.stream(
                method,
                url,
                params=params,
                headers=headers,
                json=json_body,
                timeout=httpx.Timeout(self.config.timeout_seconds),
            ) as response:
                body = await self._read_bounded(response)
        except httpx.TimeoutException as exc:
            raise FetchError(
                "source request timed out",
                source_platform=self.config.source_platform,
                details={"error": exc.__class__.__name__},
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise FetchError(
                "source request transport failed",
                source_platform=self.config.source_platform,
                details={"error": exc.__class__.__name__},
                retryable=True,
            ) from exc

        if response.is_error:
            status_code = response.status_code
            retryable = is_retriable_status(status_code)
            details: dict[str, Any] = {"statusCode": status_code}
            if status_code == 403:
                text_preview = body[:4096].decode("utf-8", errors="ignore").lower()
                if (
                    "cf_chl_opt" in text_preview
                    or "challenge-platform" in text_preview
                    or "just a moment" in text_preview
                    or "cloudflare" in text_preview
                ):
                    details["blocker"] = "cloudflare_challenge"
            raise FetchError(
                "source request returned error status",
                source_platform=self.config.source_platform,
                details=details,
                retryable=retryable,
            )
        if self._rate_limiter is not None:
            self._rate_limiter.record_success()
        return body

    async def _record_request_error(self, error: FetchError) -> None:
        if self._rate_limiter is None:
            return
        if error.retryable:
            self._rate_limiter.record_failure()

    async def _backoff_after_failure(self) -> None:
        if self._rate_limiter is not None:
            await self._rate_limiter.backoff_after_failure()
        elif self.config.retry_backoff_seconds > 0:
            await asyncio.sleep(self.config.retry_backoff_seconds)

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total_size = 0

        async for chunk in response.aiter_bytes():
            total_size += len(chunk)
            if total_size > self.config.max_response_bytes:
                raise FetchError(
                    "source response exceeded size limit",
                    source_platform=self.config.source_platform,
                    details={"maxResponseBytes": self.config.max_response_bytes},
                    retryable=False,
                )
            chunks.append(chunk)

        return b"".join(chunks)
