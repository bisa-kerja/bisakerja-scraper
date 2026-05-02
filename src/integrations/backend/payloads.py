from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from modules.persistence import JobRequirementStaging, JobSkillStaging, NormalizedJob


class BackendPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class BackendCompanyPayload(BackendPayloadModel):
    name: str
    source_company_id: str | None = Field(default=None, serialization_alias="sourceCompanyId")
    source_slug: str | None = Field(default=None, serialization_alias="sourceSlug")
    logo_url: str | None = Field(default=None, serialization_alias="logoUrl")
    industry: str | None = None


class BackendLocationPayload(BackendPayloadModel):
    display: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    is_remote: bool | None = Field(default=None, serialization_alias="isRemote")


class BackendSalaryPayload(BackendPayloadModel):
    min_amount: int | None = Field(default=None, serialization_alias="minAmount")
    max_amount: int | None = Field(default=None, serialization_alias="maxAmount")
    currency: str | None = None
    period: str | None = None
    display: str | None = None


class BackendSkillPayload(BackendPayloadModel):
    name: str
    confidence: float | None = None
    source: str | None = None


class BackendRequirementPayload(BackendPayloadModel):
    type: str
    value: str
    confidence: float | None = None
    source: str | None = None


class BackendJobPayload(BackendPayloadModel):
    source_platform: str = Field(serialization_alias="sourcePlatform")
    external_job_id: str = Field(serialization_alias="externalJobId")
    source_url: str = Field(serialization_alias="sourceUrl")
    external_apply_url: str | None = Field(default=None, serialization_alias="externalApplyUrl")
    title: str
    description: str | None = None
    company: BackendCompanyPayload
    location: BackendLocationPayload
    salary: BackendSalaryPayload | None = None
    employment_types: list[str] = Field(default_factory=list, serialization_alias="employmentTypes")
    work_type: str | None = Field(default=None, serialization_alias="workType")
    status: str
    posted_at: str | None = Field(default=None, serialization_alias="postedAt")
    last_seen_at: str = Field(serialization_alias="lastSeenAt")
    skills: list[BackendSkillPayload] = Field(default_factory=list)
    requirements: list[BackendRequirementPayload] = Field(default_factory=list)


def build_backend_job_payload(job: NormalizedJob) -> BackendJobPayload:
    payload = job.normalized_payload
    company = as_dict(payload.get("company"))
    location = as_dict(payload.get("location"))
    salary = payload.get("salary")

    return BackendJobPayload(
        source_platform=job.source_platform,
        external_job_id=job.external_id,
        source_url=job.source_url,
        external_apply_url=job.apply_url,
        title=job.title,
        description=payload.get("description"),
        company=BackendCompanyPayload(
            name=job.company_name,
            source_company_id=company.get("source_company_id"),
            source_slug=company.get("source_slug"),
            logo_url=company.get("logo_url"),
            industry=company.get("industry"),
        ),
        location=BackendLocationPayload(
            display=location.get("display"),
            city=location.get("city"),
            region=location.get("region"),
            country=location.get("country"),
            is_remote=location.get("is_remote"),
        ),
        salary=build_salary_payload(salary),
        employment_types=[map_backend_enum(value) for value in payload.get("employment_types", [])],
        work_type=map_backend_enum(payload.get("work_type")),
        status=map_backend_status(job.status),
        posted_at=iso_or_none(job.posted_at),
        last_seen_at=job.last_seen_at.isoformat(),
        skills=build_skill_payloads(job),
        requirements=build_requirement_payloads(job),
    )


def build_backend_jobs_body(jobs: list[NormalizedJob]) -> dict[str, Any]:
    return {
        "jobs": [
            build_backend_job_payload(job).model_dump(mode="json", by_alias=True) for job in jobs
        ]
    }


def build_salary_payload(value: Any) -> BackendSalaryPayload | None:
    if not isinstance(value, dict):
        return None
    return BackendSalaryPayload(
        min_amount=value.get("min_amount"),
        max_amount=value.get("max_amount"),
        currency=value.get("currency"),
        period=map_backend_enum(value.get("period")),
        display=value.get("display"),
    )


def build_skill_payloads(job: NormalizedJob) -> list[BackendSkillPayload]:
    staged = list(getattr(job, "skills_staging", []) or [])
    if staged:
        return [skill_payload_from_staging(skill) for skill in staged]
    return [
        BackendSkillPayload(name=value, source="normalized")
        for value in job.normalized_payload.get("skills", [])
        if isinstance(value, str) and value.strip()
    ]


def skill_payload_from_staging(skill: JobSkillStaging) -> BackendSkillPayload:
    return BackendSkillPayload(
        name=skill.normalized_value,
        confidence=skill.confidence,
        source=skill.source,
    )


def build_requirement_payloads(job: NormalizedJob) -> list[BackendRequirementPayload]:
    return [
        requirement_payload_from_staging(requirement)
        for requirement in list(getattr(job, "requirements_staging", []) or [])
    ]


def requirement_payload_from_staging(
    requirement: JobRequirementStaging,
) -> BackendRequirementPayload:
    return BackendRequirementPayload(
        type=requirement.requirement_type,
        value=requirement.normalized_value,
        confidence=requirement.confidence,
        source=requirement.source,
    )


def map_backend_enum(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str):
        return None
    return value.replace("-", "_").upper()


def map_backend_status(value: str) -> str:
    mapped = map_backend_enum(value)
    return mapped or "UNKNOWN"


def iso_or_none(value) -> str | None:  # noqa: ANN001
    return value.isoformat() if value is not None else None


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
