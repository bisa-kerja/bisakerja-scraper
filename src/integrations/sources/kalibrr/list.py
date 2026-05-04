from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ParseError
from integrations.sources.kalibrr.build_id import (
    KALIBRR_SOURCE_PLATFORM,
    KalibrrBuildIdResolver,
    request_kalibrr_data_with_build_refresh,
)
from integrations.sources.time_utils import parse_source_datetime
from shared.http import HttpClientConfig, JsonHttpClient, SourceHttpClient

KALIBRR_BASE_URL = "https://www.kalibrr.id"
KALIBRR_LIST_PATH_TEMPLATE = "/_next/data/{build_id}/id-ID/home/{category}/{keyword}.json"
KALIBRR_PUBLIC_JOB_BASE_URL = "https://www.kalibrr.id"
KALIBRR_DEFAULT_HEADERS = {
    "accept": "*/*",
    "referer": "https://www.kalibrr.id/",
}


@dataclass(frozen=True)
class KalibrrListQuery:
    category: str = "te"
    keyword: str = "developer"
    sort: str = "Freshness"
    offset: int = 0

    def path_template(self) -> str:
        return KALIBRR_LIST_PATH_TEMPLATE.format(
            build_id="{build_id}",
            category=self.category,
            keyword=quote(self.keyword, safe=""),
        )

    def to_params(self) -> dict[str, Any]:
        return {
            "sort": self.sort,
            "param": [self.category, self.keyword],
            "offset": self.offset,
        }


class RawSourceJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_platform: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class KalibrrPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total_count: int = Field(ge=0)


class KalibrrListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pagination: KalibrrPagination
    raw_jobs: list[RawSourceJob]


class KalibrrListAdapter:
    def __init__(
        self,
        http_client: JsonHttpClient,
        build_id_resolver: KalibrrBuildIdResolver,
    ) -> None:
        self.http_client = http_client
        self.build_id_resolver = build_id_resolver

    async def fetch_page(self, query: KalibrrListQuery | None = None) -> KalibrrListResult:
        query = query or KalibrrListQuery()
        payload = await request_kalibrr_data_with_build_refresh(
            json_client=self.http_client,
            resolver=self.build_id_resolver,
            path_template=query.path_template(),
            params=query.to_params(),
        )
        return parse_kalibrr_list_payload(payload)


def build_kalibrr_http_client(
    *,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    max_response_bytes: int,
    rate_limit_per_minute: int | None = None,
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=KALIBRR_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=KALIBRR_DEFAULT_HEADERS,
            rate_limit_per_minute=rate_limit_per_minute,
        )
    )


def parse_kalibrr_list_payload(payload: dict[str, Any]) -> KalibrrListResult:
    page_props = payload.get("pageProps")
    if not isinstance(page_props, dict):
        raise ParseError(
            "Kalibrr list payload missing pageProps object",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    jobs = page_props.get("jobs")
    if not isinstance(jobs, list):
        raise ParseError(
            "Kalibrr list payload missing jobs list",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    filters = page_props.get("filters")
    filters = filters if isinstance(filters, dict) else {}
    pagination = KalibrrPagination(
        offset=_optional_int(filters.get("offset"), 0),
        limit=_optional_int(filters.get("limit"), len(jobs) or 1),
        total_count=_optional_int(page_props.get("count"), len(jobs)),
    )
    return KalibrrListResult(
        pagination=pagination,
        raw_jobs=[_parse_raw_job(job) for job in jobs],
    )


def build_kalibrr_source_url(raw_job: dict[str, Any]) -> str:
    external_id = str(raw_job.get("id"))
    slug = raw_job.get("slug")
    company = raw_job.get("company")
    company_code = company.get("code") if isinstance(company, dict) else None
    if isinstance(company_code, str) and company_code and isinstance(slug, str) and slug:
        return f"{KALIBRR_PUBLIC_JOB_BASE_URL}/c/{company_code}/jobs/{external_id}/{slug}"
    if isinstance(slug, str) and slug:
        return f"{KALIBRR_PUBLIC_JOB_BASE_URL}/jobs/{external_id}/{slug}"
    return f"{KALIBRR_PUBLIC_JOB_BASE_URL}/jobs/{external_id}"


def extract_kalibrr_source_timestamp(raw_payload: dict[str, Any]):
    return (
        parse_source_datetime(raw_payload.get("activationDate"))
        or parse_source_datetime(raw_payload.get("createdAt"))
        or parse_source_datetime(raw_payload.get("updatedAt"))
    )


def _parse_raw_job(raw_job: Any) -> RawSourceJob:
    if not isinstance(raw_job, dict):
        raise ParseError(
            "Kalibrr list job must be an object",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    external_id = raw_job.get("id")
    if isinstance(external_id, bool) or not isinstance(external_id, int | str):
        raise ParseError(
            "Kalibrr list job missing required id",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    external_id_str = str(external_id)
    if not external_id_str:
        raise ParseError(
            "Kalibrr list job missing required id",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    return RawSourceJob(
        source_platform=KALIBRR_SOURCE_PLATFORM,
        external_id=external_id_str,
        source_url=build_kalibrr_source_url(raw_job),
        raw_payload=raw_job,
    )


def _optional_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return fallback
