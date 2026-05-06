from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from modules.jobs.completion import (
    build_source_limited_summary,
    clean_description,
    default_employment_types,
    default_work_type,
    infer_experience_level,
    normalize_location_fields,
)
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


class AINormalizationBatchPromptItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    item_id: str = Field(
        min_length=1,
        validation_alias="itemId",
        serialization_alias="itemId",
    )
    source_platform: SourcePlatform = Field(
        validation_alias="sourcePlatform",
        serialization_alias="sourcePlatform",
    )
    endpoint_type: NormalizationEndpointType = Field(
        validation_alias="endpointType",
        serialization_alias="endpointType",
    )
    raw_payload_subset: dict[str, Any] = Field(
        validation_alias="rawPayloadSubset",
        serialization_alias="rawPayloadSubset",
    )

    @model_validator(mode="after")
    def validate_raw_payload_subset(self) -> AINormalizationBatchPromptItem:
        if not self.raw_payload_subset:
            raise ValueError("rawPayloadSubset must not be empty")
        return self


class AINormalizationBatchPromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    items: list[AINormalizationBatchPromptItem] = Field(min_length=1, max_length=50)
    target_schema: str = Field(default="CanonicalJobSchema", serialization_alias="targetSchema")


class AINormalizationBatchItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    item_id: str = Field(
        min_length=1,
        validation_alias="itemId",
        serialization_alias="itemId",
    )
    normalized_job: CanonicalJobSchema | None = Field(
        default=None,
        validation_alias="normalizedJob",
        serialization_alias="normalizedJob",
    )
    error_code: str | None = Field(
        default=None,
        validation_alias="errorCode",
        serialization_alias="errorCode",
    )
    error_message: str | None = Field(
        default=None,
        validation_alias="errorMessage",
        serialization_alias="errorMessage",
    )

    @model_validator(mode="after")
    def validate_partial_result(self) -> AINormalizationBatchItemResult:
        has_job = self.normalized_job is not None
        has_error = bool(self.error_code and self.error_message)
        if has_job and has_error:
            raise ValueError("batch result item cannot include both normalizedJob and error")
        if not has_job and not has_error:
            raise ValueError("batch result item must include normalizedJob or error")
        return self


class AINormalizationBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    results: list[AINormalizationBatchItemResult] = Field(min_length=1)


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


def build_ai_normalization_batch_messages(
    prompt_input: AINormalizationBatchPromptInput,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": AI_NORMALIZATION_BATCH_SYSTEM_PROMPT},
        {"role": "user", "content": build_ai_normalization_batch_user_prompt(prompt_input)},
    ]


def build_ai_normalization_user_prompt(prompt_input: AINormalizationPromptInput) -> str:
    request = {
        "sourcePlatform": prompt_input.source_platform.value,
        "endpointType": prompt_input.endpoint_type.value,
        "sourceContext": _source_context(prompt_input),
        "rawEvidence": _raw_evidence_context(prompt_input.raw_payload_subset),
        "deterministicBaseline": _deterministic_baseline_context(prompt_input.raw_payload_subset),
        "targetSchema": prompt_input.target_schema,
        "rawPayloadSubset": prompt_input.raw_payload_subset,
        "targetJsonSchema": CanonicalJobSchema.model_json_schema(),
        "backendSchemaContext": BACKEND_SCHEMA_CONTEXT,
        "normalizationObjectives": NORMALIZATION_OBJECTIVES,
        "completionPolicy": COMPLETION_POLICY,
        "outputShape": OUTPUT_SHAPE_POLICY,
        "standaloneSchemaBlueprint": STANDALONE_SCHEMA_BLUEPRINT,
        "normalizationOutputExamples": NORMALIZATION_OUTPUT_EXAMPLES,
    }
    return json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_ai_normalization_batch_user_prompt(prompt_input: AINormalizationBatchPromptInput) -> str:
    request = {
        "targetSchema": prompt_input.target_schema,
        "inputItems": [
            {
                "itemId": item.item_id,
                "sourcePlatform": item.source_platform.value,
                "endpointType": item.endpoint_type.value,
                "sourceContext": _source_context(
                    AINormalizationPromptInput(
                        source_platform=item.source_platform,
                        endpoint_type=item.endpoint_type,
                        raw_payload_subset=item.raw_payload_subset,
                    )
                ),
                "rawPayloadSubset": item.raw_payload_subset,
            }
            for item in prompt_input.items
        ],
        "targetJsonSchema": CanonicalJobSchema.model_json_schema(),
        "batchOutputJsonSchema": AINormalizationBatchOutput.model_json_schema(),
        "backendSchemaContext": BACKEND_SCHEMA_CONTEXT,
        "normalizationObjectives": NORMALIZATION_OBJECTIVES,
        "completionPolicy": COMPLETION_POLICY,
        "outputShape": OUTPUT_SHAPE_POLICY,
        "standaloneSchemaBlueprint": STANDALONE_SCHEMA_BLUEPRINT,
        "normalizationOutputExamples": NORMALIZATION_OUTPUT_EXAMPLES,
        "batchOutputPolicy": {
            "resultShape": "results[]",
            "ordering": "must preserve inputItems order",
            "itemIdentity": "itemId must match input itemId exactly",
            "partialPolicy": "per-item result; never fail whole batch for one bad item",
            "errorPolicy": {
                "on_missing_evidence": "return errorCode/errorMessage for that item",
                "allowedErrorCode": ["INSUFFICIENT_EVIDENCE", "UNSUPPORTED_PAYLOAD"],
            },
        },
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

    job = _apply_defaults(job, prompt_input=prompt_input)
    _validate_source_policy(job, prompt_input)
    return job


def validate_ai_normalization_batch_output(
    output: dict[str, Any] | str | AINormalizationBatchOutput,
    *,
    prompt_input: AINormalizationBatchPromptInput,
) -> list[AINormalizationBatchItemResult]:
    try:
        batch_output = (
            AINormalizationBatchOutput.model_validate_json(output)
            if isinstance(output, str)
            else (
                output
                if isinstance(output, AINormalizationBatchOutput)
                else AINormalizationBatchOutput.model_validate(output)
            )
        )
    except ValidationError as exc:
        raise AINormalizationContractError(
            "AI normalization batch output does not match batch schema",
            details=list(exc.errors()),
        ) from exc

    expected_ids = [item.item_id for item in prompt_input.items]
    actual_ids = [item.item_id for item in batch_output.results]
    if actual_ids != expected_ids:
        raise AINormalizationContractError(
            "AI normalization batch output must preserve input item order and identity",
            details=[
                {
                    "loc": ["results", "itemId"],
                    "msg": "itemId order mismatch",
                    "type": "item_order_mismatch",
                    "expected": expected_ids,
                    "actual": actual_ids,
                }
            ],
        )

    validated_results: list[AINormalizationBatchItemResult] = []
    for request_item, result_item in zip(prompt_input.items, batch_output.results, strict=True):
        if result_item.normalized_job is None:
            validated_results.append(result_item)
            continue
        normalized = _apply_defaults(
            result_item.normalized_job,
            prompt_input=AINormalizationPromptInput(
                source_platform=request_item.source_platform,
                endpoint_type=request_item.endpoint_type,
                raw_payload_subset=request_item.raw_payload_subset,
                target_schema=prompt_input.target_schema,
            ),
        )
        _validate_source_policy(
            normalized,
            AINormalizationPromptInput(
                source_platform=request_item.source_platform,
                endpoint_type=request_item.endpoint_type,
                raw_payload_subset=request_item.raw_payload_subset,
                target_schema=prompt_input.target_schema,
            ),
        )
        validated_results.append(
            AINormalizationBatchItemResult(
                item_id=result_item.item_id,
                normalized_job=normalized,
                error_code=result_item.error_code,
                error_message=result_item.error_message,
            )
        )
    return validated_results


def _apply_defaults(
    job: CanonicalJobSchema,
    *,
    prompt_input: AINormalizationPromptInput,
) -> CanonicalJobSchema:
    payload = job.model_dump(mode="python")

    source = payload.get("source")
    if isinstance(source, dict):
        apply_url = source.get("external_apply_url")
        source_url = source.get("source_url")
        if not isinstance(apply_url, str) or not apply_url.strip():
            if isinstance(source_url, str) and source_url.strip():
                source["external_apply_url"] = source_url.strip()

    description = clean_description(_normalize_text(payload.get("description")))
    requirements = clean_description(_normalize_text(payload.get("requirements")))
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
        normalized_location = normalize_location_fields(
            city=location.get("city"),
            region=location.get("region"),
            country=location.get("country"),
            display=location.get("display"),
            is_remote=location.get("is_remote"),
        )
        location.update(normalized_location)

    payload["work_type"] = default_work_type(payload.get("work_type"))
    payload["employment_types"] = default_employment_types(payload.get("employment_types"))
    payload["experience_level"] = infer_experience_level(
        explicit=payload.get("experience_level"),
        title=payload.get("title"),
        description=payload.get("description"),
        requirements=payload.get("requirements"),
    )

    if (
        prompt_input.source_platform is SourcePlatform.GLINTS
        and prompt_input.endpoint_type is NormalizationEndpointType.LIST
        and not _has_detail_coverage(prompt_input.raw_payload_subset)
        and payload.get("description") is None
    ):
        company = payload.get("company") if isinstance(payload.get("company"), dict) else {}
        location_display = None
        if isinstance(location, dict):
            location_display = location.get("display")
        payload["description"] = build_source_limited_summary(
            title=payload.get("title"),
            company=company.get("name") if isinstance(company, dict) else None,
            location=location_display,
            source_platform=prompt_input.source_platform.value,
        )

    return CanonicalJobSchema.model_validate(payload)


def _validate_source_policy(
    job: CanonicalJobSchema,
    prompt_input: AINormalizationPromptInput,
) -> None:
    if not (
        prompt_input.source_platform is SourcePlatform.GLINTS
        and prompt_input.endpoint_type is NormalizationEndpointType.LIST
        and not _has_detail_coverage(prompt_input.raw_payload_subset)
    ):
        return
    if job.description is None:
        raise AINormalizationContractError(
            "glints list normalization requires source-limited description summary",
            details=[
                {
                    "loc": ["description"],
                    "msg": "description summary is required when detail coverage is unavailable",
                    "type": "source_limited_summary_required",
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


def _source_context(prompt_input: AINormalizationPromptInput) -> dict[str, Any]:
    detail_capability = _detail_capability(
        prompt_input.source_platform,
        prompt_input.endpoint_type,
        prompt_input.raw_payload_subset,
    )
    endpoint_mode = prompt_input.endpoint_type.value
    if detail_capability == "available":
        endpoint_mode = "list+detail"
    elif detail_capability == "embedded":
        endpoint_mode = "list+embedded-detail"
    return {
        "sourcePlatform": prompt_input.source_platform.value,
        "detailCapability": detail_capability,
        "endpointType": prompt_input.endpoint_type.value,
        "effectiveEndpointType": endpoint_mode,
    }


def _raw_evidence_context(raw_payload_subset: dict[str, Any]) -> dict[str, Any]:
    list_payload = raw_payload_subset.get("list")
    detail_payload = raw_payload_subset.get("detail")
    return {
        "hasListPayload": isinstance(list_payload, dict) or bool(raw_payload_subset),
        "hasDetailPayload": isinstance(detail_payload, dict),
        "detailMetadata": raw_payload_subset.get("detailMetadata"),
    }


def _deterministic_baseline_context(raw_payload_subset: dict[str, Any]) -> dict[str, Any]:
    baseline = raw_payload_subset.get("deterministicBaseline")
    if isinstance(baseline, dict):
        return baseline
    return {
        "status": "provided_by_mapper",
        "fieldProvenance": raw_payload_subset.get("fieldProvenance", {}),
    }


def _detail_capability(
    source_platform: SourcePlatform,
    endpoint_type: NormalizationEndpointType,
    raw_payload_subset: dict[str, Any],
) -> str:
    detail_metadata = raw_payload_subset.get("detailMetadata")
    if isinstance(detail_metadata, dict):
        coverage = detail_metadata.get("coverage")
        if isinstance(coverage, str) and coverage.strip():
            return coverage.strip().lower()
    if source_platform is SourcePlatform.GLINTS:
        return "unavailable"
    if source_platform is SourcePlatform.KALIBRR:
        return "embedded"
    if endpoint_type is NormalizationEndpointType.DETAIL:
        return "available"
    return "missing"


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
   City/province resolution is open-world (not whitelist-based).
   Use reliable geographic reasoning when source fields are ambiguous.
9. Keep Glints list records partial when detail data is unavailable.
   Use factual source-limited description summary; never invent official detail content.
10. external_apply_url must fall back to source_url when missing.
11. Prefer explicit defaults aligned with backendSchemaContext default policy.
12. Keep unknown values null instead of placeholders such as '-', 'N/A', or 'unknown text'.
"""


AI_NORMALIZATION_BATCH_SYSTEM_PROMPT = """You are a strict job data normalizer for batch processing.
Return JSON object only in shape {"results":[...]}.
Rules:
1. Every input item is independent and must return exactly one result item.
2. Preserve item order exactly as input; each output itemId must match input itemId.
3. For each item, return either normalizedJob (valid CanonicalJobSchema) OR errorCode+errorMessage.
4. Never fail whole batch because one item has low evidence or unsupported payload.
5. Use only factual evidence in each rawPayloadSubset. Never fabricate values.
6. Follow backendSchemaContext as strict normalization policy for defaults,
   enums, and relation safety.
7. Fill as many fields as evidence permits; keep null only when evidence is truly absent.
8. Output JSON only. No prose, markdown, comments, code fences, or extra keys.
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


COMPLETION_POLICY: dict[str, Any] = {
    "fieldPriority": [
        "source evidence first",
        "deterministic mapper baseline second",
        "derived values only when evidence is sufficient",
    ],
    "disallowedPlaceholders": ["-", "--", "N/A", "unknown", ""],
    "defaults": {
        "workType": "onsite",
        "employmentType": "full_time",
        "experienceLevelFallback": "entry_level",
        "salaryCurrency": "IDR",
        "salaryPeriodFallback": "monthly",
        "externalApplyUrlFallback": "source_url",
    },
    "locationResolutionPolicy": {
        "strategyOrder": [
            "explicit source city/province/region fields",
            "detail text and location display parsing",
            "validated geographic inference when evidence is sufficient",
        ],
        "openWorld": True,
        "noStaticCityWhitelist": True,
        "rules": [
            "never force province from hardcoded local dictionary",
            "normalize formatting only; keep factual geography",
            "if uncertain, keep field null and expose missing reason rather than guessing",
        ],
    },
    "confidencePolicy": {
        "sourceExactMatch": "high",
        "displayParse": "medium",
        "geoInference": "medium_or_low_depending_evidence",
    },
    "sourceLimitedSummaryRule": (
        "when detail capability is unavailable, description must be factual "
        "source-limited summary and explicitly non-official detail text"
    ),
}


OUTPUT_SHAPE_POLICY: dict[str, Any] = {
    "requiredTopLevel": [
        "source",
        "title",
        "company",
        "location",
        "employment_types",
        "work_type",
        "experience_level",
        "description",
        "requirements",
        "skills",
        "last_seen_at",
        "status",
    ]
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
