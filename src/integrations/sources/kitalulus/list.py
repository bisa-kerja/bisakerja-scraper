from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ParseError
from integrations.sources.time_utils import parse_source_datetime
from shared.http import HttpClientConfig, JsonHttpClient, SourceHttpClient

KITALULUS_SOURCE_PLATFORM = "kitalulus"
KITALULUS_GRAPHQL_URL = "https://gql.kitalulus.com/graphql"
KITALULUS_GRAPHQL_PATH = "/graphql"
KITALULUS_LIST_OPERATION = "Vacancies"
KITALULUS_PUBLIC_JOB_BASE_URL = "https://www.kitalulus.com/lowongan"
KITALULUS_DEFAULT_HEADERS = {
    "accept": "application/graphql-response+json, application/json;q=0.9",
    "accept-language": "id",
    "content-type": "application/json",
    "origin": "https://www.kitalulus.com",
    "referer": "https://www.kitalulus.com/",
    "x-channel": "web",
}

KITALULUS_LIST_QUERY = """query Vacancies(
  $keyword: String,
  $tag: String,
  $pagination: CommonFilter,
  $filters: [SearchCategoryFilter!],
  $locations: [LocationAreaInput!],
  $haveMisiSeruLimit: Boolean,
  $userMaxEducation: String,
  $userJobSpecializationRoleIds: [ID!]
) {
  vacanciesV4(
    keyword: $keyword,
    tag: $tag,
    pagination: $pagination,
    filters: $filters,
    locations: $locations,
    haveMisiSeruLimit: $haveMisiSeruLimit,
    userMaxEducation: $userMaxEducation,
    userJobSpecializationRoleIds: $userJobSpecializationRoleIds
  ) {
    hasNextPage
    hasPrevPage
    elements
    page
    list {
      id
      slug
      code
      positionName
      isHighlighted
      educationLevelStr
      salaryLowerBound
      salaryUpperBound
      updatedAtStr
      genderStr
      maxAge
      minExperience
      typeStr
      company { name code logoUrl }
      province { name }
      city { name }
      jobRole { displayName }
    }
  }
}"""


@dataclass(frozen=True)
class KitalulusListQuery:
    keyword: str = "developer"
    page: int = 1
    limit: int = 30
    sort: str | None = "updatedAt"

    def to_variables(self) -> dict[str, Any]:
        filters = [
            {"key": "jobSpecializations", "value": []},
            {"key": "companyIndustries", "value": []},
            {"key": "educationLevels", "value": []},
            {"key": "gender", "value": []},
            {"key": "salary", "value": []},
            {"key": "types", "value": []},
            {"key": "jobLevels", "value": []},
            {"key": "locationSites", "value": []},
            {"key": "workExperience", "value": []},
        ]
        if self.sort is not None:
            filters.insert(0, {"key": "sortBy", "value": [self.sort]})
        return {
            "keyword": self.keyword,
            "tag": "",
            "locations": [],
            "haveMisiSeruLimit": True,
            "userMaxEducation": "",
            "userJobSpecializationRoleIds": [],
            "pagination": {"page": self.page, "limit": self.limit},
            "filters": filters,
        }


class RawSourceJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_platform: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class KitalulusPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_count: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next_page: bool = False


class KitalulusListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pagination: KitalulusPagination
    raw_jobs: list[RawSourceJob]
    request_body: dict[str, Any]


class KitalulusListAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_page(self, query: KitalulusListQuery | None = None) -> KitalulusListResult:
        query = query or KitalulusListQuery()
        request_body = build_kitalulus_list_request_body(query)
        payload = await self.http_client.request_json(
            "POST",
            KITALULUS_GRAPHQL_PATH,
            json_body=request_body,
        )
        return parse_kitalulus_list_payload(payload, query=query, request_body=request_body)


def build_kitalulus_http_client(
    *,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    max_response_bytes: int,
    rate_limit_per_minute: int | None = None,
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=KITALULUS_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=KITALULUS_DEFAULT_HEADERS,
            rate_limit_per_minute=rate_limit_per_minute,
        )
    )


def build_kitalulus_list_request_body(query: KitalulusListQuery) -> dict[str, Any]:
    return {
        "operationName": KITALULUS_LIST_OPERATION,
        "variables": query.to_variables(),
        "query": KITALULUS_LIST_QUERY,
    }


def parse_kitalulus_list_payload(
    payload: dict[str, Any],
    *,
    query: KitalulusListQuery | None = None,
    request_body: dict[str, Any] | None = None,
) -> KitalulusListResult:
    if payload.get("errors"):
        raise ParseError(
            "Kitalulus list payload contains GraphQL errors",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "Kitalulus list payload missing data object",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    vacancies = data.get("vacanciesV4")
    if not isinstance(vacancies, dict):
        raise ParseError(
            "Kitalulus list payload missing vacanciesV4 object",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    jobs = vacancies.get("list")
    if not isinstance(jobs, list):
        raise ParseError(
            "Kitalulus list payload missing list array",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )

    query = query or KitalulusListQuery(limit=len(jobs) or 1)
    total_count = max(_optional_int(vacancies.get("elements"), len(jobs)), 0)
    page = max(_optional_int(vacancies.get("page"), query.page), 1)
    page_size = query.limit
    request_body = request_body or build_kitalulus_list_request_body(query)
    return KitalulusListResult(
        pagination=KitalulusPagination(
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=ceil(total_count / page_size) if total_count else 0,
            has_next_page=vacancies.get("hasNextPage") is True,
        ),
        raw_jobs=[_parse_raw_job(job) for job in jobs],
        request_body=request_body,
    )


def build_kitalulus_source_url(slug: str) -> str:
    return f"{KITALULUS_PUBLIC_JOB_BASE_URL}/{slug}"


def extract_kitalulus_source_timestamp(raw_payload: dict[str, Any]):
    detail = raw_payload.get("detail")
    if isinstance(detail, dict):
        parsed = parse_kitalulus_epoch_datetime(detail.get("updatedAt"))
        if parsed is not None:
            return parsed
    list_payload = (
        raw_payload.get("list") if isinstance(raw_payload.get("list"), dict) else raw_payload
    )
    return parse_source_datetime(list_payload.get("updatedAtStr"))


def parse_kitalulus_epoch_datetime(value: Any):
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1_000_000 if value > 10_000_000_000_000 else value / 1000
        return datetime.fromtimestamp(seconds, tz=UTC)
    return parse_source_datetime(value)


def _parse_raw_job(raw_job: Any) -> RawSourceJob:
    if not isinstance(raw_job, dict):
        raise ParseError(
            "Kitalulus list job must be an object",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    external_id = raw_job.get("id")
    slug = raw_job.get("slug")
    title = raw_job.get("positionName")
    company = raw_job.get("company")
    company_name = company.get("name") if isinstance(company, dict) else None
    if not isinstance(external_id, str) or not external_id.strip():
        raise ParseError(
            "Kitalulus list job missing required id",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    if not isinstance(slug, str) or not slug.strip():
        raise ParseError(
            "Kitalulus list job missing required slug",
            source_platform=KITALULUS_SOURCE_PLATFORM,
            external_id=external_id,
        )
    if not isinstance(title, str) or not title.strip():
        raise ParseError(
            "Kitalulus list job missing required positionName",
            source_platform=KITALULUS_SOURCE_PLATFORM,
            external_id=external_id,
        )
    if not isinstance(company_name, str) or not company_name.strip():
        raise ParseError(
            "Kitalulus list job missing required company.name",
            source_platform=KITALULUS_SOURCE_PLATFORM,
            external_id=external_id,
        )
    return RawSourceJob(
        source_platform=KITALULUS_SOURCE_PLATFORM,
        external_id=external_id,
        source_url=build_kitalulus_source_url(slug),
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
