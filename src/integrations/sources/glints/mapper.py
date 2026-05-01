from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.glints.list import GLINTS_SOURCE_PLATFORM, RawSourceJob
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

    payload = {
        "source": {
            "platform": GLINTS_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_url": raw_job.source_url,
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
        "skills": unique_texts(
            [
                skill.get("skill", {}).get("name")
                for skill in raw.get("skills", [])
                if isinstance(skill, dict) and isinstance(skill.get("skill"), dict)
            ]
        ),
        "posted_at": posted_at,
        "last_seen_at": scraped_at,
        "status": map_status(raw.get("status")),
        "presentation": {
            "badges": ["hot"] if raw.get("isHot") is True else [],
            "salary_label": None,
            "posted_label": None,
            "source_labels": {"detailCoverage": "unavailable"},
        },
    }
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
            "requirements": "unavailable",
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
