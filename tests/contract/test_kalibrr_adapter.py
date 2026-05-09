import json
from pathlib import Path
from typing import Any

import pytest

from integrations.sources.kalibrr import (
    KALIBRR_LIST_PATH_TEMPLATE,
    KalibrrBuildIdResolver,
    KalibrrListAdapter,
    KalibrrListQuery,
    extract_kalibrr_source_timestamp,
    merge_kalibrr_list_and_detail,
    parse_kalibrr_detail_payload,
    parse_kalibrr_list_payload,
)


class MockHtmlClient:
    async def request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        return '<script id="__NEXT_DATA__" type="application/json">{"buildId":"BUILD_123"}</script>'


class MockJsonClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[dict[str, Any]] = []

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
        return self.payload


def load_fixture(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_parse_kalibrr_list_fixture_produces_raw_jobs() -> None:
    result = parse_kalibrr_list_payload(load_fixture("tests/fixtures/raw/kalibrr/sample.json"))

    assert result.pagination.offset == 0
    assert result.pagination.limit == 15
    assert result.pagination.total_count == 283
    assert len(result.raw_jobs) == 2
    assert result.raw_jobs[0].source_platform == "kalibrr"
    assert result.raw_jobs[0].external_id == "265196"
    assert "/c/simbadda-group/jobs/265196/" in result.raw_jobs[0].source_url
    assert (
        extract_kalibrr_source_timestamp(result.raw_jobs[0].raw_payload)
        .isoformat()
        .startswith("2026-05-01T03:51:58.260489+00:00")
    )


@pytest.mark.asyncio
async def test_kalibrr_list_adapter_uses_dynamic_build_id_path() -> None:
    payload = load_fixture("tests/fixtures/raw/kalibrr/sample.json")
    http_client = MockJsonClient(payload)
    resolver = KalibrrBuildIdResolver(MockHtmlClient())
    adapter = KalibrrListAdapter(http_client, resolver)
    query = KalibrrListQuery(category="te", keyword="developer", offset=0)

    result = await adapter.fetch_page(query)

    assert result.raw_jobs[0].external_id == "265196"
    assert http_client.requests[0]["url"] == KALIBRR_LIST_PATH_TEMPLATE.format(
        build_id="BUILD_123",
        category="te",
        keyword="developer",
    )
    assert http_client.requests[0]["headers"] == {"x-nextjs-data": "1"}


def test_kalibrr_list_query_can_omit_freshness_sort() -> None:
    params = KalibrrListQuery(category="te", keyword="developer", offset=0, sort=None).to_params()

    assert params == {"param": ["te", "developer"], "offset": 0}


def test_kalibrr_embedded_detail_keeps_html_metadata() -> None:
    result = parse_kalibrr_list_payload(load_fixture("tests/fixtures/raw/kalibrr/sample.json"))
    detail = parse_kalibrr_detail_payload(result.raw_jobs[0].raw_payload)
    enriched = merge_kalibrr_list_and_detail(result.raw_jobs[0])

    assert detail.html_description.startswith("<p><strong>1. Revenue Ownership")
    assert "Bachelor" in detail.html_qualifications
    assert enriched.raw_payload["detailMetadata"] == {
        "coverage": "embedded",
        "source": "list_job",
        "detailCompleteness": "complete",
        "htmlFields": ["description", "qualifications"],
    }
