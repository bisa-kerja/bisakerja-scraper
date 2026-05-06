from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from integrations.backend.payloads import build_backend_jobs_body
from modules.persistence import NormalizedJob

DEFAULT_BACKEND_SYNC_PATH = "/api/v1/internal/scraper/jobs"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class BackendSyncError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_summary: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_summary = response_summary or {}


class BackendSyncClientError(BackendSyncError):
    pass


class BackendSyncServerError(BackendSyncError):
    pass


@dataclass(frozen=True)
class BackendSyncResult:
    status_code: int
    response_summary: dict[str, Any]


class BackendSyncClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float,
        max_retries: int,
        path: str = DEFAULT_BACKEND_SYNC_PATH,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_retries = max_retries
        self.path = path if path.startswith("/") else f"/{path}"
        self.client = client

    async def sync_jobs(self, jobs: list[dict[str, Any]]) -> BackendSyncResult:
        payload = {"jobs": jobs}
        return await self.sync_payload(payload)

    async def sync_normalized_jobs(self, jobs: list[NormalizedJob]) -> BackendSyncResult:
        return await self.sync_payload(build_backend_jobs_body(jobs))

    async def sync_payload(self, payload: dict[str, Any]) -> BackendSyncResult:
        last_error: BackendSyncError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._post(payload)
            except BackendSyncClientError:
                raise
            except BackendSyncServerError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
        if last_error is not None:
            raise last_error
        raise BackendSyncServerError("backend sync failed")

    async def _post(self, payload: dict[str, Any]) -> BackendSyncResult:
        close_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                f"{self.base_url}{self.path}",
                json=payload,
                headers={
                    "authorization": f"Bearer {self.service_token}",
                    "content-type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise BackendSyncServerError("backend sync transport failed") from exc
        finally:
            if close_client:
                await client.aclose()

        summary = summarize_response(response)
        summary["endpointPath"] = self.path
        if 200 <= response.status_code < 300:
            return BackendSyncResult(
                status_code=response.status_code,
                response_summary=summary,
            )
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise BackendSyncServerError(
                "backend sync retryable failure",
                status_code=response.status_code,
                response_summary=summary,
            )
        raise BackendSyncClientError(
            "backend sync rejected payload",
            status_code=response.status_code,
            response_summary=summary,
        )


def summarize_response(response: httpx.Response) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "statusCode": response.status_code,
        "statusClass": f"{response.status_code // 100}xx",
    }
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        for key in ("success", "message", "code"):
            if key in body:
                summary[key] = body[key]
        error = body.get("error")
        if isinstance(error, dict):
            summary["errorCode"] = error.get("code")
            details = error.get("details")
            if isinstance(details, list):
                summary["validationErrors"] = [
                    {
                        "path": item.get("path"),
                        "code": item.get("code"),
                        "message": item.get("message"),
                    }
                    for item in details[:10]
                    if isinstance(item, dict)
                ]
    return summary
