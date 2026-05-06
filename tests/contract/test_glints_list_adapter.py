import json
from pathlib import Path
from typing import Any

import pytest

from core.errors import ParseError
from integrations.sources.glints import (
    GLINTS_GRAPHQL_OPERATION,
    GLINTS_GRAPHQL_PATH,
    GlintsListAdapter,
    GlintsListQuery,
    build_glints_detail_fallback,
    build_glints_list_request_body,
    extract_glints_source_timestamp,
    merge_glints_list_with_fallback,
    parse_glints_list_payload,
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


def load_fixture(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_parse_glints_list_fixture_produces_raw_jobs() -> None:
    result = parse_glints_list_payload(
        load_fixture("tests/fixtures/raw/glints/sample.json"),
        query=GlintsListQuery(search_term="developer"),
    )

    assert result.pagination.page == 1
    assert result.pagination.page_size == 30
    assert result.pagination.has_more is True
    assert len(result.raw_jobs) == 2
    assert result.raw_jobs[0].source_platform == "glints"
    assert result.raw_jobs[0].external_id == "aaed8a7f-de12-479c-8df8-56f26b35bed9"
    assert result.raw_jobs[0].source_url.endswith("/aaed8a7f-de12-479c-8df8-56f26b35bed9")
    assert result.raw_jobs[0].raw_payload["title"] == "Full Stack Developer"
    assert (
        extract_glints_source_timestamp(result.raw_jobs[0].raw_payload)
        .isoformat()
        .startswith("2026-05-01T04:41:42.821000+00:00")
    )


@pytest.mark.asyncio
async def test_glints_list_adapter_sends_sanitized_graphql_request_shape() -> None:
    http_client = MockJsonClient(load_fixture("tests/fixtures/raw/glints/sample.json"))
    adapter = GlintsListAdapter(http_client)
    query = GlintsListQuery(search_term="developer", page=1, page_size=30)
    expected_body = build_glints_list_request_body(query)

    result = await adapter.fetch_page(query)

    assert result.request_body == expected_body
    assert http_client.requests == [
        {
            "method": "POST",
            "url": GLINTS_GRAPHQL_PATH,
            "params": {"op": GLINTS_GRAPHQL_OPERATION},
            "headers": None,
            "json_body": expected_body,
        }
    ]
    request_json = json.dumps(expected_body).lower()
    assert "cookie" not in request_json
    assert "authorization" not in request_json
    assert "token" not in request_json
    assert "traceinfo" not in request_json


def test_glints_request_body_matches_fixture_shape() -> None:
    request_fixture = load_fixture("tests/fixtures/raw/glints/search_jobs_v3_request.json")
    request_body = build_glints_list_request_body(
        GlintsListQuery(search_term="developer", page=1, page_size=30)
    )

    assert request_body["operationName"] == request_fixture["operationName"]
    assert request_body["variables"] == request_fixture["variables"]
    assert "jobsInPage" in request_body["query"]
    assert "traceInfo" not in request_body["query"]


def test_glints_detail_fallback_keeps_job_valid_with_list_provenance() -> None:
    result = parse_glints_list_payload(load_fixture("tests/fixtures/raw/glints/sample.json"))

    fallback = build_glints_detail_fallback(result.raw_jobs[0])

    assert fallback.detail_coverage == "unavailable"
    assert fallback.detail_completeness == "partial"
    assert fallback.source_url.endswith("/aaed8a7f-de12-479c-8df8-56f26b35bed9")
    assert fallback.external_apply_url == fallback.source_url
    assert fallback.field_provenance["title"] == "list.title"
    assert fallback.field_provenance["description"] == "unavailable"
    assert fallback.field_provenance["external_apply_url"] == "source_url_fallback"
    assert fallback.raw_payload["title"] == "Full Stack Developer"


def test_glints_merge_wraps_list_payload_with_unavailable_detail_metadata() -> None:
    result = parse_glints_list_payload(load_fixture("tests/fixtures/raw/glints/sample.json"))

    wrapped = merge_glints_list_with_fallback(result.raw_jobs[0])

    assert wrapped.raw_payload["detail"] is None
    assert wrapped.raw_payload["detailMetadata"] == {
        "coverage": "unavailable",
        "detailCompleteness": "partial",
        "missingReason": "unavailable",
        "attempted": False,
    }


def test_parse_glints_list_payload_classifies_graphql_errors() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_glints_list_payload({"errors": [{"message": "bad query"}]})

    assert exc_info.value.stage.value == "parse"
    assert exc_info.value.source_platform == "glints"
