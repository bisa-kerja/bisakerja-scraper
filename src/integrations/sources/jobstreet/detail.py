from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.errors import FetchError, ParseError
from integrations.sources.jobstreet.list import (
    JOBSTREET_GRAPHQL_PATH,
    JOBSTREET_SOURCE_PLATFORM,
    RawSourceJob,
    build_jobstreet_source_url,
)
from shared.http import JsonHttpClient

JOBSTREET_DETAIL_OPERATION = "jobDetails"

JOBSTREET_DETAIL_QUERY = """query jobDetails(
  $jobId: ID!
  $jobDetailsViewedCorrelationId: String!
  $sessionId: String!
  $zone: Zone!
  $locale: Locale!
  $languageCode: LanguageCodeIso!
  $countryCode: CountryCodeIso2!
  $timezone: Timezone!
  $visitorId: UUID!
  $isAuthenticated: Boolean!
) {
  jobDetails(
    id: $jobId
    tracking: {
      channel: "WEB"
      jobDetailsViewedCorrelationId: $jobDetailsViewedCorrelationId
      sessionId: $sessionId
    }
  ) {
    job {
      id
      title
      abstract
      content(platform: WEB)
      status
      isExpired
      listedAt {
        label(context: JOB_POSTED, length: SHORT, timezone: $timezone, locale: $locale)
        dateTimeUtc
        __typename
      }
      expiresAt {
        dateTimeUtc
        __typename
      }
      salary {
        currencyLabel(zone: $zone)
        label
        __typename
      }
      shareLink(platform: WEB, zone: $zone, locale: $locale)
      workTypes {
        label(locale: $locale)
        __typename
      }
      advertiser {
        id
        name(locale: $locale)
        isVerified
        __typename
      }
      location {
        label(locale: $locale, type: LONG)
        __typename
      }
      classifications {
        label(languageCode: $languageCode)
        __typename
      }
      products {
        branding {
          logo {
            url
            __typename
          }
          __typename
        }
        bullets
        __typename
      }
      __typename
    }
    companyProfile(zone: $zone) {
      id
      name
      companyNameSlug
      branding {
        logo
        __typename
      }
      overview {
        description {
          paragraphs
          __typename
        }
        industry
        website {
          url
          __typename
        }
        __typename
      }
      __typename
    }
    workArrangements(visitorId: $visitorId, channel: "JDV", platform: WEB) {
      arrangements {
        type
        label(locale: $locale)
        __typename
      }
      label(locale: $locale)
      __typename
    }
    insights @include(if: $isAuthenticated) {
      __typename
    }
    __typename
  }
}"""


@dataclass(frozen=True)
class JobStreetDetailQuery:
    job_id: str
    zone: str = "asia-4"
    locale: str = "id-ID"
    language_code: str = "id"
    country_code: str = "ID"
    timezone: str = "Asia/Jakarta"
    is_authenticated: bool = True
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = field(default_factory=lambda: str(uuid4()))
    visitor_id: str = field(default_factory=lambda: str(uuid4()))

    def to_variables(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "jobDetailsViewedCorrelationId": self.correlation_id,
            "sessionId": self.session_id,
            "zone": self.zone,
            "locale": self.locale,
            "languageCode": self.language_code,
            "countryCode": self.country_code,
            "timezone": self.timezone,
            "visitorId": self.visitor_id,
            "isAuthenticated": self.is_authenticated,
        }


class JobStreetDetailResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]
    html_description: str | None = None
    abstract: str | None = None


class JobStreetDetailAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_detail(
        self,
        job_id: str,
        query: JobStreetDetailQuery | None = None,
    ) -> JobStreetDetailResult:
        detail_query = query or JobStreetDetailQuery(job_id=job_id)
        request_body = build_jobstreet_detail_request_body(detail_query)
        payload = await self.http_client.request_json(
            "POST",
            JOBSTREET_GRAPHQL_PATH,
            json_body=request_body,
        )
        return parse_jobstreet_detail_payload(payload)

    async def fetch_enriched_job(self, list_job: RawSourceJob) -> RawSourceJob:
        try:
            detail = await self.fetch_detail(list_job.external_id)
            return merge_jobstreet_list_and_detail(list_job, detail)
        except FetchError as exc:
            return merge_jobstreet_list_and_detail(
                list_job,
                None,
                missing_reason=_missing_reason_from_fetch_error(exc),
                detail_attempted=True,
                failure_retryable=exc.retryable,
            )
        except ParseError as exc:
            return merge_jobstreet_list_and_detail(
                list_job,
                None,
                missing_reason=_missing_reason_from_parse_error(exc),
                detail_attempted=True,
                failure_retryable=False,
            )


def build_jobstreet_detail_request_body(query: JobStreetDetailQuery) -> dict[str, Any]:
    return {
        "operationName": JOBSTREET_DETAIL_OPERATION,
        "variables": query.to_variables(),
        "query": JOBSTREET_DETAIL_QUERY,
    }


def parse_jobstreet_detail_payload(payload: dict[str, Any]) -> JobStreetDetailResult:
    if payload.get("errors"):
        raise ParseError(
            "JobStreet detail payload contains GraphQL errors",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "JobStreet detail payload missing data object",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    detail = data.get(JOBSTREET_DETAIL_OPERATION)
    if not isinstance(detail, dict):
        raise ParseError(
            "JobStreet detail payload missing jobDetails object",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    job = detail.get("job")
    if not isinstance(job, dict):
        raise ParseError(
            "JobStreet detail payload missing job object",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    external_id = job.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise ParseError(
            "JobStreet detail job missing required id",
            source_platform=JOBSTREET_SOURCE_PLATFORM,
        )

    return JobStreetDetailResult(
        external_id=external_id,
        source_url=_detail_source_url(job, external_id),
        raw_payload=detail,
        html_description=_optional_text(job.get("content")),
        abstract=_optional_text(job.get("abstract")),
    )


def merge_jobstreet_list_and_detail(
    list_job: RawSourceJob,
    detail: JobStreetDetailResult | None,
    *,
    missing_reason: str | None = None,
    detail_attempted: bool = True,
    failure_retryable: bool | None = None,
) -> RawSourceJob:
    if detail is None:
        metadata: dict[str, Any] = {
            "coverage": "missing",
            "missingReason": missing_reason or "unavailable",
            "detailCompleteness": "partial",
            "attempted": detail_attempted,
        }
        if failure_retryable is not None:
            metadata["failureRetryable"] = failure_retryable
        return RawSourceJob(
            source_platform=list_job.source_platform,
            external_id=list_job.external_id,
            source_url=list_job.source_url,
            raw_payload={
                "list": list_job.raw_payload,
                "detail": None,
                "detailMetadata": metadata,
            },
        )

    return RawSourceJob(
        source_platform=list_job.source_platform,
        external_id=list_job.external_id,
        source_url=detail.source_url,
        raw_payload={
            "list": list_job.raw_payload,
            "detail": detail.raw_payload,
            "detailMetadata": {
                "coverage": "available",
                "source": "detail",
                "detailCompleteness": "complete",
                "attempted": True,
                "htmlFields": ["job.content"] if detail.html_description else [],
            },
        },
    )


def _detail_source_url(job: dict[str, Any], external_id: str) -> str:
    share_link = job.get("shareLink")
    if isinstance(share_link, str) and share_link:
        return share_link.split("?", maxsplit=1)[0]
    return build_jobstreet_source_url(external_id)


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _missing_reason_from_parse_error(error: ParseError) -> str:
    message = error.message.lower()
    if "auth" in message or "unauthorized" in message:
        return "auth_required"
    return "unavailable"


def _missing_reason_from_fetch_error(error: FetchError) -> str:
    status_code = error.details.get("statusCode")
    if status_code == 404:
        return "not_found"
    if status_code in {401, 403}:
        return "auth_required"
    if status_code == 429:
        return "rate_limited"
    return "unavailable"
