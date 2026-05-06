from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.glints.list import GLINTS_SOURCE_PLATFORM, RawSourceJob
from integrations.sources.mapper_utils import (
    CanonicalJobStatus,
    ExperienceLevel,
    first_text,
    map_employment_type,
    map_experience_level,
    map_status,
    map_work_type,
    parse_datetime,
    salary_or_none,
    unique_texts,
    utc_now,
    validate_mapped_job,
)


def map_glints_job(raw_job: RawSourceJob, *, scraped_at: datetime | None = None):
    scraped_at = scraped_at or utc_now()
    raw = raw_job.raw_payload
    list_payload = raw.get("list") if isinstance(raw.get("list"), dict) else raw
    detail_metadata = (
        raw.get("detailMetadata") if isinstance(raw.get("detailMetadata"), dict) else {}
    )
    company = _dict_value(list_payload.get("company"))
    industry = _dict_value(company.get("industry"))
    location = _dict_value(list_payload.get("location"))
    country = _dict_value(list_payload.get("country"))
    salary = _first_dict(list_payload.get("salaries"))
    posted_at = parse_datetime(list_payload.get("createdAt"))
    updated_at = parse_datetime(list_payload.get("updatedAt"))
    requirements_summary = _build_requirements_summary(list_payload)
    canonical_status = _status_from_list_visibility(list_payload.get("status"))

    payload = {
        "source": {
            "platform": GLINTS_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_url": raw_job.source_url,
            "external_apply_url": raw_job.source_url,
            "scraped_at": scraped_at,
            "source_updated_at": updated_at,
        },
        "title": list_payload.get("title"),
        "company": {
            "name": company.get("name") or company.get("brandName") or "Unknown company",
            "logo_url": company.get("logo"),
            "industry": industry.get("name"),
            "source_company_id": company.get("id"),
        },
        "location": {
            "display": first_text([location.get("formattedName"), country.get("name")]),
            "city": location.get("formattedName"),
            "country": country.get("name"),
        },
        "salary": salary_or_none(
            min_amount=salary.get("minAmount"),
            max_amount=salary.get("maxAmount"),
            currency=salary.get("CurrencyCode"),
            period=salary.get("salaryMode"),
        ),
        "employment_types": [map_employment_type(list_payload.get("type"))],
        "work_type": map_work_type(list_payload.get("workArrangementOption")),
        "experience_level": _experience_level_from_payload(list_payload),
        "description": None,
        "requirements": requirements_summary,
        "skills": unique_texts(
            [
                skill.get("skill", {}).get("name")
                for skill in list_payload.get("skills", [])
                if isinstance(skill, dict) and isinstance(skill.get("skill"), dict)
            ]
        ),
        "posted_at": posted_at,
        "last_seen_at": scraped_at,
        "status": canonical_status,
        "presentation": {
            "badges": ["hot"] if list_payload.get("isHot") is True else [],
            "salary_label": None,
            "posted_label": None,
            "source_labels": {
                "detailCoverage": detail_metadata.get("coverage", "unavailable"),
                "detailCompleteness": detail_metadata.get("detailCompleteness", "partial"),
                "fallbackPolicy": "list-only",
            },
        },
    }
    requirements_provenance = "unavailable"
    if requirements_summary:
        requirements_provenance = (
            "list.minYearsOfExperience/list.maxYearsOfExperience/"
            "list.hierarchicalJobCategory.name/list.skills[].skill.name"
        )
    return validate_mapped_job(
        payload,
        source_platform=GLINTS_SOURCE_PLATFORM,
        external_id=raw_job.external_id,
        field_provenance={
            "title": "list.title",
            "company.name": "list.company.name",
            "location.display": "list.location.formattedName",
            "salary": "list.salaries[0]",
            "skills": "list.skills[].skill.name",
            "description": "unavailable",
            "requirements": requirements_provenance,
        },
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _status_from_list_visibility(value: Any) -> CanonicalJobStatus:
    mapped = map_status(value)
    if mapped in {
        CanonicalJobStatus.STALE,
        CanonicalJobStatus.INACTIVE,
        CanonicalJobStatus.EXPIRED,
    }:
        return mapped
    return CanonicalJobStatus.ACTIVE


def _build_requirements_summary(raw: dict[str, Any]) -> str | None:
    parts: list[str] = []

    minimum = _as_non_negative_int(raw.get("minYearsOfExperience"))
    maximum = _as_non_negative_int(raw.get("maxYearsOfExperience"))
    if minimum is not None and maximum is not None:
        parts.append(f"Experience: {minimum}-{maximum} years.")
    elif minimum is not None:
        parts.append(f"Experience: minimum {minimum} years.")
    elif maximum is not None:
        parts.append(f"Experience: up to {maximum} years.")

    category = _dict_value(raw.get("hierarchicalJobCategory")).get("name")
    if isinstance(category, str) and category.strip():
        parts.append(f"Category: {category.strip()}.")

    skills = unique_texts(
        [
            skill.get("skill", {}).get("name")
            for skill in raw.get("skills", [])
            if isinstance(skill, dict) and isinstance(skill.get("skill"), dict)
        ]
    )
    if skills:
        parts.append(f"Skills: {', '.join(skills)}.")
    return " ".join(parts) if parts else None


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        parsed = int(value)
        return parsed if parsed >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed >= 0 else None
    return None


def _experience_level_from_payload(payload: dict[str, Any]) -> ExperienceLevel:
    for value in (
        payload.get("experienceLevel"),
        payload.get("seniorityLevel"),
        payload.get("careerLevel"),
    ):
        mapped = map_experience_level(value)
        if mapped is not ExperienceLevel.UNKNOWN:
            return mapped

    minimum = _as_non_negative_int(payload.get("minYearsOfExperience"))
    maximum = _as_non_negative_int(payload.get("maxYearsOfExperience"))
    if maximum is not None:
        if maximum >= 5:
            return ExperienceLevel.SENIOR
        if maximum >= 3:
            return ExperienceLevel.MID_LEVEL
        if maximum >= 1:
            return ExperienceLevel.JUNIOR
    if minimum is not None:
        if minimum >= 5:
            return ExperienceLevel.SENIOR
        if minimum >= 3:
            return ExperienceLevel.MID_LEVEL
        if minimum >= 1:
            return ExperienceLevel.JUNIOR
    return ExperienceLevel.ENTRY_LEVEL
