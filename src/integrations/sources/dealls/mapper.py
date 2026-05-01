from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.dealls.list import DEALLS_SOURCE_PLATFORM, RawSourceJob
from integrations.sources.mapper_utils import (
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
from shared.text import html_to_text


def map_dealls_job(raw_job: RawSourceJob, *, scraped_at: datetime | None = None):
    scraped_at = scraped_at or utc_now()
    raw = raw_job.raw_payload
    list_payload = raw.get("list") if isinstance(raw.get("list"), dict) else raw
    detail_payload = raw.get("detail") if isinstance(raw.get("detail"), dict) else None

    company = _dict_value(list_payload.get("company"))
    city = _dict_value(list_payload.get("city"))
    country = _dict_value(list_payload.get("country"))
    salary_range = _dict_value(list_payload.get("salaryRange"))
    posted_at = parse_datetime(list_payload.get("publishedAt"))
    updated_at = parse_datetime(list_payload.get("latestUpdatedAt")) or parse_datetime(
        list_payload.get("updatedAt")
    )

    description = html_to_text(_value_from_detail(detail_payload, "description"))
    requirements = html_to_text(_value_from_detail(detail_payload, "requirements"))

    payload = {
        "source": {
            "platform": DEALLS_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_slug": list_payload.get("slug"),
            "source_url": raw_job.source_url,
            "external_apply_url": list_payload.get("externalPlatformApplyUrl"),
            "scraped_at": scraped_at,
            "source_updated_at": updated_at,
        },
        "title": list_payload.get("role"),
        "company": {
            "name": company.get("name") or "Unknown company",
            "logo_url": company.get("logoUrl"),
            "industry": company.get("sector"),
            "source_company_id": company.get("id"),
            "source_slug": company.get("slug"),
        },
        "location": {
            "display": first_text(
                [
                    ", ".join(
                        part
                        for part in [city.get("name"), country.get("name")]
                        if isinstance(part, str) and part
                    )
                ]
            ),
            "city": city.get("name"),
            "country": country.get("name"),
        },
        "salary": salary_or_none(
            min_amount=salary_range.get("start"),
            max_amount=salary_range.get("end"),
            currency="IDR" if salary_range else None,
            period="monthly" if salary_range else None,
        ),
        "employment_types": [
            map_employment_type(value) for value in list_payload.get("employmentTypes", []) if value
        ],
        "work_type": map_work_type(list_payload.get("workplaceType")),
        "description": description,
        "requirements": requirements,
        "skills": unique_texts(
            [
                skill.get("name")
                for skill in list_payload.get("skills", [])
                if isinstance(skill, dict)
            ]
        ),
        "posted_at": posted_at,
        "last_seen_at": scraped_at,
        "status": map_status(list_payload.get("status")),
        "presentation": {
            "badges": _badges(list_payload),
            "salary_label": None,
            "posted_label": None,
        },
    }
    return validate_mapped_job(
        payload,
        source_platform=DEALLS_SOURCE_PLATFORM,
        external_id=raw_job.external_id,
        field_provenance={
            "title": "list.role",
            "company.name": "list.company.name",
            "location.display": "list.city.name + list.country.name",
            "salary": "list.salaryRange",
            "description": "detail.description",
            "requirements": "detail.requirements",
        },
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value_from_detail(detail_payload: dict[str, Any] | None, field: str) -> Any:
    if detail_payload is None:
        return None
    return detail_payload.get(field)


def _badges(payload: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    if payload.get("urgentlyNeeded") is True:
        badges.append("urgent")
    if payload.get("thereAreStillFewApplicants") is True:
        badges.append("few_applicants")
    return badges
