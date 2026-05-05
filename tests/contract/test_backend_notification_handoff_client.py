from __future__ import annotations

import httpx
import pytest

from integrations.backend import (
    BackendNotificationHandoffClient,
    BackendNotificationHandoffError,
)


@pytest.mark.asyncio
async def test_notification_handoff_client_sends_backend_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "message": "Notification events accepted",
                "data": {"accepted": 1, "runId": "run-1"},
            },
        )

    result = await make_client(handler).send_candidates(
        {
            "runId": "run-1",
            "candidates": [
                {
                    "eventId": "event-1",
                    "syncEventId": "sync-1",
                    "sourcePlatform": "glints",
                    "externalJobId": "job-1",
                    "title": "Backend Engineer",
                    "companyName": "Example Co",
                    "sourceUrl": "https://example.test/jobs/job-1",
                    "location": {"display": "Jakarta"},
                    "salary": None,
                    "status": "active",
                    "lastSeenAt": "2026-05-05T00:00:00+00:00",
                }
            ],
        }
    )

    assert result.response_summary == {
        "statusCode": 200,
        "statusClass": "2xx",
        "success": True,
        "message": "Notification events accepted",
        "endpointPath": "/api/v1/internal/notification-events",
    }
    assert requests[0].headers["authorization"] == "Bearer secret-token"
    assert requests[0].url.path == "/api/v1/internal/notification-events"


@pytest.mark.asyncio
async def test_notification_handoff_client_keeps_safe_error_summary() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"code": "VALIDATION_ERROR"}})

    with pytest.raises(BackendNotificationHandoffError) as exc_info:
        await make_client(handler).send_candidates({"runId": "run-1", "candidates": []})

    assert exc_info.value.status_code == 422
    assert exc_info.value.response_summary == {
        "statusCode": 422,
        "statusClass": "4xx",
        "errorCode": "VALIDATION_ERROR",
        "endpointPath": "/api/v1/internal/notification-events",
    }
    assert "secret-token" not in str(exc_info.value)


def make_client(handler) -> BackendNotificationHandoffClient:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return BackendNotificationHandoffClient(
        base_url="https://backend.example",
        service_token="secret-token",
        timeout_seconds=5,
        client=http_client,
    )
