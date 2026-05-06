from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.kalibrr.build_id import KALIBRR_SOURCE_PLATFORM
from integrations.sources.kalibrr.list import RawSourceJob
from integrations.sources.mapper_utils import (
    ExperienceLevel,
    first_text,
    map_employment_type,
    map_experience_level,
    map_work_type,
    parse_datetime,
    salary_or_none,
    unique_texts,
    utc_now,
    validate_mapped_job,
)
from modules.jobs.schemas import CanonicalJobStatus, WorkType
from shared.text import html_to_text


def map_kalibrr_job(raw_job: RawSourceJob, *, scraped_at: datetime | None = None):
    scraped_at = scraped_at or utc_now()
    raw = raw_job.raw_payload
    list_payload = raw.get("list") if isinstance(raw.get("list"), dict) else raw
    detail_payload = raw.get("detail") if isinstance(raw.get("detail"), dict) else list_payload
    detail_metadata = (
        raw.get("detailMetadata") if isinstance(raw.get("detailMetadata"), dict) else {}
    )
    company = _dict_value(list_payload.get("company"))
    company_info = _dict_value(list_payload.get("companyInfo"))
    location_components = _dict_value(
        _dict_value(list_payload.get("googleLocation")).get("addressComponents")
    )
    posted_at = parse_datetime(list_payload.get("activationDate")) or parse_datetime(
        list_payload.get("createdAt")
    )

    payload = {
        "source": {
            "platform": KALIBRR_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_slug": list_payload.get("slug"),
            "source_url": raw_job.source_url,
            "external_apply_url": list_payload.get("applyRedirectUrl"),
            "scraped_at": scraped_at,
            "source_updated_at": parse_datetime(list_payload.get("activationDate")),
        },
        "title": list_payload.get("name"),
        "company": {
            "name": list_payload.get("companyName")
            or company.get("name")
            or company_info.get("name")
            or "Unknown company",
            "logo_url": company.get("logoSmall") or company_info.get("logoSmall"),
            "industry": company.get("industry") or company_info.get("industry"),
            "source_company_id": str(company.get("id")) if company.get("id") is not None else None,
            "source_slug": company.get("code") or company_info.get("code"),
        },
        "location": {
            "display": first_text(
                [
                    ", ".join(
                        part
                        for part in [
                            location_components.get("city"),
                            location_components.get("region"),
                            location_components.get("country"),
                        ]
                        if isinstance(part, str) and part
                    )
                ]
            ),
            "city": location_components.get("city"),
            "region": location_components.get("region"),
            "country": location_components.get("country"),
            "is_remote": list_payload.get("isWorkFromHome"),
        },
        "salary": salary_or_none(
            min_amount=list_payload.get("baseSalary"),
            max_amount=list_payload.get("maximumSalary"),
            currency=list_payload.get("salaryCurrency"),
            period=list_payload.get("salaryInterval"),
        ),
        "employment_types": [map_employment_type(list_payload.get("tenure"))],
        "work_type": _kalibrr_work_type(list_payload),
        "experience_level": _kalibrr_experience_level(list_payload),
        "description": html_to_text(detail_payload.get("description")),
        "requirements": html_to_text(detail_payload.get("qualifications")),
        "skills": unique_texts(
            [
                skill.get("name") or skill.get("skill")
                for skill in list_payload.get("jobSdsSkills", [])
                if isinstance(skill, dict)
            ]
        ),
        "posted_at": posted_at,
        "last_seen_at": scraped_at,
        "status": CanonicalJobStatus.ACTIVE,
        "presentation": {
            "posted_label": None,
            "salary_label": None,
            "badges": ["featured"] if list_payload.get("isFeatured") is True else [],
            "source_labels": {
                "detailCoverage": detail_metadata.get("coverage", "embedded"),
                "detailCompleteness": detail_metadata.get("detailCompleteness", "complete"),
            },
        },
    }
    return validate_mapped_job(
        payload,
        source_platform=KALIBRR_SOURCE_PLATFORM,
        external_id=raw_job.external_id,
        field_provenance={
            "title": "list.name",
            "company.name": "list.companyName or list.company.name",
            "location.display": "list.googleLocation.addressComponents",
            "salary": "list.baseSalary/list.maximumSalary",
            "description": "detail.description",
            "requirements": "detail.qualifications",
        },
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _kalibrr_work_type(payload: dict[str, Any]) -> WorkType:
    if payload.get("isWorkFromHome") is True:
        return WorkType.REMOTE
    if payload.get("isHybrid") is True:
        return WorkType.HYBRID
    return map_work_type("onsite")


def _kalibrr_experience_level(payload: dict[str, Any]) -> ExperienceLevel:
    if payload.get("isOpenToFreshGrads") is True:
        return ExperienceLevel.ENTRY_LEVEL
    mapped = map_experience_level(payload.get("experienceLevel"))
    if mapped is not ExperienceLevel.UNKNOWN:
        return mapped
    return map_experience_level(payload.get("qualifications"))
