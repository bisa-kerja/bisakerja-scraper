from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from core.errors import NormalizeError
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CanonicalJobStatus,
    EmploymentType,
    SalaryPeriod,
    SalarySchema,
    WorkType,
)
from shared.text import clean_text


class SourceMapperResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: CanonicalJobSchema
    field_provenance: dict[str, str]


def validate_mapped_job(
    payload: dict[str, Any],
    *,
    source_platform: str,
    external_id: str | None,
    field_provenance: dict[str, str],
) -> SourceMapperResult:
    try:
        job = CanonicalJobSchema.model_validate(payload)
    except ValidationError as exc:
        raise NormalizeError(
            "mapped job failed canonical validation",
            source_platform=source_platform,
            external_id=external_id,
            details={"error": exc.__class__.__name__},
            retryable=False,
        ) from exc
    return SourceMapperResult(job=job, field_provenance=field_provenance)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_text(value)
    return None


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def first_text(values: list[Any]) -> str | None:
    for value in values:
        text = optional_str(value)
        if text:
            return text
    return None


def unique_texts(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = optional_str(value)
        if text and text not in result:
            result.append(text)
    return result


def map_employment_type(value: Any) -> EmploymentType:
    text = optional_str(value)
    if not text:
        return EmploymentType.UNKNOWN
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    normalized = normalized.replace("fulltime", "full_time").replace("parttime", "part_time")
    if normalized in {"full_time", "full"}:
        return EmploymentType.FULL_TIME
    if normalized in {"part_time", "part"}:
        return EmploymentType.PART_TIME
    if "contract" in normalized:
        return EmploymentType.CONTRACT
    if "intern" in normalized:
        return EmploymentType.INTERNSHIP
    if "freelance" in normalized:
        return EmploymentType.FREELANCE
    return EmploymentType.UNKNOWN


def map_work_type(value: Any) -> WorkType:
    text = optional_str(value)
    if not text:
        return WorkType.UNKNOWN
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if "remote" in normalized or "work_from_home" in normalized or normalized == "wfh":
        return WorkType.REMOTE
    if "hybrid" in normalized:
        return WorkType.HYBRID
    if "onsite" in normalized or "on_site" in normalized or "kantor" in normalized:
        return WorkType.ONSITE
    return WorkType.UNKNOWN


def map_status(value: Any) -> CanonicalJobStatus:
    text = optional_str(value)
    if not text:
        return CanonicalJobStatus.UNKNOWN
    normalized = text.lower()
    if normalized in {"active", "open"}:
        return CanonicalJobStatus.ACTIVE
    if normalized in {"inactive", "closed"}:
        return CanonicalJobStatus.INACTIVE
    if normalized in {"expired"}:
        return CanonicalJobStatus.EXPIRED
    return CanonicalJobStatus.UNKNOWN


def salary_or_none(
    *,
    min_amount: Any = None,
    max_amount: Any = None,
    currency: Any = None,
    period: Any = None,
    display: Any = None,
) -> dict[str, Any] | None:
    min_value = optional_int(min_amount)
    max_value = optional_int(max_amount)
    currency_value = optional_str(currency)
    period_value = map_salary_period(period)
    display_value = optional_str(display)
    if not any([min_value is not None, max_value is not None, currency_value, display_value]):
        return None
    salary = SalarySchema(
        min_amount=min_value,
        max_amount=max_value,
        currency=currency_value,
        period=period_value,
        display=display_value,
    )
    return salary.model_dump()


def map_salary_period(value: Any) -> SalaryPeriod | None:
    text = optional_str(value)
    if not text:
        return None
    normalized = text.lower()
    if normalized in {"month", "monthly"}:
        return SalaryPeriod.MONTHLY
    if normalized in {"year", "yearly"}:
        return SalaryPeriod.YEARLY
    if normalized in {"day", "daily"}:
        return SalaryPeriod.DAILY
    if normalized in {"hour", "hourly"}:
        return SalaryPeriod.HOURLY
    return SalaryPeriod.UNKNOWN
