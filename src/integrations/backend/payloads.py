from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from modules.jobs.completion import (
    build_source_limited_summary,
    clean_description,
    infer_experience_level,
    is_placeholder_text,
    normalize_location_fields,
)
from modules.jobs.dates import parse_absolute_datetime
from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import JobRequirementStaging, JobSkillStaging, NormalizedJob

MONTHLY_PATTERN = re.compile(r"\b(month|monthly|bulan|bulanan)\b", re.IGNORECASE)
YEARLY_PATTERN = re.compile(r"\b(year|yearly|tahun|tahunan)\b", re.IGNORECASE)
VISUAL_NOISE_PATTERN = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")
INVISIBLE_NOISE_PATTERN = re.compile(r"[\u200B-\u200F\u2060\uFE0E\uFE0F]")
MAX_JOBS_PER_BACKEND_BATCH = 100
MAX_RELATIONS_PER_BACKEND_JOB = 100
SALARY_PLACEHOLDER_TEXTS = {"tidak dicantumkan", "not specified", "not disclosed"}
INDONESIAN_MARKERS = {
    "dan",
    "dengan",
    "pengalaman",
    "kualifikasi",
    "minimal",
    "menguasai",
    "mampu",
    "lulusan",
    "sarjana",
    "tahun",
    "bulan",
    "lokasi",
    "indonesia",
}
REQUIREMENT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bexperience\s*:\s*", re.IGNORECASE), "Pengalaman: "),
    (re.compile(r"\bcategory\s*:\s*", re.IGNORECASE), "Kategori: "),
    (re.compile(r"\bskills?\s*:\s*", re.IGNORECASE), "Keahlian: "),
    (re.compile(r"\bminimum\s+(\d+)\s+years?\b", re.IGNORECASE), r"minimal \1 tahun"),
    (re.compile(r"\bup to\s+(\d+)\s+years?\b", re.IGNORECASE), r"hingga \1 tahun"),
    (re.compile(r"\b(\d+)\s*-\s*(\d+)\s+years?\b", re.IGNORECASE), r"\1-\2 tahun"),
    (re.compile(r"\byears?\b", re.IGNORECASE), "tahun"),
    (re.compile(r"\band\b", re.IGNORECASE), "dan"),
)
TECH_SKILL_PATTERN = re.compile(
    r"\b("
    r"python|java(?:script)?|typescript|go(?:lang)?|php|ruby|kotlin|swift|rust|"
    r"c\+\+|c#|sql|postgres(?:ql)?|mysql|mariadb|mongodb|redis|oracle|"
    r"docker|kubernetes|terraform|ansible|linux|git|"
    r"node(?:\.js)?|react(?:\.js)?|vue(?:\.js)?|angular|next(?:\.js)?|nuxt(?:\.js)?|"
    r"laravel|django|flask|fastapi|spring(?: boot)?|express(?:\.js)?|"
    r"aws|gcp|azure|"
    r"rest(?:ful)?\s*api|graphql|ci/cd|microservices?"
    r")\b",
    re.IGNORECASE,
)
ROLE_BASED_SKILL_FALLBACKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(engineer|developer|programmer|software|backend|frontend|full stack)\b",
            re.IGNORECASE,
        ),
        "Pemrograman",
    ),
    (
        re.compile(
            r"\b(sales|business development|account executive|telemarketing)\b",
            re.IGNORECASE,
        ),
        "Negosiasi",
    ),
    (
        re.compile(r"\b(marketing|brand|content|social media|seo|sem)\b", re.IGNORECASE),
        "Pemasaran Digital",
    ),
    (
        re.compile(r"\b(customer service|customer support|helpdesk|call center)\b", re.IGNORECASE),
        "Pelayanan Pelanggan",
    ),
    (
        re.compile(r"\b(finance|accounting|akuntan|tax|auditor)\b", re.IGNORECASE),
        "Analisis Keuangan",
    ),
    (
        re.compile(r"\b(hr|recruiter|talent acquisition|people)\b", re.IGNORECASE),
        "Komunikasi Interpersonal",
    ),
    (
        re.compile(r"\b(operation|logistic|warehouse|supply chain)\b", re.IGNORECASE),
        "Manajemen Operasional",
    ),
    (
        re.compile(r"\b(product manager|product owner|project manager)\b", re.IGNORECASE),
        "Manajemen Proyek",
    ),
)
TECH_SKILL_CANONICAL_MAP = {
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "golang": "Go",
    "php": "PHP",
    "ruby": "Ruby",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "rust": "Rust",
    "c++": "C++",
    "c#": "C#",
    "sql": "SQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "oracle": "Oracle",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "linux": "Linux",
    "git": "Git",
    "node": "Node.js",
    "node.js": "Node.js",
    "react": "React",
    "react.js": "React",
    "vue": "Vue",
    "vue.js": "Vue",
    "angular": "Angular",
    "next": "Next.js",
    "next.js": "Next.js",
    "nuxt": "Nuxt.js",
    "nuxt.js": "Nuxt.js",
    "laravel": "Laravel",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring",
    "spring boot": "Spring Boot",
    "express": "Express.js",
    "express.js": "Express.js",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "rest api": "REST API",
    "restful api": "REST API",
    "graphql": "GraphQL",
    "ci/cd": "CI/CD",
    "microservice": "Microservices",
    "microservices": "Microservices",
}


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
    salary_currency: str = Field(
        default="IDR",
        min_length=3,
        max_length=3,
        serialization_alias="salaryCurrency",
    )
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

    normalized_location = normalize_location_fields(
        city=location.get("city"),
        region=location.get("region"),
        country=location.get("country"),
        display=location.get("display"),
        is_remote=location.get("is_remote"),
    )
    location_display = optional_text(normalized_location.get("display"))
    location_city = optional_text(normalized_location.get("city"))
    location_region = optional_text(normalized_location.get("region"))

    company_name = first_non_empty([company.get("name"), job.company_name])
    description = clean_description(payload.get("description"))
    if description is None and job.source_platform.strip().lower() == "glints":
        description = build_source_limited_summary(
            title=job.title,
            company=company_name,
            location=location_display,
            source_platform=job.source_platform,
        )
    raw_skills = payload.get("skills")
    normalized_skills = (
        [item.strip() for item in raw_skills if isinstance(item, str) and item.strip()]
        if isinstance(raw_skills, list)
        else []
    )
    requirement_summary = improve_requirement_summary(
        clean_description(payload.get("requirements")),
        skills=normalized_skills,
    )
    description = improve_description(
        description,
        title=job.title,
        company_name=company_name,
        location_display=location_display,
        requirement_summary=requirement_summary,
        skills=normalized_skills,
    )

    employment_type = (
        map_employment_type(payload.get("employment_types")) or PrismaEmploymentType.FULL_TIME
    )
    work_type = map_work_type(payload.get("work_type")) or PrismaWorkType.ONSITE
    experience_level = map_experience_level(payload.get("experience_level"))
    if experience_level is None:
        experience_level = map_experience_level(
            infer_experience_level(
                explicit=payload.get("experience_level"),
                title=payload.get("title"),
                description=description,
                requirements=requirement_summary,
            )
        )
    if experience_level is None:
        experience_level = PrismaExperienceLevel.ENTRY_LEVEL
    status = map_job_status(job.status)
    source_posted_at = iso_or_none(job.posted_at) or iso_or_none(
        parse_source_datetime(payload.get("posted_at"))
    )
    source_updated_at = iso_or_none(parse_source_datetime(source.get("source_updated_at")))
    salary_min = optional_int(salary.get("min_amount"))
    salary_max = optional_int(salary.get("max_amount"))
    salary_display = optional_text(salary.get("display"))
    salary_period = map_salary_period(salary.get("period"), salary_display)
    if salary_period is None:
        salary_period = PrismaSalaryPeriod.MONTHLY
    salary_currency = normalized_currency(salary.get("currency")) or "IDR"
    if (
        salary_display is not None
        and (salary_min is not None or salary_max is not None)
        and salary_display.casefold() in SALARY_PLACEHOLDER_TEXTS
    ):
        salary_display = None
    if salary_display is None:
        salary_display = build_salary_display_fallback(
            min_amount=salary_min,
            max_amount=salary_max,
            currency=salary_currency,
            period=salary_period,
        )
    if salary_display is None:
        salary_display = "Tidak dicantumkan"

    try:
        return BackendJobPayload(
            source_platform=BackendSourcePlatformPayload(
                slug=job.source_platform,
                name=platform_display_name(job.source_platform),
            ),
            company=BackendCompanyPayload(
                name=company_name or "",
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
                normalized_title=optional_text(payload.get("normalized_title")) or job.title,
                category=optional_text(payload.get("category")),
                description=description,
                requirement_summary=requirement_summary,
                work_type=work_type,
                employment_type=employment_type,
                experience_level=experience_level,
                location_display=location_display,
                province=location_region,
                city=location_city,
                salary_min=salary_min,
                salary_max=salary_max,
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

    payload = job.normalized_payload if isinstance(job.normalized_payload, dict) else {}
    normalized_skills = [
        BackendSkillPayload(name=value, source="normalized")
        for value in payload.get("skills", [])
        if isinstance(value, str) and value.strip()
    ]
    if normalized_skills:
        return dedupe_skill_payloads(normalized_skills)

    derived_skills = derive_fallback_skills(job)
    if derived_skills:
        return dedupe_skill_payloads(
            [BackendSkillPayload(name=value, source="normalized") for value in derived_skills]
        )

    # Global non-empty fallback for downstream sync completeness.
    return [BackendSkillPayload(name="Komunikasi", source="normalized")]


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
    if staged:
        return [requirement_payload_from_staging(job, requirement) for requirement in staged]

    normalized_requirement = derive_fallback_requirement(job)
    return [
        BackendRequirementPayload(
            type=PrismaRequirementType.OTHER,
            value=normalized_requirement,
            confidence=None,
            source="normalized",
        )
    ]


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


def dedupe_skill_payloads(values: list[BackendSkillPayload]) -> list[BackendSkillPayload]:
    deduped: list[BackendSkillPayload] = []
    seen: set[str] = set()
    for skill in values:
        key = skill.name.casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(skill)
    return deduped


def derive_fallback_requirement(job: NormalizedJob) -> str:
    payload = job.normalized_payload if isinstance(job.normalized_payload, dict) else {}
    requirement_text = normalize_text_block(optional_text(payload.get("requirements")))
    if requirement_text:
        return requirement_text

    description = normalize_text_block(optional_text(payload.get("description")))
    if description:
        brief = description[:260].strip()
        return f"Memiliki kompetensi yang relevan untuk menjalankan peran ini: {brief}"

    title = optional_text(payload.get("title")) or job.title
    return f"Memiliki kompetensi inti yang sesuai untuk posisi {title}."


def derive_fallback_skills(job: NormalizedJob) -> list[str]:
    payload = job.normalized_payload if isinstance(job.normalized_payload, dict) else {}
    texts = [
        optional_text(payload.get("requirements")),
        optional_text(payload.get("description")),
        optional_text(payload.get("title")),
        job.title,
    ]
    derived_tech = derive_tech_skills_from_texts([text for text in texts if text])
    if derived_tech:
        return derived_tech[:8]

    joined = " ".join(text for text in texts if text).strip()
    if not joined:
        return []

    for pattern, fallback in ROLE_BASED_SKILL_FALLBACKS:
        if pattern.search(joined):
            return [fallback]
    return []


def derive_tech_skills_from_texts(texts: list[str]) -> list[str]:
    found: list[str] = []
    for value in texts:
        normalized = normalize_text_block(value)
        if normalized is None:
            continue
        for token in TECH_SKILL_PATTERN.findall(normalized):
            canonical = TECH_SKILL_CANONICAL_MAP.get(token.strip().casefold())
            if canonical:
                found.append(canonical)
    return dedupe_strings(found)


def dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


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
        if not text or is_placeholder_text(text):
            return None
        return text
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


def improve_requirement_summary(value: str | None, *, skills: list[str]) -> str | None:
    text = normalize_text_block(value)
    if text is None and skills:
        text = f"Menguasai {', '.join(skills[:6])}."
    if text is None:
        return None
    text = normalize_requirement_language(text)
    if text.casefold().startswith("kualifikasi utama: kualifikasi utama:"):
        text = text[len("Kualifikasi utama: ") :]
    if text.casefold().startswith(("kualifikasi", "persyaratan")):
        return text
    return f"Kualifikasi utama: {text}"


def improve_description(
    value: str | None,
    *,
    title: str,
    company_name: str | None,
    location_display: str | None,
    requirement_summary: str | None,
    skills: list[str],
) -> str | None:
    text = normalize_text_block(value)
    if text is not None:
        return text

    company_text = company_name or "perusahaan terkait"
    location_text = f" di {location_display}" if location_display else ""
    overview = (
        f"Posisi {title} di {company_text}{location_text} berfokus pada pelaksanaan tanggung jawab "
        "teknis sesuai kebutuhan bisnis."
    )
    details: list[str] = [overview]

    if requirement_summary:
        details.append(f"Ringkasan kualifikasi: {requirement_summary}")
    elif skills:
        details.append(f"Kompetensi yang dibutuhkan antara lain {', '.join(skills[:8])}.")

    if not looks_like_indonesian(" ".join(details)):
        details.insert(0, "Deskripsi peran ini disusun ulang dalam Bahasa Indonesia.")
    return " ".join(details)


def normalize_text_block(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = strip_visual_noise(value)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    cleaned = cleaned.replace("•", ". ").replace(" - ", ". ")
    cleaned = " ".join(cleaned.split())
    return cleaned


def strip_visual_noise(value: str) -> str:
    cleaned = VISUAL_NOISE_PATTERN.sub(" ", value)
    cleaned = INVISIBLE_NOISE_PATTERN.sub("", cleaned)
    return cleaned.replace("▪", " ").replace("◦", " ")


def normalize_requirement_language(value: str) -> str:
    normalized = value
    for pattern, replacement in REQUIREMENT_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def looks_like_indonesian(value: str) -> bool:
    lowered = value.casefold()
    return sum(marker in lowered for marker in INDONESIAN_MARKERS) >= 2


def build_salary_display_fallback(
    *,
    min_amount: int | None,
    max_amount: int | None,
    currency: str,
    period: PrismaSalaryPeriod | None,
) -> str | None:
    if min_amount is None and max_amount is None:
        return None

    low = min_amount
    high = max_amount
    if low is not None and high is not None and low > high:
        low, high = high, low

    if low is not None and high is not None:
        amount_text = (
            f"{format_salary_amount(low, currency)} - {format_salary_amount(high, currency)}"
        )
    else:
        single = low if low is not None else high
        if single is None:
            return None
        amount_text = format_salary_amount(single, currency)

    period_text = period_suffix(period)
    if period_text:
        return f"{amount_text} {period_text}"
    return amount_text


def format_salary_amount(value: int, currency: str) -> str:
    if currency == "IDR":
        return f"Rp {value:,}".replace(",", ".")
    return f"{currency} {value:,}"


def period_suffix(period: PrismaSalaryPeriod | None) -> str:
    if period is PrismaSalaryPeriod.MONTHLY:
        return "per bulan"
    if period is PrismaSalaryPeriod.YEARLY:
        return "per tahun"
    return ""


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
