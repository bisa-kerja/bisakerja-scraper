from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from modules.jobs.dates import parse_absolute_datetime
from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import JobRequirementStaging, JobSkillStaging, NormalizedJob

MONTHLY_PATTERN = re.compile(r"\b(month|monthly|bulan|bulanan)\b", re.IGNORECASE)
YEARLY_PATTERN = re.compile(r"\b(year|yearly|tahun|tahunan)\b", re.IGNORECASE)
MAX_JOBS_PER_BACKEND_BATCH = 100
MAX_RELATIONS_PER_BACKEND_JOB = 100


class PrismaWorkType(StrEnum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"


class PrismaEmploymentType(StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    INTERNSHIP = "INTERNSHIP"
    CONTRACT = "CONTRACT"
    FREELANCE = "FREELANCE"


class PrismaExperienceLevel(StrEnum):
    ENTRY_LEVEL = "ENTRY_LEVEL"
    JUNIOR = "JUNIOR"
    MID_LEVEL = "MID_LEVEL"
    SENIOR = "SENIOR"
    LEAD = "LEAD"


class PrismaSalaryPeriod(StrEnum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class PrismaJobListingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    HIDDEN = "HIDDEN"


class PrismaRequirementType(StrEnum):
    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    RESPONSIBILITY = "RESPONSIBILITY"
    OTHER = "OTHER"


class PrismaRequirementPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class BackendPayloadValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        external_job_id: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.external_job_id = external_job_id
        self.details = details or []


class BackendPayloadModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )


class BackendSourcePlatformPayload(BackendPayloadModel):
    slug: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower()


class BackendCompanyPayload(BackendPayloadModel):
    name: str = Field(min_length=1, max_length=180)
    source_company_id: str | None = Field(
        default=None,
        max_length=120,
        serialization_alias="sourceCompanyId",
    )
    source_slug: str | None = Field(default=None, max_length=120, serialization_alias="sourceSlug")
    logo_url: str | None = Field(default=None, max_length=2000, serialization_alias="logoUrl")
    website_url: str | None = Field(
        default=None,
        max_length=2000,
        serialization_alias="websiteUrl",
    )
    industry: str | None = Field(default=None, max_length=120)


class BackendIngestionRunPayload(BackendPayloadModel):
    source_run_id: str = Field(min_length=1, max_length=160, serialization_alias="sourceRunId")


class BackendRequirementPayload(BackendPayloadModel):
    type: PrismaRequirementType
    value: str = Field(min_length=1, max_length=2000)
    priority: PrismaRequirementPriority | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = Field(default=None, max_length=80)


class BackendSkillPayload(BackendPayloadModel):
    name: str = Field(min_length=1, max_length=120)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = Field(default=None, max_length=80)


class BackendJobListingPayload(BackendPayloadModel):
    external_job_id: str = Field(
        min_length=1,
        max_length=255,
        serialization_alias="externalJobId",
    )
    title: str = Field(min_length=1, max_length=255)
    normalized_title: str | None = Field(
        default=None,
        max_length=255,
        serialization_alias="normalizedTitle",
    )
    category: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)
    requirement_summary: str | None = Field(
        default=None,
        max_length=10_000,
        serialization_alias="requirementSummary",
    )
    work_type: PrismaWorkType | None = Field(default=None, serialization_alias="workType")
    employment_type: PrismaEmploymentType | None = Field(
        default=None,
        serialization_alias="employmentType",
    )
    experience_level: PrismaExperienceLevel | None = Field(
        default=None,
        serialization_alias="experienceLevel",
    )
    location_display: str | None = Field(
        default=None,
        max_length=255,
        serialization_alias="locationDisplay",
    )
    province: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    salary_min: int | None = Field(default=None, ge=0, serialization_alias="salaryMin")
    salary_max: int | None = Field(default=None, ge=0, serialization_alias="salaryMax")
    salary_currency: str = Field(default="IDR", min_length=3, max_length=3)
    salary_period: PrismaSalaryPeriod | None = Field(
        default=None,
        serialization_alias="salaryPeriod",
    )
    salary_display: str | None = Field(
        default=None,
        max_length=255,
        serialization_alias="salaryDisplay",
    )
    source_url: str = Field(min_length=1, max_length=2000, serialization_alias="sourceUrl")
    external_apply_url: str = Field(
        min_length=1,
        max_length=2000,
        serialization_alias="externalApplyUrl",
    )
    source_posted_at: str | None = Field(default=None, serialization_alias="sourcePostedAt")
    source_updated_at: str | None = Field(default=None, serialization_alias="sourceUpdatedAt")
    last_seen_at: str = Field(min_length=1, max_length=80, serialization_alias="lastSeenAt")
    status: PrismaJobListingStatus = PrismaJobListingStatus.ACTIVE

    @field_validator("salary_currency")
    @classmethod
    def normalize_salary_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_salary_range(self) -> BackendJobListingPayload:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salaryMin must be less than or equal to salaryMax")
        return self


class BackendJobPayload(BackendPayloadModel):
    source_platform: BackendSourcePlatformPayload = Field(serialization_alias="sourcePlatform")
    company: BackendCompanyPayload
    ingestion_run: BackendIngestionRunPayload | None = Field(
        default=None,
        serialization_alias="ingestionRun",
    )
    job_listing: BackendJobListingPayload = Field(serialization_alias="jobListing")
    requirements: list[BackendRequirementPayload] = Field(
        default_factory=list,
        max_length=MAX_RELATIONS_PER_BACKEND_JOB,
    )
    skills: list[BackendSkillPayload] = Field(
        default_factory=list,
        max_length=MAX_RELATIONS_PER_BACKEND_JOB,
    )

    @model_validator(mode="after")
    def validate_relations(self) -> BackendJobPayload:
        if not self.source_platform.slug:
            raise ValueError("sourcePlatform.slug is required")
        if not self.company.name:
            raise ValueError("company.name is required")
        return self


def build_backend_job_payload(job: NormalizedJob) -> BackendJobPayload:
    payload = job.normalized_payload if isinstance(job.normalized_payload, dict) else {}
    source = as_dict(payload.get("source"))
    company = as_dict(payload.get("company"))
    location = as_dict(payload.get("location"))
    salary = as_dict(payload.get("salary"))
    run_id = job.raw_job.scrape_run_id if job.raw_job is not None else None

    external_apply_url = (
        first_non_empty(
            [
                source.get("external_apply_url"),
                job.apply_url,
                source.get("source_url"),
                job.source_url,
            ]
        )
        or ""
    )
    source_url = first_non_empty([source.get("source_url"), job.source_url]) or ""

    employment_type = map_employment_type(payload.get("employment_types"))
    work_type = map_work_type(payload.get("work_type"))
    status = map_job_status(job.status)
    source_posted_at = iso_or_none(job.posted_at) or iso_or_none(
        parse_source_datetime(payload.get("posted_at"))
    )
    source_updated_at = iso_or_none(parse_source_datetime(source.get("source_updated_at")))
    salary_display = optional_text(salary.get("display"))
    salary_period = map_salary_period(salary.get("period"), salary_display)
    salary_currency = normalized_currency(salary.get("currency")) or "IDR"

    try:
        return BackendJobPayload(
            source_platform=BackendSourcePlatformPayload(
                slug=job.source_platform,
                name=platform_display_name(job.source_platform),
            ),
            company=BackendCompanyPayload(
                name=first_non_empty([company.get("name"), job.company_name]) or "",
                source_company_id=optional_text(company.get("source_company_id")),
                source_slug=optional_text(company.get("source_slug")),
                logo_url=optional_text(company.get("logo_url")),
                website_url=optional_text(company.get("website_url")),
                industry=optional_text(company.get("industry")),
            ),
            ingestion_run=BackendIngestionRunPayload(source_run_id=run_id) if run_id else None,
            job_listing=BackendJobListingPayload(
                external_job_id=job.external_id,
                title=job.title,
                normalized_title=optional_text(payload.get("normalized_title")),
                category=optional_text(payload.get("category")),
                description=optional_text(payload.get("description")),
                requirement_summary=optional_text(payload.get("requirements")),
                work_type=work_type,
                employment_type=employment_type,
                experience_level=map_experience_level(payload.get("experience_level")),
                location_display=optional_text(location.get("display")),
                province=optional_text(location.get("region")),
                city=optional_text(location.get("city")),
                salary_min=optional_int(salary.get("min_amount")),
                salary_max=optional_int(salary.get("max_amount")),
                salary_currency=salary_currency,
                salary_period=salary_period,
                salary_display=salary_display,
                source_url=source_url,
                external_apply_url=external_apply_url,
                source_posted_at=source_posted_at,
                source_updated_at=source_updated_at,
                last_seen_at=job.last_seen_at.isoformat(),
                status=status,
            ),
            requirements=build_requirement_payloads(job),
            skills=build_skill_payloads(job),
        )
    except ValidationError as exc:
        raise BackendPayloadValidationError(
            "sync payload failed contract validation",
            external_job_id=job.external_id,
            details=list(exc.errors()),
        ) from exc


def build_backend_jobs_body(jobs: list[NormalizedJob]) -> dict[str, Any]:
    if len(jobs) > MAX_JOBS_PER_BACKEND_BATCH:
        raise BackendPayloadValidationError(
            "sync payload exceeds backend batch limit",
            details=[
                {
                    "loc": ["jobs"],
                    "msg": f"maximum {MAX_JOBS_PER_BACKEND_BATCH} jobs per batch",
                    "type": "max_length",
                }
            ],
        )
    payloads: list[dict[str, Any]] = []
    for job in jobs:
        payloads.append(build_backend_job_payload(job).model_dump(mode="json", by_alias=True))
    return {"jobs": payloads}


def build_skill_payloads(job: NormalizedJob) -> list[BackendSkillPayload]:
    staged = list(getattr(job, "skills_staging", []) or [])
    if staged:
        return [skill_payload_from_staging(job, skill) for skill in staged]
    return [
        BackendSkillPayload(name=value, source="normalized")
        for value in job.normalized_payload.get("skills", [])
        if isinstance(value, str) and value.strip()
    ]


def skill_payload_from_staging(job: NormalizedJob, skill: JobSkillStaging) -> BackendSkillPayload:
    if skill.normalized_job_id != job.id:
        raise BackendPayloadValidationError(
            "orphan JobSkill row: normalized job relation mismatch",
            external_job_id=job.external_id,
        )
    return BackendSkillPayload(
        name=skill.normalized_value,
        confidence=skill.confidence,
        source=skill.source,
    )


def build_requirement_payloads(job: NormalizedJob) -> list[BackendRequirementPayload]:
    staged = list(getattr(job, "requirements_staging", []) or [])
    return [requirement_payload_from_staging(job, requirement) for requirement in staged]


def requirement_payload_from_staging(
    job: NormalizedJob,
    requirement: JobRequirementStaging,
) -> BackendRequirementPayload:
    if requirement.normalized_job_id != job.id:
        raise BackendPayloadValidationError(
            "orphan JobRequirement row: normalized job relation mismatch",
            external_job_id=job.external_id,
        )
    try:
        requirement_type = PrismaRequirementType(requirement.requirement_type.strip().upper())
    except ValueError as exc:
        raise BackendPayloadValidationError(
            "invalid requirement type for backend sync contract",
            external_job_id=job.external_id,
            details=[{"loc": ["requirements", "type"], "msg": str(exc), "type": "enum"}],
        ) from exc
    return BackendRequirementPayload(
        type=requirement_type,
        value=requirement.normalized_value,
        confidence=requirement.confidence,
        source=requirement.source,
    )


def map_work_type(value: Any) -> PrismaWorkType | None:
    mapped = map_backend_enum(value)
    if mapped in {item.value for item in PrismaWorkType}:
        return PrismaWorkType(mapped)
    return None


def map_employment_type(values: Any) -> PrismaEmploymentType | None:
    if isinstance(values, list):
        for value in values:
            mapped = map_employment_type(value)
            if mapped is not None:
                return mapped
        return None
    mapped = map_backend_enum(values)
    if mapped in {item.value for item in PrismaEmploymentType}:
        return PrismaEmploymentType(mapped)
    return None


def map_experience_level(value: Any) -> PrismaExperienceLevel | None:
    mapped = map_backend_enum(value)
    if mapped in {item.value for item in PrismaExperienceLevel}:
        return PrismaExperienceLevel(mapped)
    return None


def map_salary_period(value: Any, display: str | None) -> PrismaSalaryPeriod | None:
    mapped = map_backend_enum(value)
    if mapped in {item.value for item in PrismaSalaryPeriod}:
        return PrismaSalaryPeriod(mapped)
    if display and MONTHLY_PATTERN.search(display):
        return PrismaSalaryPeriod.MONTHLY
    if display and YEARLY_PATTERN.search(display):
        return PrismaSalaryPeriod.YEARLY
    return None


def map_job_status(value: Any) -> PrismaJobListingStatus:
    canonical = map_canonical_status(value)
    mapping = {
        CanonicalJobStatus.ACTIVE: PrismaJobListingStatus.ACTIVE,
        CanonicalJobStatus.STALE: PrismaJobListingStatus.STALE,
        CanonicalJobStatus.EXPIRED: PrismaJobListingStatus.EXPIRED,
        CanonicalJobStatus.INACTIVE: PrismaJobListingStatus.CLOSED,
        CanonicalJobStatus.UNKNOWN: PrismaJobListingStatus.ACTIVE,
    }
    return mapping[canonical]


def map_canonical_status(value: Any) -> CanonicalJobStatus:
    mapped = map_backend_enum(value)
    if mapped == CanonicalJobStatus.ACTIVE.value.upper():
        return CanonicalJobStatus.ACTIVE
    if mapped == CanonicalJobStatus.STALE.value.upper():
        return CanonicalJobStatus.STALE
    if mapped == CanonicalJobStatus.EXPIRED.value.upper():
        return CanonicalJobStatus.EXPIRED
    if mapped == CanonicalJobStatus.INACTIVE.value.upper():
        return CanonicalJobStatus.INACTIVE
    return CanonicalJobStatus.UNKNOWN


def map_backend_enum(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, StrEnum):
        return value.value.upper()
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str):
        return None
    return value.strip().replace("-", "_").replace(" ", "_").upper()


def parse_source_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return parse_absolute_datetime(value)


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def first_non_empty(values: list[Any]) -> str | None:
    for value in values:
        text = optional_text(value)
        if text:
            return text
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


def normalized_currency(value: Any) -> str | None:
    text = optional_text(value)
    if text is None:
        return None
    if len(text) != 3:
        return None
    return text.upper()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def platform_display_name(slug: str) -> str:
    mapping = {
        "dealls": "Dealls",
        "glints": "Glints",
        "jobstreet": "JobStreet",
        "kalibrr": "Kalibrr",
    }
    normalized = slug.strip().lower()
    return mapping.get(normalized, normalized.title())
