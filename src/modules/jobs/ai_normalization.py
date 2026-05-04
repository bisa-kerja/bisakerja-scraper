from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from modules.jobs.salary import normalize_salary
from modules.jobs.schemas import CanonicalJobSchema, SourcePlatform
from shared.text import clean_text, html_to_text

_HTML_LIKE_PATTERN = re.compile(r"<[^>]+>")
_SOURCE_DETAIL_KEYS = {
    "description",
    "responsibilities",
    "requirements",
    "qualifications",
    "content",
}


class NormalizationEndpointType(StrEnum):
    LIST = "list"
    DETAIL = "detail"


class AINormalizationPromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    source_platform: SourcePlatform = Field(serialization_alias="sourcePlatform")
    endpoint_type: NormalizationEndpointType = Field(serialization_alias="endpointType")
    raw_payload_subset: dict[str, Any] = Field(serialization_alias="rawPayloadSubset")
    target_schema: str = Field(default="CanonicalJobSchema", serialization_alias="targetSchema")

    @model_validator(mode="after")
    def validate_raw_payload_subset(self) -> AINormalizationPromptInput:
        if not self.raw_payload_subset:
            raise ValueError("rawPayloadSubset must not be empty")
        return self


class AINormalizationContractError(ValueError):
    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


def build_ai_normalization_messages(
    prompt_input: AINormalizationPromptInput,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": AI_NORMALIZATION_SYSTEM_PROMPT},
        {"role": "user", "content": build_ai_normalization_user_prompt(prompt_input)},
    ]


def build_ai_normalization_user_prompt(prompt_input: AINormalizationPromptInput) -> str:
    request = {
        "sourcePlatform": prompt_input.source_platform.value,
        "endpointType": prompt_input.endpoint_type.value,
        "targetSchema": prompt_input.target_schema,
        "rawPayloadSubset": prompt_input.raw_payload_subset,
        "targetJsonSchema": CanonicalJobSchema.model_json_schema(),
        "backendSchemaContext": BACKEND_SCHEMA_CONTEXT,
        "normalizationObjectives": NORMALIZATION_OBJECTIVES,
        "standaloneSchemaBlueprint": STANDALONE_SCHEMA_BLUEPRINT,
        "normalizationOutputExamples": NORMALIZATION_OUTPUT_EXAMPLES,
    }
    return json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_ai_normalization_format_repair_messages(
    *,
    prompt_input: AINormalizationPromptInput,
    invalid_output: str,
    validation_errors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": AI_NORMALIZATION_REPAIR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "sourcePlatform": prompt_input.source_platform.value,
                    "endpointType": prompt_input.endpoint_type.value,
                    "targetSchema": prompt_input.target_schema,
                    "targetJsonSchema": CanonicalJobSchema.model_json_schema(),
                    "backendSchemaContext": BACKEND_SCHEMA_CONTEXT,
                    "standaloneSchemaBlueprint": STANDALONE_SCHEMA_BLUEPRINT,
                    "invalidOutput": invalid_output,
                    "validationErrors": validation_errors,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def validate_ai_normalization_output(
    output: dict[str, Any] | str,
    *,
    prompt_input: AINormalizationPromptInput,
) -> CanonicalJobSchema:
    try:
        job = (
            CanonicalJobSchema.model_validate_json(output)
            if isinstance(output, str)
            else CanonicalJobSchema.model_validate(output)
        )
    except ValidationError as exc:
        raise AINormalizationContractError(
            "AI normalization output does not match CanonicalJobSchema",
            details=list(exc.errors()),
        ) from exc

    job = _apply_defaults(job)
    _validate_source_policy(job, prompt_input)
    return job


def _apply_defaults(job: CanonicalJobSchema) -> CanonicalJobSchema:
    payload = job.model_dump(mode="python")

    source = payload.get("source")
    if isinstance(source, dict):
        apply_url = source.get("external_apply_url")
        source_url = source.get("source_url")
        if not isinstance(apply_url, str) or not apply_url.strip():
            if isinstance(source_url, str) and source_url.strip():
                source["external_apply_url"] = source_url.strip()

    description = _normalize_text(payload.get("description"))
    requirements = _normalize_text(payload.get("requirements"))
    payload["description"] = description
    payload["requirements"] = requirements

    salary = payload.get("salary")
    if isinstance(salary, dict):
        normalized_salary = normalize_salary(
            min_amount=salary.get("min_amount"),
            max_amount=salary.get("max_amount"),
            currency=salary.get("currency"),
            period=salary.get("period"),
            label=salary.get("display"),
            default_currency="IDR",
        ).salary
        payload["salary"] = (
            normalized_salary.model_dump(mode="python") if normalized_salary else None
        )

    location = payload.get("location")
    if isinstance(location, dict):
        display = location.get("display")
        if not isinstance(display, str) or not display.strip():
            city = (
                clean_text(location.get("city")) if isinstance(location.get("city"), str) else None
            )
            region = (
                clean_text(location.get("region"))
                if isinstance(location.get("region"), str)
                else None
            )
            country = (
                clean_text(location.get("country"))
                if isinstance(location.get("country"), str)
                else None
            )
            parts = [part for part in (city, region, country) if part]
            location["display"] = ", ".join(parts) if parts else None

    return CanonicalJobSchema.model_validate(payload)


def _validate_source_policy(
    job: CanonicalJobSchema,
    prompt_input: AINormalizationPromptInput,
) -> None:
    if (
        prompt_input.source_platform is SourcePlatform.GLINTS
        and prompt_input.endpoint_type is NormalizationEndpointType.LIST
        and not _has_detail_coverage(prompt_input.raw_payload_subset)
    ):
        if job.description is not None or job.requirements is not None:
            raise AINormalizationContractError(
                "glints list normalization must not invent detail fields",
                details=[
                    {
                        "loc": ["description", "requirements"],
                        "msg": "detail fields are unavailable for glints list payload",
                        "type": "no_detail_coverage",
                    }
                ],
            )


def _has_detail_coverage(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _SOURCE_DETAIL_KEYS:
                text = _normalize_text(item)
                if text:
                    return True
            if _has_detail_coverage(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_detail_coverage(item) for item in value)
    return False


def _normalize_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not value.strip():
        return None
    if _HTML_LIKE_PATTERN.search(value):
        return html_to_text(value)
    return clean_text(value)


AI_NORMALIZATION_SYSTEM_PROMPT = """You are a strict job data normalizer.
Return one JSON object that must match targetJsonSchema exactly.
Rules:
1. Use only factual evidence in rawPayloadSubset. Never fabricate values.
2. Follow backendSchemaContext as strict normalization policy
   for names, enum semantics, defaults, and relation safety.
3. Treat this prompt payload as standalone contract.
   Do not depend on external files, repos, or undocumented assumptions.
4. Prioritize filling as many target fields as evidence permits.
   Keep null only when evidence is truly absent.
5. Output JSON only. No prose, markdown, comments, code fences, or extra keys.
6. Normalize HTML-like content into clean safe plain text without losing core meaning.
7. Parse salary numbers only when confidence is high. Keep uncertain numeric salary values null.
8. Map location into display, city, region, and country when evidence exists.
9. Keep Glints list records partial when detail data is unavailable.
   Do not invent description or requirements.
10. external_apply_url must fall back to source_url when missing.
11. Prefer explicit defaults aligned with backendSchemaContext default policy.
12. Keep unknown values null instead of placeholders such as '-', 'N/A', or 'unknown text'.
"""


AI_NORMALIZATION_REPAIR_SYSTEM_PROMPT = """Fix JSON format only.
Do not add, remove, or alter any semantic values.
Only return one corrected JSON object that matches the given schema."""


NORMALIZATION_OBJECTIVES: dict[str, Any] = {
    "goal": (
        "Produce canonical normalized job JSON for production sync."
        " Contract is standalone and self-contained in this prompt."
    ),
    "qualityBar": [
        "standalone contract, no cross-repo dependency",
        "maximal safe field coverage from source evidence",
        "strict enum compatibility",
        "explicit default policy alignment",
        "production-grade consistency for list and detail use cases",
    ],
}


BACKEND_SCHEMA_CONTEXT: dict[str, Any] = {
    "reference": {
        "source": "standalone embedded backend schema contract snapshot",
        "scope": "job ingestion and public jobs compatibility",
        "externalDependencyAllowed": False,
    },
    "targetModels": {
        "SourcePlatform": {
            "required": ["slug", "name"],
            "unique": ["slug"],
        },
        "Company": {
            "required": ["name"],
            "optional": ["slug", "logoUrl", "websiteUrl"],
            "indexes": ["name", "slug"],
        },
        "JobListing": {
            "required": [
                "externalJobId",
                "title",
                "sourceUrl",
                "externalApplyUrl",
                "lastSeenAt",
            ],
            "optional": [
                "normalizedTitle",
                "category",
                "description",
                "requirementSummary",
                "workType",
                "employmentType",
                "experienceLevel",
                "locationDisplay",
                "province",
                "city",
                "salaryMin",
                "salaryMax",
                "salaryPeriod",
                "salaryDisplay",
                "sourcePostedAt",
                "sourceUpdatedAt",
                "expiredAt",
            ],
            "defaultPolicy": {
                "salaryCurrency": "IDR",
                "status": "ACTIVE",
                "externalApplyUrlFallback": "sourceUrl",
            },
            "unique": ["sourcePlatform + externalJobId"],
            "constraints": ["salaryMin <= salaryMax when both not null"],
        },
        "JobRequirement": {
            "required": ["type", "value"],
            "optional": ["priority"],
            "defaultPolicy": {"sortOrder": 0},
        },
        "Skill": {
            "required": ["name"],
            "unique": ["slug"],
        },
        "JobSkill": {
            "relation": "join table between job listing and skill",
            "unique": ["jobListing + skill"],
        },
    },
    "enumContracts": {
        "workType": {
            "remote": "REMOTE",
            "hybrid": "HYBRID",
            "onsite": "ONSITE",
        },
        "employmentType": {
            "full_time": "FULL_TIME",
            "part_time": "PART_TIME",
            "internship": "INTERNSHIP",
            "contract": "CONTRACT",
            "freelance": "FREELANCE",
        },
        "salaryPeriod": {
            "monthly_markers": ["month", "monthly", "bulan"],
            "yearly_markers": ["year", "yearly", "tahun"],
            "map": {"monthly": "MONTHLY", "yearly": "YEARLY"},
        },
        "jobStatus": {
            "active": "ACTIVE",
            "stale": "STALE",
            "expired": "EXPIRED",
            "inactive_or_closed": "CLOSED",
            "unknown_fallback": "ACTIVE",
        },
        "requirementType": {
            "skill": "SKILL",
            "experience": "EXPERIENCE",
            "education": "EDUCATION",
            "responsibility": "RESPONSIBILITY",
            "other": "OTHER",
        },
    },
    "endpointCompatibility": {
        "list": {
            "mustSupport": [
                "title",
                "company",
                "sourcePlatform",
                "workType",
                "employmentType",
                "location",
                "salary",
                "postedAt",
                "lastSeenAt",
            ]
        },
        "detail": {
            "mustSupport": [
                "description",
                "requirements",
                "skills",
                "externalApplyUrl",
            ]
        },
    },
}


STANDALONE_SCHEMA_BLUEPRINT: dict[str, Any] = {
    "canonicalOutputModel": {
        "source": {
            "platform": {"type": "enum", "required": True},
            "external_job_id": {"type": "string", "required": True},
            "source_slug": {"type": "string", "required": False},
            "source_url": {"type": "string", "required": True},
            "external_apply_url": {
                "type": "string|null",
                "required": False,
                "defaultRule": "fallback_to_source_url_when_missing",
            },
            "raw_payload_hash": {"type": "string|null", "required": False},
            "scraped_at": {"type": "datetime", "required": True},
            "source_updated_at": {"type": "datetime|null", "required": False},
        },
        "title": {"type": "string", "required": True},
        "company": {
            "name": {"type": "string", "required": True},
            "logo_url": {"type": "string|null", "required": False},
            "industry": {"type": "string|null", "required": False},
            "source_company_id": {"type": "string|null", "required": False},
            "source_slug": {"type": "string|null", "required": False},
        },
        "location": {
            "display": {"type": "string|null", "required": False},
            "city": {"type": "string|null", "required": False},
            "region": {"type": "string|null", "required": False},
            "country": {"type": "string|null", "required": False},
            "is_remote": {"type": "boolean|null", "required": False},
        },
        "salary": {
            "type": "object|null",
            "required": False,
            "fields": {
                "min_amount": {"type": "integer|null", "required": False},
                "max_amount": {"type": "integer|null", "required": False},
                "currency": {
                    "type": "string|null",
                    "required": False,
                    "defaultRule": "IDR_when_missing",
                },
                "period": {"type": "enum|null", "required": False},
                "display": {"type": "string|null", "required": False},
            },
            "constraints": ["min_amount <= max_amount when both exist"],
        },
        "employment_types": {"type": "enum[]", "required": True},
        "work_type": {"type": "enum", "required": True},
        "description": {"type": "string|null", "required": False},
        "requirements": {"type": "string|null", "required": False},
        "skills": {"type": "string[]", "required": True},
        "posted_at": {"type": "datetime|null", "required": False},
        "last_seen_at": {"type": "datetime", "required": True},
        "status": {
            "type": "enum",
            "required": True,
            "defaultRule": "active_when_unknown",
        },
        "presentation": {
            "posted_label": {"type": "string|null", "required": False},
            "salary_label": {"type": "string|null", "required": False},
            "badges": {"type": "string[]", "required": True},
            "source_labels": {"type": "object", "required": True},
        },
    },
    "persistenceIntents": {
        "job_listing_required_fields": [
            "externalJobId",
            "title",
            "sourceUrl",
            "externalApplyUrl",
            "lastSeenAt",
        ],
        "job_listing_defaults": {
            "salaryCurrency": "IDR",
            "status": "ACTIVE",
            "externalApplyUrl": "fallback_to_sourceUrl",
        },
        "relations": [
            "sourcePlatform must be resolvable",
            "company must be resolvable",
            "requirements belong to one job listing",
            "job skills belong to one job listing and one skill",
        ],
    },
}


NORMALIZATION_OUTPUT_EXAMPLES: dict[str, Any] = {
    "listRecordExample": {
        "source": {
            "platform": "jobstreet",
            "external_job_id": "91788065",
            "source_slug": "programmer",
            "source_url": "https://id.jobstreet.com/id/job/91788065",
            "external_apply_url": "https://id.jobstreet.com/id/job/91788065",
            "raw_payload_hash": "sha256:sample",
            "scraped_at": "2026-05-04T09:00:00Z",
            "source_updated_at": None,
        },
        "title": "Programmer",
        "company": {
            "name": "Gamma Persada",
            "logo_url": "https://cdn.example.com/company-logo.png",
            "industry": None,
            "source_company_id": "168557159051559",
            "source_slug": "gamma-persada",
        },
        "location": {
            "display": "Jakarta Selatan, DKI Jakarta, Indonesia",
            "city": "Jakarta Selatan",
            "region": "DKI Jakarta",
            "country": "Indonesia",
            "is_remote": False,
        },
        "salary": {
            "min_amount": 8000000,
            "max_amount": 10000000,
            "currency": "IDR",
            "period": "monthly",
            "display": "Rp8.000.000 - Rp10.000.000 / bulan",
        },
        "employment_types": ["full_time"],
        "work_type": "onsite",
        "description": None,
        "requirements": None,
        "skills": [],
        "posted_at": "2026-05-01T00:00:00Z",
        "last_seen_at": "2026-05-04T09:00:00Z",
        "status": "active",
        "presentation": {
            "posted_label": "3 days ago",
            "salary_label": "Rp8.000.000 - Rp10.000.000 / bulan",
            "badges": [],
            "source_labels": {},
        },
    },
    "detailRecordExample": {
        "source": {
            "platform": "dealls",
            "external_job_id": "dealls-12345",
            "source_slug": "backend-engineer",
            "source_url": "https://dealls.com/jobs/backend-engineer",
            "external_apply_url": "https://dealls.com/jobs/backend-engineer/apply",
            "raw_payload_hash": "sha256:sample2",
            "scraped_at": "2026-05-04T09:15:00Z",
            "source_updated_at": "2026-05-03T11:00:00Z",
        },
        "title": "Backend Engineer",
        "company": {
            "name": "Bisakerja Technology",
            "logo_url": "https://cdn.example.com/bisakerja-logo.png",
            "industry": "Technology",
            "source_company_id": "cmp-7788",
            "source_slug": "bisakerja-technology",
        },
        "location": {
            "display": "Jakarta, DKI Jakarta, Indonesia",
            "city": "Jakarta",
            "region": "DKI Jakarta",
            "country": "Indonesia",
            "is_remote": True,
        },
        "salary": {
            "min_amount": 12000000,
            "max_amount": 18000000,
            "currency": "IDR",
            "period": "monthly",
            "display": "Rp12.000.000 - Rp18.000.000 / bulan",
        },
        "employment_types": ["full_time"],
        "work_type": "remote",
        "description": "Build and maintain backend APIs and data pipelines.",
        "requirements": "3+ years backend experience, Python, SQL, cloud services.",
        "skills": ["Python", "PostgreSQL", "FastAPI", "Docker"],
        "posted_at": "2026-05-02T08:00:00Z",
        "last_seen_at": "2026-05-04T09:15:00Z",
        "status": "active",
        "presentation": {
            "posted_label": "2 days ago",
            "salary_label": "Rp12.000.000 - Rp18.000.000 / bulan",
            "badges": ["remote", "urgent"],
            "source_labels": {"category": "Engineering"},
        },
    },
}
