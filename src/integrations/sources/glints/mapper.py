from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.glints.list import GLINTS_SOURCE_PLATFORM, RawSourceJob
from integrations.sources.mapper_utils import (
    CanonicalJobStatus,
    first_text,
    map_employment_type,
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
    company = _dict_value(raw.get("company"))
    industry = _dict_value(company.get("industry"))
    location = _dict_value(raw.get("location"))
    country = _dict_value(raw.get("country"))
    salary = _first_dict(raw.get("salaries"))
    posted_at = parse_datetime(raw.get("createdAt"))
    updated_at = parse_datetime(raw.get("updatedAt"))
    requirements_summary = _build_requirements_summary(raw)
    canonical_status = _status_from_list_visibility(raw.get("status"))

    payload = {
        "source": {
            "platform": GLINTS_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_url": raw_job.source_url,
            "external_apply_url": raw_job.source_url,
            "scraped_at": scraped_at,
            "source_updated_at": updated_at,
        },
        "title": raw.get("title"),
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
        "employment_types": [map_employment_type(raw.get("type"))],
        "work_type": map_work_type(raw.get("workArrangementOption")),
        "description": None,
        "requirements": requirements_summary,
        "skills": unique_texts(
            [
                skill.get("skill", {}).get("name")
                for skill in raw.get("skills", [])
                if isinstance(skill, dict) and isinstance(skill.get("skill"), dict)
            ]
        ),
        "posted_at": posted_at,
        "last_seen_at": scraped_at,
        "status": canonical_status,
        "presentation": {
            "badges": ["hot"] if raw.get("isHot") is True else [],
            "salary_label": None,
            "posted_label": None,
            "source_labels": {
                "detailCoverage": "unavailable",
                "detailCompleteness": "partial",
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
        parts.append(f"Skills: {', '.join(skills[:5])}.")

    if not parts:
        return None
    return " ".join(parts)


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None
