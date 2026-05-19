from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConfigError, ParseError
from integrations.sources.time_utils import parse_source_datetime
from shared.http import HttpClientConfig, JsonHttpClient, SourceHttpClient

JOBSTREET_SOURCE_PLATFORM = "jobstreet"
JOBSTREET_GRAPHQL_PATH = "/graphql"
JOBSTREET_GRAPHQL_OPERATION = "JobSearchV6"
JOBSTREET_PUBLIC_JOB_BASE_URL = "https://id.jobstreet.com/id/job"
JOBSTREET_DEFAULT_HEADERS = {
    "accept": "application/graphql-response+json, application/json;q=0.9",
    "content-type": "application/json",
    "origin": "https://id.jobstreet.com",
    "referer": "https://id.jobstreet.com/",
    "x-seek-site": "chalice",
}
JOBSTREET_PUBLIC_DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "origin": "https://id.jobstreet.com",
    "referer": "https://id.jobstreet.com/",
    "x-seek-site": "chalice",
}

JOBSTREET_SEARCH_QUERY = """query JobSearchV6($params: JobSearchParamsInput) {
  jobSearchV6(params: $params) {
    data {
      id
      title
      roleId
      teaser
      companyName
      salaryLabel
      listingDate {
        dateTimeUtc
        label
        __typename
      }
      locations {
        label
        countryCode
        __typename
      }
      classifications {
        classification {
          description
          id
          __typename
        }
        subclassification {
          description
          id
          __typename
        }
        __typename
      }
      workTypes
      workArrangements {
        displayText
        __typename
      }
      advertiser {
        description
        id
        __typename
      }
      branding {
        serpLogoUrl
        __typename
      }
      bulletPoints
      tags {
        label
        type
        __typename
      }
      __typename
    }
    totalCount
    __typename
  }
}"""


@dataclass(frozen=True)
class JobStreetListQuery:
    keywords: str | None = None
    page: int = 1
    page_size: int = 32
    date_range: int | None = 7
    new_since: str | None = None
    site_key: str = "ID"
    channel: str = "mobileWeb"

    def to_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "channel": self.channel,
            "page": self.page,
            "pageSize": self.page_size,
            "siteKey": self.site_key,
        }
        if self.keywords:
            params["keywords"] = self.keywords
        if self.date_range is not None:
            params["dateRange"] = self.date_range
        if self.new_since:
            params["newSince"] = self.new_since
        return params


class RawSourceJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_platform: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class JobStreetPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_count: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class JobStreetListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pagination: JobStreetPagination
    raw_jobs: list[RawSourceJob]
    request_body: dict[str, Any]


class JobStreetListAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_page(self, query: JobStreetListQuery | None = None) -> JobStreetListResult:
        query = query or JobStreetListQuery()
        request_body = build_jobstreet_list_request_body(query)
        payload = await self.http_client.request_json(
            "POST",
            JOBSTREET_GRAPHQL_PATH,
            json_body=request_body,
        )
        return parse_jobstreet_list_payload(payload, query=query, request_body=request_body)


def build_jobstreet_http_client(
    *,
    base_url: str,
    bearer_token: str | None,
    cookie_header: str | None = None,
    timeout_seconds: float,
    max_retries: int,
    max_response_bytes: int,
    rate_limit_per_minute: int | None = None,
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=JOBSTREET_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=build_jobstreet_default_headers(
                bearer_token,
                cookie_header=cookie_header,
            ),
            rate_limit_per_minute=rate_limit_per_minute,
        )
    )


def build_jobstreet_public_http_client(
    *,
    base_url: str,
    cookie_header: str | None = None,
    timeout_seconds: float,
    max_retries: int,
    max_response_bytes: int,
    rate_limit_per_minute: int | None = None,
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=JOBSTREET_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=build_jobstreet_public_headers(cookie_header),
            rate_limit_per_minute=rate_limit_per_minute,
        )
    )


def build_jobstreet_default_headers(
    bearer_token: str | None,
    *,
    cookie_header: str | None = None,
) -> dict[str, str]:
    if bearer_token is None or not bearer_token.strip():
        raise ConfigError(
            "JobStreet bearer token is required",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
            details={"configKey": "JOBSTREET_BEARER_TOKEN"},
            retryable=False,
        )
    headers = {
        **JOBSTREET_DEFAULT_HEADERS,
        "authorization": f"Bearer {bearer_token.strip()}",
    }
    if cookie_header is not None and cookie_header.strip():
        headers["cookie"] = cookie_header.strip()
    return headers


def build_jobstreet_public_headers(cookie_header: str | None = None) -> dict[str, str]:
    headers = {**JOBSTREET_PUBLIC_DEFAULT_HEADERS}
    if cookie_header is not None and cookie_header.strip():
        headers["cookie"] = cookie_header.strip()
    return headers


def build_jobstreet_list_request_body(query: JobStreetListQuery) -> dict[str, Any]:
    return {
        "operationName": JOBSTREET_GRAPHQL_OPERATION,
        "variables": {"params": query.to_params()},
        "query": JOBSTREET_SEARCH_QUERY,
    }


def parse_jobstreet_list_payload(
    payload: dict[str, Any],
    *,
    query: JobStreetListQuery | None = None,
    request_body: dict[str, Any] | None = None,
) -> JobStreetListResult:
    if payload.get("errors"):
        raise ParseError(
            "JobStreet list payload contains GraphQL errors",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "JobStreet list payload missing data object",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    search_result = data.get("jobSearchV6")
    if not isinstance(search_result, dict):
        raise ParseError(
            "JobStreet list payload missing jobSearchV6 object",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    jobs = search_result.get("data")
    if not isinstance(jobs, list):
        raise ParseError(
            "JobStreet list payload missing data list",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    query = query or _query_from_payload(search_result, len(jobs))
    total_count = _optional_int(search_result.get("totalCount"), len(jobs))
    pagination = JobStreetPagination(
        page=query.page,
        page_size=query.page_size,
        total_count=total_count,
        total_pages=ceil(total_count / query.page_size) if total_count else 0,
    )
    request_body = request_body or build_jobstreet_list_request_body(query)
    raw_jobs = [_parse_raw_job(raw_job) for raw_job in jobs]
    return JobStreetListResult(
        pagination=pagination,
        raw_jobs=raw_jobs,
        request_body=request_body,
    )


def build_jobstreet_source_url(job_id: str) -> str:
    return f"{JOBSTREET_PUBLIC_JOB_BASE_URL}/{job_id}"


def extract_jobstreet_source_timestamp(raw_payload: dict[str, Any]):
    listing_date = raw_payload.get("listingDate")
    if isinstance(listing_date, dict):
        parsed = parse_source_datetime(listing_date.get("dateTimeUtc"))
        if parsed is not None:
            return parsed
    detail = raw_payload.get("detail")
    if isinstance(detail, dict):
        job = detail.get("job")
        if isinstance(job, dict):
            listed_at = job.get("listedAt")
            if isinstance(listed_at, dict):
                return parse_source_datetime(listed_at.get("dateTimeUtc"))
    return None


def _parse_raw_job(raw_job: Any) -> RawSourceJob:
    if not isinstance(raw_job, dict):
        raise ParseError(
            "JobStreet list job must be an object",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    external_id = raw_job.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise ParseError(
            "JobStreet list job missing required id",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    return RawSourceJob(
        source_platform=JOBSTREET_SOURCE_PLATFORM,
        external_id=external_id,
        source_url=build_jobstreet_source_url(external_id),
        raw_payload=raw_job,
    )


def _query_from_payload(search_result: dict[str, Any], job_count: int) -> JobStreetListQuery:
    search_params = search_result.get("searchParams")
    if not isinstance(search_params, dict):
        return JobStreetListQuery(page_size=job_count or 1)
    return JobStreetListQuery(
        keywords=_optional_str(search_params.get("keywords")),
        page=_optional_int(search_params.get("page"), 1),
        page_size=_optional_int(search_params.get("pageSize"), job_count or 1),
        date_range=_optional_int(search_params.get("daterange"), 7),
    )


def _optional_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return fallback


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
