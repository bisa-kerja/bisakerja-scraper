from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import FetchError, ParseError
from integrations.sources.kitalulus.list import (
    KITALULUS_GRAPHQL_PATH,
    KITALULUS_SOURCE_PLATFORM,
    RawSourceJob,
    build_kitalulus_source_url,
)
from shared.http import JsonHttpClient

KITALULUS_DETAIL_OPERATION = "VacancyBySlug"
KITALULUS_DETAIL_QUERY = """query VacancyBySlug($slug: String) {
  vacancyBySlug(slug: $slug) {
    id
    slug
    code
    positionName
    isHighlighted
    educationLevelStr
    salaryLowerBound
    salaryUpperBound
    updatedAt
    updatedAtStr
    genderStr
    maxAge
    maxAgeStr
    minExperience
    minExperienceStr
    typeStr
    locationSiteStr
    description
    formattedDescription
    workingDayStartStr
    workingDayEndStr
    workingHourStartStr
    workingHourEndStr
    skillTags
    closeDate
    isClosed
    isPublished
    validThrough
    googleType
    googleEducationLevel
    benefits { id copy }
    company {
      id
      slug
      name
      code
      description
      status
      logoUrl
      contactWeblink
      companyIndustry { id name }
    }
    province { id name }
    city { id name }
    jobRole { displayName }
  }
}"""


class KitalulusDetailResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class KitalulusDetailAdapter:
    def __init__(self, http_client: JsonHttpClient) -> None:
        self.http_client = http_client

    async def fetch_enriched_job(self, list_job: RawSourceJob) -> RawSourceJob:
        slug = _required_slug(list_job)
        try:
            payload = await self.http_client.request_json(
                "POST",
                KITALULUS_GRAPHQL_PATH,
                json_body=build_kitalulus_detail_request_body(slug),
            )
            detail = parse_kitalulus_detail_payload(payload)
        except (FetchError, ParseError) as exc:
            return RawSourceJob(
                source_platform=list_job.source_platform,
                external_id=list_job.external_id,
                source_url=list_job.source_url,
                raw_payload={
                    "list": list_job.raw_payload,
                    "detailMetadata": {
                        "coverage": "missing",
                        "detailCompleteness": "partial",
                        "attempted": True,
                        "missingReason": exc.__class__.__name__,
                        "failureRetryable": bool(getattr(exc, "retryable", False)),
                    },
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
                    "detailCompleteness": "complete",
                    "attempted": True,
                    "source": "VacancyBySlug",
                },
            },
        )


def build_kitalulus_detail_request_body(slug: str) -> dict[str, Any]:
    return {
        "operationName": KITALULUS_DETAIL_OPERATION,
        "variables": {"slug": slug},
        "query": KITALULUS_DETAIL_QUERY,
    }


def parse_kitalulus_detail_payload(payload: dict[str, Any]) -> KitalulusDetailResult:
    if payload.get("errors"):
        raise ParseError(
            "Kitalulus detail payload contains GraphQL errors",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ParseError(
            "Kitalulus detail payload missing data object",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    vacancy = data.get("vacancyBySlug")
    if not isinstance(vacancy, dict):
        raise ParseError(
            "Kitalulus detail payload missing vacancyBySlug object",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    external_id = vacancy.get("id")
    slug = vacancy.get("slug")
    if not isinstance(external_id, str) or not external_id.strip():
        raise ParseError(
            "Kitalulus detail job missing required id",
            source_platform=KITALULUS_SOURCE_PLATFORM,
        )
    if not isinstance(slug, str) or not slug.strip():
        raise ParseError(
            "Kitalulus detail job missing required slug",
            source_platform=KITALULUS_SOURCE_PLATFORM,
            external_id=external_id,
        )
    return KitalulusDetailResult(
        external_id=external_id,
        slug=slug,
        source_url=build_kitalulus_source_url(slug),
        raw_payload=vacancy,
    )


def _required_slug(list_job: RawSourceJob) -> str:
    slug = list_job.raw_payload.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        raise ParseError(
            "Kitalulus list job missing slug for detail fetch",
            source_platform=KITALULUS_SOURCE_PLATFORM,
            external_id=list_job.external_id,
        )
    return slug
