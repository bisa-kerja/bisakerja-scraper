from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ParseError
from shared.http import HttpClientConfig, JsonHttpClient, SourceHttpClient

GLINTS_SOURCE_PLATFORM = "glints"
GLINTS_GRAPHQL_PATH = "/api/v2-alc/graphql"
GLINTS_GRAPHQL_OPERATION = "searchJobsV3"
GLINTS_PUBLIC_JOB_BASE_URL = "https://glints.com/id/opportunities/jobs"
GLINTS_DEFAULT_HEADERS = {
    "content-type": "application/json",
    "origin": "https://glints.com",
    "referer": "https://glints.com/",
    "x-glints-country-code": "ID",
}

GLINTS_SEARCH_JOBS_QUERY = """query searchJobsV3($data: JobSearchConditionInput!) {
  searchJobsV3(data: $data) {
    jobsInPage {
      id
      title
      workArrangementOption
      status
      createdAt
      updatedAt
      shouldShowSalary
      type
      company {
        id
        name
        brandName
        logo
        status
        industry {
          id
          name
          __typename
        }
        __typename
      }
      country {
        code
        name
        __typename
      }
      salaries {
        id
        salaryType
        salaryMode
        maxAmount
        minAmount
        CurrencyCode
        __typename
      }
      location {
        id
        name
        administrativeLevelName
        formattedName
        level
        slug
        parents {
          id
          name
          administrativeLevelName
          formattedName
          level
          slug
          CountryCode: countryCode
          parents {
            level
            formattedName
            slug
            __typename
          }
          __typename
        }
        __typename
      }
      minYearsOfExperience
      maxYearsOfExperience
      source
      jobSource
      hierarchicalJobCategory {
        id
        level
        name
        parents {
          id
          level
          name
          __typename
        }
        __typename
      }
      skills {
        skill {
          id
          name
          __typename
        }
        mustHave
        __typename
      }
      __typename
    }
    hasMore
    __typename
  }
}"""


@dataclass(frozen=True)
class GlintsListQuery:
    page: int = 1
    page_size: int = 30
    search_term: str | None = None
    country_code: str = "ID"
    sort_by: str = "LATEST"
    include_external_jobs: bool = True

    def to_variables_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "CountryCode": self.country_code,
            "sortBy": self.sort_by,
            "includeExternalJobs": self.include_external_jobs,
            "pageSize": self.page_size,
            "page": self.page,
        }
        if self.search_term:
            data["SearchTerm"] = self.search_term
        return data


class RawSourceJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_platform: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class GlintsPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    has_more: bool


class GlintsListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pagination: GlintsPagination
    raw_jobs: list[RawSourceJob]
    request_body: dict[str, Any]


class GlintsListAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_page(self, query: GlintsListQuery | None = None) -> GlintsListResult:
        query = query or GlintsListQuery()
        request_body = build_glints_list_request_body(query)
        payload = await self.http_client.request_json(
            "POST",
            GLINTS_GRAPHQL_PATH,
            params={"op": GLINTS_GRAPHQL_OPERATION},
            json_body=request_body,
        )
        return parse_glints_list_payload(payload, query=query, request_body=request_body)


def build_glints_http_client(
    *,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    max_response_bytes: int,
) -> SourceHttpClient:
    return SourceHttpClient(
        HttpClientConfig(
            source_platform=GLINTS_SOURCE_PLATFORM,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_response_bytes=max_response_bytes,
            default_headers=GLINTS_DEFAULT_HEADERS,
        )
    )


def build_glints_list_request_body(query: GlintsListQuery) -> dict[str, Any]:
    return {
        "operationName": GLINTS_GRAPHQL_OPERATION,
        "variables": {"data": query.to_variables_data()},
        "query": GLINTS_SEARCH_JOBS_QUERY,
    }


def parse_glints_list_payload(
    payload: dict[str, Any],
    *,
    query: GlintsListQuery | None = None,
    request_body: dict[str, Any] | None = None,
) -> GlintsListResult:
    if payload.get("errors"):
        raise ParseError(
            "Glints list payload contains GraphQL errors",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "Glints list payload missing data object",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    search_result = data.get(GLINTS_GRAPHQL_OPERATION)
    if not isinstance(search_result, dict):
        raise ParseError(
            "Glints list payload missing searchJobsV3 object",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    jobs = search_result.get("jobsInPage")
    if not isinstance(jobs, list):
        raise ParseError(
            "Glints list payload missing jobsInPage list",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    has_more = search_result.get("hasMore")
    if not isinstance(has_more, bool):
        raise ParseError(
            "Glints list payload missing hasMore boolean",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    query = query or GlintsListQuery(page_size=len(jobs) or 1)
    request_body = request_body or build_glints_list_request_body(query)
    pagination = GlintsPagination(
        page=query.page,
        page_size=query.page_size,
        has_more=has_more,
    )
    raw_jobs = [_parse_raw_job(raw_job) for raw_job in jobs]
    return GlintsListResult(
        pagination=pagination,
        raw_jobs=raw_jobs,
        request_body=request_body,
    )


def build_glints_source_url(job_id: str) -> str:
    return f"{GLINTS_PUBLIC_JOB_BASE_URL}/{job_id}"


def _parse_raw_job(raw_job: Any) -> RawSourceJob:
    if not isinstance(raw_job, dict):
        raise ParseError(
            "Glints list job must be an object",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    external_id = raw_job.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise ParseError(
            "Glints list job missing required id",
            source_platform=GLINTS_SOURCE_PLATFORM,
        )

    return RawSourceJob(
        source_platform=GLINTS_SOURCE_PLATFORM,
        external_id=external_id,
        source_url=build_glints_source_url(external_id),
        raw_payload=raw_job,
    )
