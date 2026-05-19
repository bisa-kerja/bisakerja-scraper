from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ParseError
from integrations.sources.time_utils import parse_source_datetime
from shared.http import HttpClientConfig, JsonHttpClient, SourceHttpClient

DEALLS_SOURCE_PLATFORM = "dealls"
DEALLS_LIST_PATH = "/explore-job/job"
DEALLS_PUBLIC_JOB_BASE_URL = "https://dealls.com/jobs"
DEALLS_MAX_PAGE_SIZE = 20
DEALLS_DEFAULT_HEADERS = {
    "origin": "https://dealls.com",
    "referer": "https://dealls.com/",
    "x-client-app-name": "Deall-Talent-Web",
    "x-client-app-version": "2.0.0",
}


@dataclass(frozen=True)
class DeallsListQuery:
    page: int = 1
    limit: int = DEALLS_MAX_PAGE_SIZE
    search: str | None = None
    sort_param: str | None = "publishedAt"
    sort_by: str | None = "desc"
    status: str | None = "active"
    published: bool | None = True
    boost_the_boosted_job: bool | None = True
    external_platform_apply_url_set: str | None = "null"

    def to_params(self) -> dict[str, str | int | bool]:
        params: dict[str, str | int | bool] = {
            "page": self.page,
            "limit": self.limit,
        }
        if self.sort_param is not None:
            params["sortParam"] = self.sort_param
        if self.sort_by is not None:
            params["sortBy"] = self.sort_by
        if self.status is not None:
            params["status"] = self.status
        if self.published is not None:
            params["published"] = self.published
        if self.boost_the_boosted_job is not None:
            params["boostTheBoostedJob"] = self.boost_the_boosted_job
        if self.external_platform_apply_url_set is not None:
            params["externalPlatformApplyUrlSet"] = self.external_platform_apply_url_set
        if self.search:
            params["search"] = self.search
        return params


class RawSourceJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_platform: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class DeallsPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    limit: int = Field(ge=1)
    total_docs: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class DeallsListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pagination: DeallsPagination
    raw_jobs: list[RawSourceJob]


class DeallsListAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_page(self, query: DeallsListQuery | None = None) -> DeallsListResult:
        query = query or DeallsListQuery()
        payload = await self.http_client.request_json(
            "GET",
            DEALLS_LIST_PATH,
            params=query.to_params(),
        )
        return parse_dealls_list_payload(payload)


def build_dealls_http_client(
    *,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    max_response_bytes: int,
    rate_limit_per_minute: int | None = None,
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=DEALLS_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=DEALLS_DEFAULT_HEADERS,
            rate_limit_per_minute=rate_limit_per_minute,
        )
    )


def parse_dealls_list_payload(payload: dict[str, Any]) -> DeallsListResult:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "Dealls list payload missing data object",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    docs = data.get("docs")
    if not isinstance(docs, list):
        raise ParseError(
            "Dealls list payload missing docs list",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    pagination = DeallsPagination.model_validate(
        {
            "page": _positive_int_or_default(data.get("page"), 1),
            "limit": _positive_int_or_default(data.get("limit"), max(len(docs), 1)),
            "total_docs": _non_negative_int_or_default(data.get("totalDocs"), len(docs)),
            "total_pages": _non_negative_int_or_default(data.get("totalPages"), 0),
        }
    )
    raw_jobs = [_parse_raw_job(raw_job) for raw_job in docs]
    return DeallsListResult(pagination=pagination, raw_jobs=raw_jobs)


def _parse_raw_job(raw_job: Any) -> RawSourceJob:
    if not isinstance(raw_job, dict):
        raise ParseError(
            "Dealls list job must be an object",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    external_id = raw_job.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise ParseError(
            "Dealls list job missing required id",
            source_platform=DEALLS_SOURCE_PLATFORM,
        )

    slug = raw_job.get("slug")
    source_url = build_dealls_source_url(slug if isinstance(slug, str) and slug else external_id)
    return RawSourceJob(
        source_platform=DEALLS_SOURCE_PLATFORM,
        external_id=external_id,
        source_url=source_url,
        raw_payload=raw_job,
    )


def _positive_int_or_default(value: Any, default: int) -> int:
    parsed = _parse_int(value)
    if parsed is None or parsed <= 0:
        return default
    return parsed


def _non_negative_int_or_default(value: Any, default: int) -> int:
    parsed = _parse_int(value)
    if parsed is None or parsed < 0:
        return default
    return parsed


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def extract_dealls_source_timestamp(raw_payload: dict[str, Any]):
    return parse_source_datetime(raw_payload.get("publishedAt")) or parse_source_datetime(
        raw_payload.get("latestUpdatedAt")
    )


def build_dealls_source_url(slug_or_id: str) -> str:
    return f"{DEALLS_PUBLIC_JOB_BASE_URL}/{slug_or_id}"
