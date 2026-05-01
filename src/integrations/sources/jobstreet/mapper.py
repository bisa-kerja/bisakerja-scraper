from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.sources.jobstreet.list import JOBSTREET_SOURCE_PLATFORM, RawSourceJob
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


def map_jobstreet_job(raw_job: RawSourceJob, *, scraped_at: datetime | None = None):
    scraped_at = scraped_at or utc_now()
    raw = raw_job.raw_payload
    list_payload = raw.get("list") if isinstance(raw.get("list"), dict) else raw
    detail_payload = raw.get("detail") if isinstance(raw.get("detail"), dict) else None
    detail_job = _dict_value(detail_payload.get("job") if detail_payload else None)
    company_profile = _dict_value(detail_payload.get("companyProfile") if detail_payload else None)
    company_overview = _dict_value(company_profile.get("overview"))
    listing_date = _dict_value(list_payload.get("listingDate"))
    listed_at = _dict_value(detail_job.get("listedAt"))
    branding = _dict_value(list_payload.get("branding"))
    work_arrangements = _dict_value(list_payload.get("workArrangements"))
    detail_work_arrangements = _dict_value(
        detail_payload.get("workArrangements") if detail_payload else None
    )

    posted_at = parse_datetime(listed_at.get("dateTimeUtc")) or parse_datetime(
        listing_date.get("dateTimeUtc")
    )

    payload = {
        "source": {
            "platform": JOBSTREET_SOURCE_PLATFORM,
            "external_job_id": raw_job.external_id,
            "source_url": raw_job.source_url,
            "scraped_at": scraped_at,
            "source_updated_at": posted_at,
        },
        "title": detail_job.get("title") or list_payload.get("title"),
        "company": {
            "name": company_profile.get("name")
            or detail_job.get("advertiser", {}).get("name")
            or list_payload.get("companyName")
            or "Unknown company",
            "logo_url": _jobstreet_logo(branding, detail_job, company_profile),
            "industry": company_overview.get("industry"),
            "source_company_id": company_profile.get("id"),
            "source_slug": company_profile.get("companyNameSlug"),
        },
        "location": {
            "display": detail_job.get("location", {}).get("label")
            if isinstance(detail_job.get("location"), dict)
            else _location_display(list_payload),
        },
        "salary": salary_or_none(
            display=_salary_label(list_payload, detail_job),
        ),
        "employment_types": _employment_types(list_payload, detail_job),
        "work_type": map_work_type(
            first_text(
                [
                    _first_arrangement_type(detail_work_arrangements),
                    work_arrangements.get("displayText"),
                ]
            )
        ),
        "description": html_to_text(detail_job.get("content")) or list_payload.get("teaser"),
        "requirements": first_text(detail_job.get("products", {}).get("bullets") or [])
        or first_text(list_payload.get("bulletPoints") or []),
        "skills": [],
        "posted_at": posted_at,
        "last_seen_at": scraped_at,
        "status": map_status(detail_job.get("status")) if detail_job else map_status("active"),
        "presentation": {
            "posted_label": listed_at.get("label") or listing_date.get("label"),
            "salary_label": _salary_label(list_payload, detail_job),
            "badges": unique_texts(
                [
                    tag.get("type") or tag.get("label")
                    for tag in list_payload.get("tags", [])
                    if isinstance(tag, dict)
                ]
            ),
        },
    }
    return validate_mapped_job(
        payload,
        source_platform=JOBSTREET_SOURCE_PLATFORM,
        external_id=raw_job.external_id,
        field_provenance={
            "title": "detail.job.title or list.title",
            "company.name": "detail.companyProfile.name or list.companyName",
            "location.display": "detail.job.location.label or list.locations[].label",
            "salary": "detail.job.salary.label or list.salaryLabel",
            "description": "detail.job.content or list.teaser",
            "requirements": "detail.job.products.bullets or list.bulletPoints",
        },
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _location_display(payload: dict[str, Any]) -> str | None:
    locations = payload.get("locations")
    if not isinstance(locations, list):
        return None
    return first_text(
        [location.get("label") for location in locations if isinstance(location, dict)]
    )


def _jobstreet_logo(
    branding: dict[str, Any],
    detail_job: dict[str, Any],
    company_profile: dict[str, Any],
) -> str | None:
    logo = branding.get("serpLogoUrl")
    if isinstance(logo, str) and logo:
        return logo
    products = _dict_value(detail_job.get("products"))
    product_branding = _dict_value(products.get("branding"))
    logo_payload = _dict_value(product_branding.get("logo"))
    logo = logo_payload.get("url")
    if isinstance(logo, str) and logo:
        return logo
    company_branding = _dict_value(company_profile.get("branding"))
    logo = company_branding.get("logo")
    return logo if isinstance(logo, str) and logo else None


def _salary_label(list_payload: dict[str, Any], detail_job: dict[str, Any]) -> str | None:
    salary = _dict_value(detail_job.get("salary"))
    return first_text([salary.get("label"), list_payload.get("salaryLabel")])


def _employment_types(list_payload: dict[str, Any], detail_job: dict[str, Any]):
    values: list[Any] = []
    detail_work_types = detail_job.get("workTypes")
    if isinstance(detail_work_types, dict):
        values.append(detail_work_types.get("label"))
    values.extend(list_payload.get("workTypes") or [])
    mapped = [map_employment_type(value) for value in values if value]
    return mapped or [map_employment_type(None)]


def _first_arrangement_type(work_arrangements: dict[str, Any]) -> str | None:
    arrangements = work_arrangements.get("arrangements")
    if not isinstance(arrangements, list):
        return None
    for arrangement in arrangements:
        if isinstance(arrangement, dict):
            value = arrangement.get("type") or arrangement.get("label")
            if isinstance(value, str) and value:
                return value
    return None
