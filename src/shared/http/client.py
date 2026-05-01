from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from core.errors import FetchError

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; BisakerjaScraper/0.1; +https://bisakerja.local)"
RETRIABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class HttpClientConfig:
    source_platform: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    max_response_bytes: int
    default_headers: dict[str, str] = field(default_factory=dict)
    retry_backoff_seconds: float = 0.2


class JsonHttpClient(Protocol):
    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return decoded JSON or raise FetchError."""


class SourceHttpClient:
    def __init__(
        self,
        config: HttpClientConfig,
        *,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if config.max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to zero")
        if config.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be greater than zero")

        self.config = config
        headers = {"user-agent": DEFAULT_USER_AGENT, **config.default_headers}
        self._client = async_client or httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds),
        )
        self._owns_client = async_client is None

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
    ) -> dict[str, Any]:
        last_error: FetchError | None = None
        attempts = self.config.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                return await self._request_json_once(method, url, params=params, headers=headers)
            except FetchError as error:
                last_error = error
                if not error.retryable or attempt == attempts:
                    raise
                await asyncio.sleep(self.config.retry_backoff_seconds)

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
    ) -> dict[str, Any]:
        try:
            async with self._client.stream(
                method,
                url,
                params=params,
                headers=headers,
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
            retryable = status_code in RETRIABLE_STATUS_CODES
            raise FetchError(
                "source request returned error status",
                source_platform=self.config.source_platform,
                details={"statusCode": status_code},
                retryable=retryable,
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
