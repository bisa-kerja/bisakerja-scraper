import httpx
import pytest

from core.errors import FetchError
from shared.http import DEFAULT_USER_AGENT, HttpClientConfig, SourceHttpClient


def client_config() -> HttpClientConfig:
    return HttpClientConfig(
        source_platform="dealls",
        base_url="https://api.example.test",
        timeout_seconds=2.0,
        max_retries=1,
        max_response_bytes=128,
        default_headers={"origin": "https://dealls.com"},
        retry_backoff_seconds=0,
    )


@pytest.mark.asyncio
async def test_source_http_client_sends_default_headers_and_decodes_json() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers["user-agent"] = request.headers["user-agent"]
        seen_headers["origin"] = request.headers["origin"]
        return httpx.Response(200, json={"ok": True})

    async_client = httpx.AsyncClient(
        base_url="https://api.example.test",
        headers={"user-agent": DEFAULT_USER_AGENT, "origin": "https://dealls.com"},
        transport=httpx.MockTransport(handler),
    )
    client = SourceHttpClient(client_config(), async_client=async_client)

    response = await client.request_json("GET", "/jobs")

    assert response == {"ok": True}
    assert seen_headers == {
        "user-agent": DEFAULT_USER_AGENT,
        "origin": "https://dealls.com",
    }
    await async_client.aclose()


@pytest.mark.asyncio
async def test_source_http_client_sends_json_body() -> None:
    seen_body = b""
    seen_content_type = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_body
        nonlocal seen_content_type
        seen_body = await request.aread()
        seen_content_type = request.headers["content-type"]
        return httpx.Response(200, json={"ok": True})

    async_client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    client = SourceHttpClient(client_config(), async_client=async_client)

    response = await client.request_json("POST", "/graphql", json_body={"operationName": "jobs"})

    assert response == {"ok": True}
    assert seen_body.decode("utf-8") == '{"operationName":"jobs"}'
    assert seen_content_type == "application/json"
    await async_client.aclose()


@pytest.mark.asyncio
async def test_source_http_client_retries_transient_status() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"ok": True})

    async_client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    client = SourceHttpClient(client_config(), async_client=async_client)

    response = await client.request_json("GET", "/jobs")

    assert response == {"ok": True}
    assert calls == 2
    await async_client.aclose()


@pytest.mark.asyncio
async def test_source_http_client_does_not_retry_non_retriable_status() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad request"})

    async_client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    client = SourceHttpClient(client_config(), async_client=async_client)

    with pytest.raises(FetchError) as exc_info:
        await client.request_json("GET", "/jobs")

    assert calls == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.details == {"statusCode": 400}
    await async_client.aclose()


@pytest.mark.asyncio
async def test_source_http_client_guards_response_size() -> None:
    async_client = httpx.AsyncClient(
        base_url="https://api.example.test",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 129)),
    )
    client = SourceHttpClient(client_config(), async_client=async_client)

    with pytest.raises(FetchError) as exc_info:
        await client.request_json("GET", "/jobs")

    assert exc_info.value.retryable is False
    assert exc_info.value.details == {"maxResponseBytes": 128}
    await async_client.aclose()
