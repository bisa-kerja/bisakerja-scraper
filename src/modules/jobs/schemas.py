from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1)]


class SourcePlatform(StrEnum):
    DEALLS = "dealls"
    GLINTS = "glints"
    JOBSTREET = "jobstreet"
    KALIBRR = "kalibrr"


class CanonicalJobStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class WorkType(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"
    UNKNOWN = "unknown"


class SalaryPeriod(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    UNKNOWN = "unknown"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class CompanySchema(CanonicalModel):
    name: NonEmptyStr
    logo_url: str | None = None
    industry: str | None = None
    source_company_id: str | None = None
    source_slug: str | None = None


class LocationSchema(CanonicalModel):
    display: NonEmptyStr | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    is_remote: bool | None = None


class SalarySchema(CanonicalModel):
    min_amount: int | None = Field(default=None, ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: SalaryPeriod | None = None
    display: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def validate_salary_range(self) -> SalarySchema:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("salary min_amount must be less than or equal to max_amount")
        return self


class SourceMetadataSchema(CanonicalModel):
    platform: SourcePlatform
    external_job_id: NonEmptyStr
    source_slug: str | None = None
    source_url: NonEmptyStr
    external_apply_url: str | None = None
    raw_payload_hash: str | None = None
    scraped_at: datetime
    source_updated_at: datetime | None = None


class PresentationMetadataSchema(CanonicalModel):
    posted_label: str | None = None
    salary_label: str | None = None
    badges: list[str] = Field(default_factory=list)
    source_labels: dict[str, Any] = Field(default_factory=dict)


class CanonicalJobSchema(CanonicalModel):
    source: SourceMetadataSchema
    title: NonEmptyStr
    company: CompanySchema
    location: LocationSchema = Field(default_factory=LocationSchema)
    salary: SalarySchema | None = None
    employment_types: list[EmploymentType] = Field(default_factory=list)
    work_type: WorkType = WorkType.UNKNOWN
    description: str | None = None
    requirements: str | None = None
    skills: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    last_seen_at: datetime
    status: CanonicalJobStatus = CanonicalJobStatus.UNKNOWN
    presentation: PresentationMetadataSchema = Field(default_factory=PresentationMetadataSchema)

    @field_validator("skills", "employment_types")
    @classmethod
    def deduplicate_list(cls, value: list[Any]) -> list[Any]:
        deduplicated: list[Any] = []
        for item in value:
            if item not in deduplicated:
                deduplicated.append(item)
        return deduplicated
