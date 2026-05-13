from __future__ import annotations

import re
from typing import Any

from modules.jobs.schemas import EmploymentType, ExperienceLevel, WorkType
from shared.text import clean_text

_PLACEHOLDER_VALUES = {
    "-",
    "--",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "tidak tersedia",
    "not available",
}
_YEARS_RANGE_PATTERN = re.compile(r"(\d+)\s*[-to]+\s*(\d+)\s*(tahun|years?)?", re.IGNORECASE)
_YEARS_PLUS_PATTERN = re.compile(r"(\d+)\s*\+\s*(tahun|years?)", re.IGNORECASE)


def as_clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = clean_text(value)
    return text or None


def is_placeholder_text(value: str | None) -> bool:
    if value is None:
        return True
    lowered = value.strip().lower()
    return lowered in _PLACEHOLDER_VALUES


def clean_description(value: Any) -> str | None:
    text = as_clean_text(value)
    if text is None or is_placeholder_text(text):
        return None
    return text


def normalize_city_name(value: Any) -> str | None:
    return as_clean_text(value)


def infer_city_from_display(display: Any) -> str | None:
    text = as_clean_text(display)
    if text is None:
        return None
    first_part = text.split(",", maxsplit=1)[0].strip()
    return normalize_city_name(first_part)


def infer_region_from_display(display: Any) -> str | None:
    text = as_clean_text(display)
    if text is None:
        return None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) >= 2:
        return as_clean_text(parts[1])
    return None


def normalize_location_fields(
    *,
    city: Any,
    region: Any,
    country: Any,
    display: Any,
    is_remote: Any,
) -> dict[str, str | None]:
    city_value = normalize_city_name(city) or infer_city_from_display(display)
    region_value = as_clean_text(region) or infer_region_from_display(display)
    country_value = as_clean_text(country)
    is_remote_true = is_remote is True
    if is_remote_true and (country_value or "").lower() == "indonesia":
        city_value = city_value or "Remote"
        region_value = region_value or "Indonesia"

    display_value = as_clean_text(display)
    if display_value is None:
        parts = [part for part in [city_value, region_value, country_value] if part]
        display_value = ", ".join(parts) if parts else None

    return {
        "city": city_value,
        "region": region_value,
        "country": country_value,
        "display": display_value,
    }


def default_work_type(value: Any) -> WorkType:
    if isinstance(value, WorkType) and value is not WorkType.UNKNOWN:
        return value
    return WorkType.ONSITE


def default_employment_types(values: Any) -> list[EmploymentType]:
    if isinstance(values, list):
        normalized = [
            item
            for item in values
            if isinstance(item, EmploymentType) and item is not EmploymentType.UNKNOWN
        ]
        if normalized:
            return normalized
    return [EmploymentType.FULL_TIME]


def infer_experience_level(
    *,
    explicit: Any,
    title: Any,
    description: Any,
    requirements: Any,
) -> ExperienceLevel:
    if isinstance(explicit, ExperienceLevel) and explicit is not ExperienceLevel.UNKNOWN:
        return explicit

    text = " ".join(
        value
        for value in (
            as_clean_text(title),
            as_clean_text(description),
            as_clean_text(requirements),
        )
        if value
    ).lower()

    if any(keyword in text for keyword in ("lead", "head", "principal", "manager", "owner role")):
        return ExperienceLevel.LEAD
    if "senior" in text:
        return ExperienceLevel.SENIOR
    if any(keyword in text for keyword in ("mid level", "mid-level", "intermediate")):
        return ExperienceLevel.MID_LEVEL
    if "junior" in text:
        return ExperienceLevel.JUNIOR
    if any(
        keyword in text
        for keyword in ("fresh graduate", "fresh grad", "intern", "internship", "no experience")
    ):
        return ExperienceLevel.ENTRY_LEVEL

    year_min, year_max = _years_evidence(text)
    if year_min is not None and year_max is not None and year_min >= 3 and year_max <= 5:
        return ExperienceLevel.MID_LEVEL
    if year_max is not None and year_max >= 5:
        return ExperienceLevel.SENIOR
    if year_min is not None and year_min >= 5:
        return ExperienceLevel.SENIOR
    if year_max is not None and year_max >= 3:
        return ExperienceLevel.MID_LEVEL
    if year_min is not None and year_min >= 3:
        return ExperienceLevel.MID_LEVEL
    if year_max is not None and year_max >= 1:
        return ExperienceLevel.JUNIOR
    if year_min is not None and year_min >= 1:
        return ExperienceLevel.JUNIOR
    return ExperienceLevel.ENTRY_LEVEL


def build_source_limited_summary(
    *,
    title: Any,
    company: Any,
    location: Any,
    source_platform: Any,
    output_language: str = "indonesian",
) -> str:
    language = (output_language or "indonesian").strip().casefold()
    if language == "english":
        title_value = as_clean_text(title) or "Unknown position"
        company_value = as_clean_text(company) or "unknown company"
        location_value = as_clean_text(location) or "location unavailable"
        source_value = as_clean_text(source_platform) or "source"
        return (
            f"{title_value} at {company_value} ({location_value}). "
            f"This summary is based on {source_value} listing-level data; "
            "full details are unavailable."
        )

    title_value = as_clean_text(title) or "Posisi tidak diketahui"
    company_value = as_clean_text(company) or "perusahaan tidak diketahui"
    location_value = as_clean_text(location) or "lokasi tidak tersedia"
    source_value = as_clean_text(source_platform) or "sumber"
    return (
        f"{title_value} di {company_value} ({location_value}). "
        f"Ringkasan ini dari data {source_value} level listing; detail penuh tidak tersedia."
    )


def _years_evidence(text: str) -> tuple[int | None, int | None]:
    year_min: int | None = None
    year_max: int | None = None
    for match in _YEARS_RANGE_PATTERN.finditer(text):
        low = int(match.group(1))
        high = int(match.group(2))
        if year_min is None or low < year_min:
            year_min = low
        if year_max is None or high > year_max:
            year_max = high
    for match in _YEARS_PLUS_PATTERN.finditer(text):
        low = int(match.group(1))
        if year_min is None or low < year_min:
            year_min = low
        if year_max is None or low > year_max:
            year_max = low
    return year_min, year_max
