from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.kitalulus.list import (
    KITALULUS_SOURCE_PLATFORM,
    RawSourceJob,
    parse_kitalulus_epoch_datetime,
)
from integrations.sources.mapper_utils import (
    first_text,
    map_employment_type,
    map_experience_level,
    map_work_type,
    salary_or_none,
    unique_texts,
    utc_now,
    validate_mapped_job,
)
from modules.jobs.schemas import CanonicalJobStatus, EmploymentType, ExperienceLevel, WorkType
from shared.text import html_to_text


def map_kitalulus_job(raw_job: RawSourceJob, *, scraped_at: datetime | None = None):
    scraped_at = scraped_at or utc_now()
    raw = raw_job.raw_payload
    list_payload = raw.get("list") if isinstance(raw.get("list"), dict) else raw
    detail_payload = raw.get("detail") if isinstance(raw.get("detail"), dict) else list_payload
    detail_metadata = (
        raw.get("detailMetadata") if isinstance(raw.get("detailMetadata"), dict) else {}
    )
    company = _dict_value(detail_payload.get("company")) or _dict_value(list_payload.get("company"))
    company_industry = _dict_value(company.get("companyIndustry"))
    province = _dict_value(detail_payload.get("province")) or _dict_value(
        list_payload.get("province")
    )
    city = _dict_value(detail_payload.get("city")) or _dict_value(list_payload.get("city"))
    updated_at = parse_kitalulus_epoch_datetime(detail_payload.get("updatedAt"))
    salary_min = _zero_as_none(detail_payload.get("salaryLowerBound"))
    salary_max = _zero_as_none(detail_payload.get("salaryUpperBound"))
    salary = (
        salary_or_none(
            min_amount=salary_min,
            max_amount=salary_max,
            currency="IDR",
            period="monthly",
        )
        if salary_min is not None or salary_max is not None
        else None
    )
    formatted_description = detail_payload.get("formattedDescription")
    description = html_to_text(formatted_description) if formatted_description else None
    if not description:
        description = html_to_text(detail_payload.get("description"))

    payload = {
        "source": {
            "platform": KITALULUS_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_slug": detail_payload.get("slug") or list_payload.get("slug"),
            "source_url": raw_job.source_url,
            "external_apply_url": raw_job.source_url,
            "scraped_at": scraped_at,
            "source_updated_at": updated_at,
        },
        "title": detail_payload.get("positionName") or list_payload.get("positionName"),
        "company": {
            "name": company.get("name") or "Unknown company",
            "logo_url": _safe_logo_url(company.get("logoUrl")),
            "industry": company_industry.get("name"),
            "source_company_id": first_text([company.get("id"), company.get("code")]),
            "source_slug": company.get("slug") or company.get("code"),
        },
        "location": {
            "display": first_text(
                [
                    ", ".join(
                        part
                        for part in [city.get("name"), province.get("name"), "Indonesia"]
                        if isinstance(part, str) and part
                    )
                ]
            ),
            "city": city.get("name"),
            "region": province.get("name"),
            "country": "Indonesia",
            "is_remote": _is_remote(detail_payload),
        },
        "salary": salary,
        "employment_types": [_kitalulus_employment_type(detail_payload)],
        "work_type": _kitalulus_work_type(detail_payload),
        "experience_level": _kitalulus_experience_level(detail_payload),
        "description": description,
        "requirements": description,
        "skills": unique_texts(_skill_tags(detail_payload)),
        "posted_at": updated_at,
        "last_seen_at": scraped_at,
        "status": _kitalulus_status(detail_payload),
        "presentation": {
            "posted_label": detail_payload.get("updatedAtStr") or list_payload.get("updatedAtStr"),
            "salary_label": None,
            "badges": ["highlighted"] if detail_payload.get("isHighlighted") is True else [],
            "source_labels": {
                "detailCoverage": detail_metadata.get("coverage", "list"),
                "detailCompleteness": detail_metadata.get("detailCompleteness", "partial"),
                "jobRole": _dict_value(detail_payload.get("jobRole")).get("displayName"),
                "education": detail_payload.get("educationLevelStr"),
                "minExperience": detail_payload.get("minExperienceStr")
                or detail_payload.get("minExperience"),
            },
        },
    }
    return validate_mapped_job(
        payload,
        source_platform=KITALULUS_SOURCE_PLATFORM,
        external_id=raw_job.external_id,
        field_provenance={
            "title": "detail.positionName or list.positionName",
            "company.name": "detail.company.name or list.company.name",
            "location.display": "detail.city/detail.province",
            "salary": "detail.salaryLowerBound/detail.salaryUpperBound",
            "description": "detail.formattedDescription or detail.description",
            "requirements": "detail.formattedDescription or detail.description",
            "skills": "detail.skillTags",
        },
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _zero_as_none(value: Any) -> Any:
    if value == 0:
        return None
    return value


def _safe_logo_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.split("?", maxsplit=1)[0]


def _skill_tags(payload: dict[str, Any]) -> list[Any]:
    value = payload.get("skillTags")
    return value if isinstance(value, list) else []


def _is_remote(payload: dict[str, Any]) -> bool | None:
    text = payload.get("locationSiteStr")
    if not isinstance(text, str):
        return None
    lowered = text.casefold()
    if "wfh" in lowered or "rumah" in lowered:
        return True
    if "wfo" in lowered or "kantor" in lowered:
        return False
    return None


def _kitalulus_work_type(payload: dict[str, Any]) -> WorkType:
    mapped = map_work_type(payload.get("locationSiteStr"))
    if mapped is not WorkType.UNKNOWN:
        return mapped
    return WorkType.ONSITE


def _kitalulus_employment_type(payload: dict[str, Any]) -> EmploymentType:
    google_type = payload.get("googleType")
    if google_type == "CONTRACTOR":
        return EmploymentType.CONTRACT
    mapped = map_employment_type(payload.get("typeStr"))
    if mapped is not EmploymentType.UNKNOWN:
        return mapped
    if payload.get("typeStr") == "Magang":
        return EmploymentType.INTERNSHIP
    if payload.get("typeStr") == "Kontrak":
        return EmploymentType.CONTRACT
    return EmploymentType.FULL_TIME


def _kitalulus_experience_level(payload: dict[str, Any]) -> ExperienceLevel:
    min_experience = payload.get("minExperience")
    if min_experience in {None, 0}:
        return ExperienceLevel.ENTRY_LEVEL
    mapped = map_experience_level(payload.get("minExperienceStr"))
    if mapped is not ExperienceLevel.UNKNOWN:
        return mapped
    if isinstance(min_experience, int):
        if min_experience <= 1:
            return ExperienceLevel.JUNIOR
        if min_experience <= 3:
            return ExperienceLevel.MID_LEVEL
        return ExperienceLevel.SENIOR
    return ExperienceLevel.UNKNOWN


def _kitalulus_status(payload: dict[str, Any]) -> CanonicalJobStatus:
    if payload.get("isClosed") is True:
        return CanonicalJobStatus.INACTIVE
    if payload.get("isPublished") is False:
        return CanonicalJobStatus.INACTIVE
    return CanonicalJobStatus.ACTIVE
