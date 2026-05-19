from typing import Any

import pytest

from core.errors import FetchError, ParseError
from integrations.sources.kalibrr import (
    KALIBRR_HOME_PATH,
    KalibrrBuildIdResolver,
    parse_kalibrr_build_id_from_html,
    request_kalibrr_data_with_build_refresh,
)


class MockHtmlClient:
    def __init__(self, htmls: list[str]) -> None:
        self.htmls = htmls
        self.requests: list[dict[str, Any]] = []

    async def request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        self.requests.append({"method": method, "url": url, "headers": headers})
        return self.htmls.pop(0)


class MockJsonClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._stale = True

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "headers": headers,
                "json_body": json_body,
            }
        )
        if self._stale:
            self._stale = False
            raise FetchError(
                "stale",
                source_platform="kalibrr",
                details={"statusCode": 404},
                retryable=False,
            )
        return {"pageProps": {"jobs": []}}


def html_with_build_id(build_id: str) -> str:
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        f'{{"buildId":"{build_id}","props":{{}}}}'
        "</script></body></html>"
    )


def test_parse_kalibrr_build_id_from_next_data() -> None:
    assert parse_kalibrr_build_id_from_html(html_with_build_id("BUILD_123")) == "BUILD_123"


@pytest.mark.asyncio
async def test_kalibrr_build_id_resolver_caches_per_instance() -> None:
    html_client = MockHtmlClient([html_with_build_id("BUILD_123")])
    resolver = KalibrrBuildIdResolver(html_client)

    assert await resolver.resolve() == "BUILD_123"
    assert await resolver.resolve() == "BUILD_123"

    assert html_client.requests == [
        {
            "method": "GET",
            "url": KALIBRR_HOME_PATH,
            "headers": {"accept": "text/html"},
        }
    ]


@pytest.mark.asyncio
async def test_kalibrr_build_id_resolver_force_refreshes() -> None:
    html_client = MockHtmlClient(
        [
            html_with_build_id("OLD_BUILD"),
            html_with_build_id("NEW_BUILD"),
        ]
    )
    resolver = KalibrrBuildIdResolver(html_client)

    assert await resolver.resolve() == "OLD_BUILD"
    assert await resolver.resolve(force_refresh=True) == "NEW_BUILD"

    assert len(html_client.requests) == 2


@pytest.mark.asyncio
async def test_kalibrr_stale_build_id_refreshes_and_retries_data_request() -> None:
    html_client = MockHtmlClient(
        [
            html_with_build_id("OLD_BUILD"),
            html_with_build_id("NEW_BUILD"),
        ]
    )
    resolver = KalibrrBuildIdResolver(html_client)
    json_client = MockJsonClient()

    payload = await request_kalibrr_data_with_build_refresh(
        json_client=json_client,
        resolver=resolver,
        path_template="/_next/data/{build_id}/id-ID/home/te/developer.json",
        params={"sort": "Freshness", "param": ["te", "developer"]},
    )

    assert payload == {"pageProps": {"jobs": []}}
    assert json_client.requests[0]["url"] == "/_next/data/OLD_BUILD/id-ID/home/te/developer.json"
    assert json_client.requests[1]["url"] == "/_next/data/NEW_BUILD/id-ID/home/te/developer.json"
    assert json_client.requests[1]["headers"] == {"x-nextjs-data": "1"}


def test_parse_kalibrr_build_id_missing_next_data_is_parse_error() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_kalibrr_build_id_from_html("<html></html>")

    assert exc_info.value.stage.value == "parse"
    assert exc_info.value.source_platform == "kalibrr"
