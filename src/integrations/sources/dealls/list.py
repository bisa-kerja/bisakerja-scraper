from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ParseError
from shared.http import HttpClientConfig, JsonHttpClient, SourceHttpClient

DEALLS_SOURCE_PLATFORM = "dealls"
DEALLS_LIST_PATH = "/explore-job/job"
DEALLS_PUBLIC_JOB_BASE_URL = "https://dealls.com/jobs"
DEALLS_DEFAULT_HEADERS = {
    "origin": "https://dealls.com",
    "referer": "https://dealls.com/",
    "x-client-app-name": "Deall-Talent-Web",
    "x-client-app-version": "2.0.0",
}


@dataclass(frozen=True)
class DeallsListQuery:
    page: int = 1
    limit: int = 18
    search: str | None = None
    sort_param: str = "publishedAt"
    sort_by: str = "desc"
    status: str = "active"
    published: bool = True
    boost_the_boosted_job: bool = True
    external_platform_apply_url_set: str = "null"

    def to_params(self) -> dict[str, str | int | bool]:
        params: dict[str, str | int | bool] = {
            "page": self.page,
            "limit": self.limit,
            "sortParam": self.sort_param,
            "sortBy": self.sort_by,
            "status": self.status,
            "published": self.published,
            "boostTheBoostedJob": self.boost_the_boosted_job,
            "externalPlatformApplyUrlSet": self.external_platform_apply_url_set,
        }
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
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=DEALLS_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=DEALLS_DEFAULT_HEADERS,
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
            "page": data.get("page"),
            "limit": data.get("limit", len(docs)) or len(docs),
            "total_docs": data.get("totalDocs", len(docs)),
            "total_pages": data.get("totalPages", 0),
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


def build_dealls_source_url(slug_or_id: str) -> str:
    return f"{DEALLS_PUBLIC_JOB_BASE_URL}/{slug_or_id}"
