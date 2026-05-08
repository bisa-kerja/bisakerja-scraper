import json
from pathlib import Path
from typing import Any

import pytest

from core.errors import ConfigError, FetchError, ParseError
from integrations.sources.jobstreet import (
    JOBSTREET_DETAIL_OPERATION,
    JOBSTREET_GRAPHQL_OPERATION,
    JOBSTREET_GRAPHQL_PATH,
    JOBSTREET_PUBLIC_DEFAULT_HEADERS,
    JobStreetDetailAdapter,
    JobStreetDetailQuery,
    JobStreetListAdapter,
    JobStreetListQuery,
    build_jobstreet_default_headers,
    build_jobstreet_detail_request_body,
    build_jobstreet_list_request_body,
    build_jobstreet_public_headers,
    extract_jobstreet_source_timestamp,
    merge_jobstreet_list_and_detail,
    parse_jobstreet_detail_payload,
    parse_jobstreet_list_payload,
)


class MockJsonClient:
    def __init__(self, payload: dict[str, Any] | None, *, error: FetchError | None = None) -> None:
        self.payload = payload
        self.error = error
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
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload


def load_fixture(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_parse_jobstreet_list_fixture_produces_raw_jobs() -> None:
    result = parse_jobstreet_list_payload(
        load_fixture("tests/fixtures/raw/jobstreet/sample.json"),
        query=JobStreetListQuery(keywords="developer", page=2, page_size=32),
    )

    assert result.pagination.page == 2
    assert result.pagination.page_size == 32
    assert result.pagination.total_count == 578
    assert result.pagination.total_pages == 19
    assert len(result.raw_jobs) == 2
    assert result.raw_jobs[0].source_platform == "jobstreet"
    assert result.raw_jobs[0].external_id == "91789576"
    assert result.raw_jobs[0].source_url.endswith("/91789576")
    assert result.raw_jobs[1].raw_payload["salaryLabel"] == ""
    assert (
        extract_jobstreet_source_timestamp(result.raw_jobs[0].raw_payload)
        .isoformat()
        .startswith("2026-04-28T09:08:34+00:00")
    )


@pytest.mark.asyncio
async def test_jobstreet_list_adapter_sends_sanitized_graphql_request_shape() -> None:
    http_client = MockJsonClient(load_fixture("tests/fixtures/raw/jobstreet/sample.json"))
    adapter = JobStreetListAdapter(http_client)
    query = JobStreetListQuery(
        keywords="developer",
        page=2,
        page_size=32,
        date_range=7,
        new_since="2026-04-28",
    )
    expected_body = build_jobstreet_list_request_body(query)

    result = await adapter.fetch_page(query)

    assert result.request_body == expected_body
    assert http_client.requests == [
        {
            "method": "POST",
            "url": JOBSTREET_GRAPHQL_PATH,
            "params": None,
            "headers": None,
            "json_body": expected_body,
        }
    ]
    request_json = json.dumps(expected_body).lower()
    assert JOBSTREET_GRAPHQL_OPERATION.lower() in request_json
    assert "authorization" not in request_json
    assert "bearer" not in request_json
    assert "cookie" not in request_json
    assert "eventcapture" not in request_json


def test_jobstreet_missing_bearer_is_config_error() -> None:
    with pytest.raises(ConfigError) as exc_info:
        build_jobstreet_default_headers(" ")

    assert exc_info.value.stage.value == "config"
    assert exc_info.value.source_platform == "jobstreet"
    assert exc_info.value.details == {"configKey": "JOBSTREET_BEARER_TOKEN"}


def test_jobstreet_public_headers_exclude_authorization() -> None:
    assert "authorization" not in JOBSTREET_PUBLIC_DEFAULT_HEADERS
    assert JOBSTREET_PUBLIC_DEFAULT_HEADERS["x-seek-site"] == "chalice"


def test_jobstreet_public_headers_can_include_cookie() -> None:
    headers = build_jobstreet_public_headers("cf_clearance=test-cookie")
    assert headers["cookie"] == "cf_clearance=test-cookie"


def test_jobstreet_default_headers_can_include_cookie() -> None:
    headers = build_jobstreet_default_headers(
        "test-bearer-token",
        cookie_header="cf_clearance=test-cookie",
    )
    assert headers["authorization"] == "Bearer test-bearer-token"
    assert headers["cookie"] == "cf_clearance=test-cookie"


def test_parse_jobstreet_detail_fixture_preserves_html_description() -> None:
    detail = parse_jobstreet_detail_payload(
        load_fixture("tests/fixtures/raw/jobstreet/detail.json")
    )

    assert detail.external_id == "91788065"
    assert detail.source_url == "https://id.jobstreet.com/id/job/91788065"
    assert detail.html_description.startswith("<p><strong>PROGRAMMER")
    assert "Minimal 10 tahun" in detail.html_description
    assert detail.abstract.startswith("- Gaji pokok")


@pytest.mark.asyncio
async def test_jobstreet_detail_adapter_fetches_by_generated_context() -> None:
    http_client = MockJsonClient(load_fixture("tests/fixtures/raw/jobstreet/detail.json"))
    adapter = JobStreetDetailAdapter(http_client)
    query = JobStreetDetailQuery(
        job_id="91788065",
        correlation_id="00000000-0000-4000-8000-000000000001",
        session_id="00000000-0000-4000-8000-000000000002",
        visitor_id="00000000-0000-4000-8000-000000000003",
    )
    expected_body = build_jobstreet_detail_request_body(query)

    detail = await adapter.fetch_detail("91788065", query=query)

    assert detail.external_id == "91788065"
    assert http_client.requests == [
        {
            "method": "POST",
            "url": JOBSTREET_GRAPHQL_PATH,
            "params": None,
            "headers": None,
            "json_body": expected_body,
        }
    ]
    assert http_client.requests[0]["json_body"]["operationName"] == JOBSTREET_DETAIL_OPERATION


def test_merge_jobstreet_list_and_detail_keeps_html_raw_only() -> None:
    list_result = parse_jobstreet_list_payload(
        load_fixture("tests/fixtures/raw/jobstreet/sample.json")
    )
    detail = parse_jobstreet_detail_payload(
        load_fixture("tests/fixtures/raw/jobstreet/detail.json")
    )

    enriched = merge_jobstreet_list_and_detail(list_result.raw_jobs[0], detail)

    assert enriched.raw_payload["detail"]["job"]["content"].startswith("<p><strong>")
    assert enriched.raw_payload["detailMetadata"] == {
        "coverage": "available",
        "source": "detail",
        "detailCompleteness": "complete",
        "attempted": True,
        "htmlFields": ["job.content"],
    }
    assert "cleanText" not in enriched.raw_payload


def test_parse_jobstreet_detail_payload_classifies_graphql_errors() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_jobstreet_detail_payload({"errors": [{"message": "bad auth"}]})

    assert exc_info.value.stage.value == "parse"
    assert exc_info.value.source_platform == "jobstreet"


@pytest.mark.asyncio
async def test_jobstreet_detail_fetch_failure_keeps_list_payload_with_reason() -> None:
    list_result = parse_jobstreet_list_payload(
        load_fixture("tests/fixtures/raw/jobstreet/sample.json"),
        query=JobStreetListQuery(keywords="developer"),
    )
    adapter = JobStreetDetailAdapter(
        MockJsonClient(
            None,
            error=FetchError(
                "rate limited",
                source_platform="jobstreet",
                details={"statusCode": 429},
                retryable=True,
            ),
        )
    )

    enriched = await adapter.fetch_enriched_job(list_result.raw_jobs[0])

    assert enriched.raw_payload["detail"] is None
    assert enriched.raw_payload["detailMetadata"] == {
        "coverage": "missing",
        "missingReason": "rate_limited",
        "detailCompleteness": "partial",
        "attempted": True,
        "failureRetryable": True,
    }
