import json
from pathlib import Path
from typing import Any

import pytest

from core.errors import FetchError, ParseError
from integrations.sources.dealls import (
    DEALLS_DETAIL_DEFAULT_PARAMS,
    DEALLS_DETAIL_SLUG_PATH_TEMPLATE,
    DeallsDetailAdapter,
    merge_dealls_list_and_detail,
    parse_dealls_detail_payload,
    parse_dealls_list_payload,
)


class MockJsonClient:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: FetchError | None = None,
    ) -> None:
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


def test_parse_dealls_detail_fixture_enriches_description_and_requirements() -> None:
    detail = parse_dealls_detail_payload(load_fixture("tests/fixtures/raw/dealls/detail.json"))

    assert detail.external_id == "69f076da6ab1470012b80d07"
    assert detail.slug == "frontend-developer-23"
    assert detail.requirements == "<p>Minimum 3 years of experience as Frontend Engineer</p>"
    assert detail.source_url.endswith("/frontend-developer-23")


def test_merge_dealls_list_and_detail_keeps_both_payloads() -> None:
    list_result = parse_dealls_list_payload(load_fixture("tests/fixtures/raw/dealls/sample.json"))
    list_job = list_result.raw_jobs[0]
    detail = parse_dealls_detail_payload(load_fixture("tests/fixtures/raw/dealls/detail.json"))

    enriched = merge_dealls_list_and_detail(list_job, detail)

    assert enriched.external_id == list_job.external_id
    assert enriched.raw_payload["list"]["role"] == "Academy Project Development Officer"
    assert enriched.raw_payload["detail"]["requirements"].startswith("<p>Minimum 3 years")
    assert enriched.raw_payload["detailMetadata"] == {
        "coverage": "available",
        "source": "detail",
        "detailCompleteness": "complete",
        "attempted": True,
    }


@pytest.mark.asyncio
async def test_dealls_detail_adapter_fetches_by_slug_without_tracking_id() -> None:
    http_client = MockJsonClient(load_fixture("tests/fixtures/raw/dealls/detail.json"))
    adapter = DeallsDetailAdapter(http_client)

    detail = await adapter.fetch_detail("frontend-developer-23")

    assert detail.slug == "frontend-developer-23"
    assert http_client.requests == [
        {
            "method": "GET",
            "url": DEALLS_DETAIL_SLUG_PATH_TEMPLATE.format(slug="frontend-developer-23"),
            "params": DEALLS_DETAIL_DEFAULT_PARAMS,
            "headers": None,
            "json_body": None,
        }
    ]


@pytest.mark.asyncio
async def test_dealls_missing_detail_does_not_stop_enrichment() -> None:
    list_result = parse_dealls_list_payload(load_fixture("tests/fixtures/raw/dealls/sample.json"))
    missing_detail = FetchError(
        "missing",
        source_platform="dealls",
        details={"statusCode": 404},
        retryable=False,
    )
    adapter = DeallsDetailAdapter(MockJsonClient(error=missing_detail))

    enriched = await adapter.fetch_enriched_job(list_result.raw_jobs[0])

    assert enriched.raw_payload["detail"] is None
    assert enriched.raw_payload["detailMetadata"] == {
        "coverage": "missing",
        "missingReason": "not_found",
        "detailCompleteness": "partial",
        "attempted": True,
        "failureRetryable": False,
    }


def test_parse_dealls_detail_payload_classifies_missing_result() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_dealls_detail_payload({"data": {}})

    assert exc_info.value.stage.value == "parse"
    assert exc_info.value.source_platform == "dealls"
