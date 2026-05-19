from __future__ import annotations

from typing import Any

import httpx

from modules.notifications.handoff import HandoffSuccess

DEFAULT_NOTIFICATION_HANDOFF_PATH = "/api/v1/internal/notification-events"


class BackendNotificationHandoffError(RuntimeError):
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


class BackendNotificationHandoffClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float,
        path: str = DEFAULT_NOTIFICATION_HANDOFF_PATH,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.timeout = httpx.Timeout(timeout_seconds)
        self.path = path if path.startswith("/") else f"/{path}"
        self.client = client

    async def send_candidates(self, payload: dict[str, Any]) -> HandoffSuccess:
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
            raise BackendNotificationHandoffError("notification handoff transport failed") from exc
        finally:
            if close_client:
                await client.aclose()

        summary = summarize_response(response)
        summary["endpointPath"] = self.path
        if 200 <= response.status_code < 300:
            return HandoffSuccess(response_summary=summary)
        raise BackendNotificationHandoffError(
            "notification handoff failed",
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
        return summary
    if isinstance(body, dict):
        for key in ("success", "message", "code"):
            if key in body:
                summary[key] = body[key]
        error = body.get("error")
        if isinstance(error, dict):
            summary["errorCode"] = error.get("code")
    return summary
