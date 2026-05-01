from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import FetchError, ParseError
from integrations.sources.dealls.list import (
    DEALLS_SOURCE_PLATFORM,
    RawSourceJob,
    build_dealls_source_url,
)
from shared.http import JsonHttpClient

DEALLS_DETAIL_SLUG_PATH_TEMPLATE = "/job-portal/job/slug/{slug}"
DEALLS_DETAIL_DEFAULT_PARAMS: dict[str, str | bool] = {
    "trId": "view",
    "guest": True,
}


class DeallsDetailResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]
    description: str | None = None
    requirements: str | None = None


class DeallsDetailAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_detail(self, slug: str) -> DeallsDetailResult:
        payload = await self.http_client.request_json(
            "GET",
            DEALLS_DETAIL_SLUG_PATH_TEMPLATE.format(slug=slug),
            params=DEALLS_DETAIL_DEFAULT_PARAMS,
        )
        return parse_dealls_detail_payload(payload)

    async def fetch_enriched_job(self, list_job: RawSourceJob) -> RawSourceJob:
        slug = _list_job_slug(list_job)
        if slug is None:
            return merge_dealls_list_and_detail(list_job, None, missing_reason="missing_slug")

        try:
            detail = await self.fetch_detail(slug)
        except FetchError as exc:
            if exc.details.get("statusCode") == 404:
                return merge_dealls_list_and_detail(list_job, None, missing_reason="not_found")
            raise

        return merge_dealls_list_and_detail(list_job, detail)


def parse_dealls_detail_payload(payload: dict[str, Any]) -> DeallsDetailResult:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "Dealls detail payload missing data object",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    result = data.get("result")
    if not isinstance(result, dict):
        raise ParseError(
            "Dealls detail payload missing result object",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    external_id = result.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise ParseError(
            "Dealls detail payload missing required id",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    slug = result.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ParseError(
            "Dealls detail payload missing required slug",
            source_platform=DEALLS_SOURCE_PLATFORM,
            external_id=external_id,
        )

    return DeallsDetailResult(
        external_id=external_id,
        slug=slug,
        source_url=build_dealls_source_url(slug),
        raw_payload=result,
        description=_optional_text(result.get("description")),
        requirements=_optional_text(result.get("requirements")),
    )


def merge_dealls_list_and_detail(
    list_job: RawSourceJob,
    detail: DeallsDetailResult | None,
    *,
    missing_reason: str | None = None,
) -> RawSourceJob:
    if detail is None:
        detail_metadata = {
            "coverage": "missing",
            "missingReason": missing_reason or "unavailable",
        }
        detail_payload: dict[str, Any] | None = None
        source_url = list_job.source_url
    else:
        detail_metadata = {
            "coverage": "available",
            "source": "detail",
        }
        detail_payload = detail.raw_payload
        source_url = detail.source_url

    return RawSourceJob(
        source_platform=list_job.source_platform,
        external_id=list_job.external_id,
        source_url=source_url,
        raw_payload={
            "list": list_job.raw_payload,
            "detail": detail_payload,
            "detailMetadata": detail_metadata,
        },
    )


def _list_job_slug(list_job: RawSourceJob) -> str | None:
    slug = list_job.raw_payload.get("slug")
    return slug if isinstance(slug, str) and slug else None


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
