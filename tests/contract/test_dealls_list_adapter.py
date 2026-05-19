import json
from pathlib import Path
from typing import Any

import pytest

from core.errors import ParseError
from integrations.sources.dealls import (
    DeallsListAdapter,
    DeallsListQuery,
    extract_dealls_source_timestamp,
    parse_dealls_list_payload,
)


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


def load_dealls_fixture() -> dict[str, Any]:
    fixture_path = Path("tests/fixtures/raw/dealls/sample.json")
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_parse_dealls_list_fixture_produces_raw_jobs() -> None:
    result = parse_dealls_list_payload(load_dealls_fixture())

    assert result.pagination.page == 1
    assert result.pagination.total_pages == 7
    assert len(result.raw_jobs) == 2
    assert result.raw_jobs[0].source_platform == "dealls"
    assert result.raw_jobs[0].external_id == "69f30ce4b9f8ed001233b47c"
    assert result.raw_jobs[0].source_url.endswith("/academy-project-development-officer")
    assert result.raw_jobs[0].raw_payload["role"] == "Academy Project Development Officer"
    assert (
        extract_dealls_source_timestamp(result.raw_jobs[0].raw_payload)
        .isoformat()
        .startswith("2026-04-30T08:03:48.066000+00:00")
    )


@pytest.mark.asyncio
async def test_dealls_list_adapter_sends_expected_query_params() -> None:
    http_client = MockJsonClient(load_dealls_fixture())
    adapter = DeallsListAdapter(http_client)

    result = await adapter.fetch_page(DeallsListQuery(page=2, limit=10, search="developer"))

    assert len(result.raw_jobs) == 2
    assert http_client.requests == [
        {
            "method": "GET",
            "url": "/explore-job/job",
            "params": {
                "page": 2,
                "limit": 10,
                "sortParam": "publishedAt",
                "sortBy": "desc",
                "status": "active",
                "published": True,
                "boostTheBoostedJob": True,
                "externalPlatformApplyUrlSet": "null",
                "search": "developer",
            },
            "headers": None,
            "json_body": None,
        }
    ]


def test_dealls_list_query_can_omit_latest_filters() -> None:
    params = DeallsListQuery(
        page=1,
        limit=10,
        search="developer",
        sort_param=None,
        sort_by=None,
        status=None,
        published=None,
        boost_the_boosted_job=None,
        external_platform_apply_url_set=None,
    ).to_params()

    assert params == {"page": 1, "limit": 10, "search": "developer"}


def test_parse_dealls_list_payload_classifies_missing_docs() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_dealls_list_payload({"data": {"page": 1}})

    assert exc_info.value.stage.value == "parse"
    assert exc_info.value.source_platform == "dealls"
    assert exc_info.value.retryable is False


def test_parse_dealls_list_payload_tolerates_zero_limit_on_empty_docs() -> None:
    result = parse_dealls_list_payload(
        {
            "data": {
                "page": 1,
                "limit": 0,
                "totalDocs": 0,
                "totalPages": 0,
                "docs": [],
            }
        }
    )

    assert result.pagination.page == 1
    assert result.pagination.limit == 1
    assert result.pagination.total_docs == 0
    assert result.pagination.total_pages == 0
    assert result.raw_jobs == []
