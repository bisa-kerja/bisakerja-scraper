from __future__ import annotations

import httpx
import pytest

from integrations.backend import BackendSyncClient, BackendSyncClientError, BackendSyncServerError


@pytest.mark.asyncio
async def test_backend_sync_client_sends_batch_with_service_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"success": True, "message": "Accepted"})

    result = await make_client(handler).sync_jobs([{"id": "job-1"}])

    assert result.status_code == 202
    assert result.response_summary == {
        "statusCode": 202,
        "statusClass": "2xx",
        "success": True,
        "message": "Accepted",
        "endpointPath": "/api/v1/internal/scraper/jobs",
    }
    assert requests[0].headers["authorization"] == "Bearer secret-token"
    assert requests[0].url.path == "/api/v1/internal/scraper/jobs"
    assert requests[0].read() == b'{"jobs":[{"id":"job-1"}]}'


@pytest.mark.asyncio
async def test_backend_sync_client_does_not_retry_4xx() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"code": "VALIDATION_ERROR"}})

    with pytest.raises(BackendSyncClientError) as exc_info:
        await make_client(handler).sync_jobs([{"id": "job-1"}])

    assert calls == 1
    assert exc_info.value.status_code == 400
    assert exc_info.value.response_summary == {
        "statusCode": 400,
        "statusClass": "4xx",
        "errorCode": "VALIDATION_ERROR",
        "endpointPath": "/api/v1/internal/scraper/jobs",
    }
    assert "secret-token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_backend_sync_client_retries_retryable_status() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"message": "busy"})
        return httpx.Response(200, json={"success": True})

    result = await make_client(handler).sync_jobs([{"id": "job-1"}])

    assert calls == 2
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_backend_sync_client_raises_after_retry_limit() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "busy"})

    with pytest.raises(BackendSyncServerError) as exc_info:
        await make_client(handler, max_retries=1).sync_jobs([{"id": "job-1"}])

    assert calls == 2
    assert exc_info.value.status_code == 503
    assert exc_info.value.response_summary == {
        "statusCode": 503,
        "statusClass": "5xx",
        "message": "busy",
        "endpointPath": "/api/v1/internal/scraper/jobs",
    }


def make_client(handler, *, max_retries: int = 2) -> BackendSyncClient:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return BackendSyncClient(
        base_url="https://backend.example",
        service_token="secret-token",
        timeout_seconds=5,
        max_retries=max_retries,
        client=http_client,
    )
