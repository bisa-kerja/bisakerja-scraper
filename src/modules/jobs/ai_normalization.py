from __future__ import annotations

import json
import re
from copy import deepcopy
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from modules.jobs.completion import (
    build_source_limited_summary,
    clean_description,
    default_employment_types,
    default_work_type,
    infer_experience_level,
    normalize_location_fields,
)
from modules.jobs.dates import parse_absolute_datetime
from modules.jobs.salary import normalize_salary
from modules.jobs.schemas import CanonicalJobSchema, SourcePlatform
from shared.text import clean_text, ensure_display_html, html_to_text, text_to_display_html

_HTML_LIKE_PATTERN = re.compile(r"<[^>]+>")
_VISUAL_NOISE_PATTERN = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")
_INVISIBLE_NOISE_PATTERN = re.compile(r"[\u200B-\u200F\u2060\uFE0E\uFE0F]")
_SOURCE_DETAIL_KEYS = {
    "description",
    "responsibilities",
    "requirements",
    "qualifications",
    "content",
}
_DESCRIPTION_KEYS = {"description", "responsibilities", "job_description", "about", "content"}
_SKILL_LIST_KEYS = {"skills", "skill", "technologies", "technology", "tech_stack", "tags"}
_REQUIREMENT_KEYS = {"requirements", "qualification", "qualifications", "requirement_summary"}
_BENEFIT_NOISE_PATTERN = re.compile(
    r"\b(thr|tunjangan|benefit|benefits?|fasilitas|bonus|cuti|bpjs|gaji pokok|kompensasi)\b",
    re.IGNORECASE,
)
_FOREIGN_COUNTRY_HINTS = {
    "singapore",
    "malaysia",
    "philippines",
    "thailand",
    "vietnam",
    "india",
    "china",
    "japan",
    "korea",
    "taiwan",
    "hong kong",
    "australia",
    "new zealand",
    "united states",
    "usa",
    "canada",
    "united kingdom",
    "uk",
    "germany",
    "france",
    "netherlands",
}
_TECH_TOKEN_PATTERN = re.compile(
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
_TECH_CANONICAL_MAP = {
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

_SUPPORTED_OUTPUT_LANGUAGES = {"indonesian", "english"}


def _normalize_output_language(value: Any) -> str:
    if value is None:
        return "english"
    if isinstance(value, StrEnum):
        value = value.value
    if not isinstance(value, str):
        raise ValueError("output_language must be a string")
    language = value.strip().casefold()
    if language not in _SUPPORTED_OUTPUT_LANGUAGES:
        raise ValueError("output_language must be indonesian or english")
    return language


def _language_display_name(output_language: str) -> str:
    return "English" if output_language == "english" else "Indonesian"


def _language_native_name(output_language: str) -> str:
    return "English" if output_language == "english" else "Bahasa Indonesia"


def _natural_language_name(output_language: str) -> str:
    return "natural English" if output_language == "english" else "natural Indonesian"


def _language_policy(output_language: str) -> dict[str, Any]:
    language = _normalize_output_language(output_language)
    display_name = _language_display_name(language)
    native_name = _language_native_name(language)
    natural_name = _natural_language_name(language)
    preserve_as_source = [
        "technology names",
        "tools",
        "frameworks",
        "company names",
        "product names",
        "location names",
    ]
    if language == "english":
        strict_rules = [
            "write generated or paraphrased human-readable content in English",
            "translate non-English source evidence into natural English before output",
            (
                "do not output Indonesian function words in generated prose "
                "(for example: dan, untuk, dengan, dari, yang, minimal, pengalaman)"
            ),
            "never mix English and Indonesian inside one generated sentence",
            "do not add translation or rewrite disclaimers",
            "preserve source language only for non-translatable proper nouns and acronyms",
        ]
    else:
        preserve_as_source.append("direct quotes copied from source evidence")
        strict_rules = [
            f"write generated or paraphrased human-readable content in {display_name}",
            "never mix languages inside one generated sentence unless preserving a source term",
            "do not add translation or rewrite disclaimers",
            "keep direct source quotations verbatim only when needed as evidence",
        ]
    return {
        "code": language,
        "name": display_name,
        "nativeName": native_name,
        "instructionLanguage": "English",
        "outputLanguage": display_name,
        "generatedProse": display_name,
        "naturalProse": natural_name,
        "appliesTo": [
            "description",
            "requirements",
            "requirement_summary",
            "presentation labels",
            "warnings",
            "fallback summaries",
        ],
        "preserveAsSource": preserve_as_source,
        "strictRules": strict_rules,
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
    output_language: str = Field(
        default="english",
        validation_alias="outputLanguage",
        serialization_alias="outputLanguage",
    )

    @field_validator("output_language")
    @classmethod
    def validate_output_language(cls, value: Any) -> str:
        return _normalize_output_language(value)

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
    output_language: str = Field(
        default="english",
        validation_alias="outputLanguage",
        serialization_alias="outputLanguage",
    )

    @field_validator("output_language")
    @classmethod
    def validate_output_language(cls, value: Any) -> str:
        return _normalize_output_language(value)


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
        {
            "role": "system",
            "content": _build_ai_normalization_system_prompt(prompt_input.output_language),
        },
        {"role": "user", "content": build_ai_normalization_user_prompt(prompt_input)},
    ]


def build_ai_normalization_batch_messages(
    prompt_input: AINormalizationBatchPromptInput,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _build_ai_normalization_batch_system_prompt(prompt_input.output_language),
        },
        {"role": "user", "content": build_ai_normalization_batch_user_prompt(prompt_input)},
    ]


def build_ai_normalization_user_prompt(prompt_input: AINormalizationPromptInput) -> str:
    output_language = _normalize_output_language(prompt_input.output_language)
    request = {
        "sourcePlatform": prompt_input.source_platform.value,
        "endpointType": prompt_input.endpoint_type.value,
        "outputLanguage": output_language,
        "outputLanguagePolicy": _language_policy(output_language),
        "sourceContext": _source_context(prompt_input),
        "rawEvidence": _raw_evidence_context(prompt_input.raw_payload_subset),
        "deterministicBaseline": _deterministic_baseline_context(prompt_input.raw_payload_subset),
        "targetSchema": prompt_input.target_schema,
        "rawPayloadSubset": prompt_input.raw_payload_subset,
        "targetJsonSchema": CanonicalJobSchema.model_json_schema(),
        "backendSchemaContext": BACKEND_SCHEMA_CONTEXT,
        "normalizationObjectives": NORMALIZATION_OBJECTIVES,
        "completionPolicy": _completion_policy(output_language),
        "outputShape": OUTPUT_SHAPE_POLICY,
        "standaloneSchemaBlueprint": STANDALONE_SCHEMA_BLUEPRINT,
        "normalizationOutputExamples": _normalization_output_examples(output_language),
    }
    return json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_ai_normalization_batch_user_prompt(prompt_input: AINormalizationBatchPromptInput) -> str:
    output_language = _normalize_output_language(prompt_input.output_language)
    request = {
        "targetSchema": prompt_input.target_schema,
        "outputLanguage": output_language,
        "outputLanguagePolicy": _language_policy(output_language),
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
        "completionPolicy": _completion_policy(output_language),
        "outputShape": OUTPUT_SHAPE_POLICY,
        "standaloneSchemaBlueprint": STANDALONE_SCHEMA_BLUEPRINT,
        "normalizationOutputExamples": _normalization_output_examples(output_language),
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
                output_language=prompt_input.output_language,
            ),
        )
        _validate_source_policy(
            normalized,
            AINormalizationPromptInput(
                source_platform=request_item.source_platform,
                endpoint_type=request_item.endpoint_type,
                raw_payload_subset=request_item.raw_payload_subset,
                target_schema=prompt_input.target_schema,
                output_language=prompt_input.output_language,
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
    run_scraped_at = parse_absolute_datetime(prompt_input.raw_payload_subset.get("scrapedAt"))

    source = payload.get("source")
    if isinstance(source, dict):
        apply_url = source.get("external_apply_url")
        source_url = source.get("source_url")
        if not isinstance(apply_url, str) or not apply_url.strip():
            if isinstance(source_url, str) and source_url.strip():
                source["external_apply_url"] = source_url.strip()
        if run_scraped_at is not None:
            source["scraped_at"] = run_scraped_at

    description = ensure_display_html(payload.get("description"))
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
        location["country"] = _country_with_indonesia_default(
            source_platform=prompt_input.source_platform,
            country=location.get("country"),
            city=location.get("city"),
            region=location.get("region"),
            display=location.get("display"),
        )

    payload["work_type"] = default_work_type(payload.get("work_type"))
    payload["employment_types"] = default_employment_types(payload.get("employment_types"))
    payload["experience_level"] = infer_experience_level(
        explicit=payload.get("experience_level"),
        title=payload.get("title"),
        description=_normalize_text(payload.get("description")),
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
        payload["description"] = text_to_display_html(
            build_source_limited_summary(
                title=payload.get("title"),
                company=company.get("name") if isinstance(company, dict) else None,
                location=location_display,
                source_platform=prompt_input.source_platform.value,
                output_language=prompt_input.output_language,
            )
        )

    if run_scraped_at is not None:
        payload["last_seen_at"] = run_scraped_at

    payload = _apply_quality_guards(payload, prompt_input=prompt_input)
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
    cleaned_value = _remove_visual_noise(value)
    if _HTML_LIKE_PATTERN.search(value):
        return clean_text(_remove_visual_noise(html_to_text(cleaned_value)))
    return clean_text(cleaned_value)


def _remove_visual_noise(value: str) -> str:
    # Remove emoji/dingbat-like symbols and normalize decorative bullets.
    cleaned = _VISUAL_NOISE_PATTERN.sub(" ", value)
    cleaned = _INVISIBLE_NOISE_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("•", " ").replace("▪", " ").replace("◦", " ")
    return cleaned


def _apply_quality_guards(
    payload: dict[str, Any],
    *,
    prompt_input: AINormalizationPromptInput,
) -> dict[str, Any]:
    description_text = _normalize_text(payload.get("description"))
    requirements_text = _normalize_text(payload.get("requirements"))
    skills = payload.get("skills")
    current_skills = (
        [item for item in skills if isinstance(item, str) and item.strip()]
        if isinstance(skills, list)
        else []
    )
    evidence_description, evidence_requirements, evidence_skills = _evidence_from_raw_payload(
        prompt_input.raw_payload_subset
    )

    if description_text is None:
        generated_description = _build_description_from_evidence(
            payload=payload,
            evidence_description=evidence_description,
            evidence_requirements=evidence_requirements,
            evidence_skills=evidence_skills,
            output_language=prompt_input.output_language,
        )
        if generated_description:
            payload["description"] = generated_description
    if requirements_text is None and evidence_requirements:
        payload["requirements"] = evidence_requirements
    if not current_skills and evidence_skills:
        payload["skills"] = evidence_skills
    return payload


def _evidence_from_raw_payload(
    raw_payload_subset: dict[str, Any],
) -> tuple[str | None, str | None, list[str]]:
    description_candidates: list[str] = []
    requirement_candidates: list[str] = []
    skill_candidates: list[str] = []
    _collect_evidence_strings(
        value=raw_payload_subset.get("payload", raw_payload_subset),
        description_candidates=description_candidates,
        requirement_candidates=requirement_candidates,
        skill_candidates=skill_candidates,
    )
    description = _best_description_text(description_candidates)
    requirements = _best_requirement_text(requirement_candidates)
    skills = _dedupe_texts(skill_candidates)
    if not skills:
        skills = _derive_skills_from_text(
            [text for text in (requirements, description) if isinstance(text, str)]
        )
    skills = skills[:20]
    return description, requirements, skills


def _collect_evidence_strings(
    *,
    value: Any,
    description_candidates: list[str],
    requirement_candidates: list[str],
    skill_candidates: list[str],
    parent_key: str | None = None,
    description_mode: bool = False,
    requirement_mode: bool = False,
    skill_mode: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.casefold()
            next_description_mode = description_mode or lowered in _DESCRIPTION_KEYS
            next_requirement_mode = requirement_mode or lowered in _REQUIREMENT_KEYS
            next_skill_mode = skill_mode or lowered in _SKILL_LIST_KEYS
            _collect_evidence_strings(
                value=item,
                description_candidates=description_candidates,
                requirement_candidates=requirement_candidates,
                skill_candidates=skill_candidates,
                parent_key=lowered,
                description_mode=next_description_mode,
                requirement_mode=next_requirement_mode,
                skill_mode=next_skill_mode,
            )
        return

    if isinstance(value, list):
        for item in value:
            _collect_evidence_strings(
                value=item,
                description_candidates=description_candidates,
                requirement_candidates=requirement_candidates,
                skill_candidates=skill_candidates,
                parent_key=parent_key,
                description_mode=description_mode,
                requirement_mode=requirement_mode,
                skill_mode=skill_mode,
            )
        return

    if not isinstance(value, str):
        return

    text = _normalize_text(value)
    if text is None or len(text) < 2:
        return

    key = parent_key or ""
    if description_mode or key in _DESCRIPTION_KEYS:
        description_candidates.append(text)
    if requirement_mode or key in _REQUIREMENT_KEYS:
        requirement_candidates.append(text)
    if (skill_mode or key in _SKILL_LIST_KEYS) and len(text) <= 80:
        skill_candidates.append(text)


def _best_description_text(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    sorted_candidates = sorted(candidates, key=len, reverse=True)
    return sorted_candidates[0]


def _best_requirement_text(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    # Prefer richer requirement-like text when multiple candidates are present.
    filtered = [
        candidate for candidate in candidates if not _BENEFIT_NOISE_PATTERN.search(candidate)
    ]
    sorted_candidates = sorted(filtered or candidates, key=len, reverse=True)
    return sorted_candidates[0]


def _build_description_from_evidence(
    *,
    payload: dict[str, Any],
    evidence_description: str | None,
    evidence_requirements: str | None,
    evidence_skills: list[str],
    output_language: str = "english",
) -> str | None:
    if evidence_description:
        return evidence_description

    title = _normalize_text(payload.get("title"))
    company = None
    company_value = payload.get("company")
    if isinstance(company_value, dict):
        company = _normalize_text(company_value.get("name"))

    if title is None:
        return None
    language = _normalize_output_language(output_language)
    if language == "english":
        company_text = company or "the related company"
        sentences = [
            (
                f"The {title} role at {company_text} focuses on carrying out core "
                "responsibilities supported by the available source evidence."
            )
        ]
        if evidence_requirements:
            sentences.append(f"Core qualifications include: {evidence_requirements}")
        elif evidence_skills:
            sentences.append(f"Required skills include: {', '.join(evidence_skills[:8])}.")
        return " ".join(sentences)

    company_text = company or "perusahaan terkait"
    sentences = [
        (
            f"Posisi {title} di {company_text} berfokus pada pelaksanaan tanggung jawab "
            "teknis sesuai kebutuhan bisnis."
        )
    ]
    if evidence_requirements:
        sentences.append(f"Kualifikasi inti mencakup: {evidence_requirements}")
    elif evidence_skills:
        sentences.append(f"Keahlian yang dibutuhkan antara lain: {', '.join(evidence_skills[:8])}.")
    return " ".join(sentences)


def _dedupe_texts(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _derive_skills_from_text(texts: list[str]) -> list[str]:
    extracted: list[str] = []
    for text in texts:
        normalized = _normalize_text(text)
        if normalized is None:
            continue
        for match in _TECH_TOKEN_PATTERN.findall(normalized):
            candidate = _canonical_skill_name(match)
            if candidate:
                extracted.append(candidate)
    return _dedupe_texts(extracted)


def _canonical_skill_name(raw: str) -> str | None:
    normalized = re.sub(r"\s+", " ", raw.strip().casefold())
    return _TECH_CANONICAL_MAP.get(normalized)


def _country_with_indonesia_default(
    *,
    source_platform: SourcePlatform,
    country: Any,
    city: Any,
    region: Any,
    display: Any,
) -> str | None:
    country_text = _normalize_text(country)
    if country_text:
        return country_text
    if source_platform not in {
        SourcePlatform.DEALLS,
        SourcePlatform.GLINTS,
        SourcePlatform.JOBSTREET,
        SourcePlatform.KALIBRR,
        SourcePlatform.KITALULUS,
    }:
        return None
    joined = " ".join(
        item
        for item in (
            _normalize_text(city),
            _normalize_text(region),
            _normalize_text(display),
        )
        if item
    ).casefold()
    if not joined:
        return "Indonesia"
    if any(hint in joined for hint in _FOREIGN_COUNTRY_HINTS):
        return None
    return "Indonesia"


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


def _build_ai_normalization_system_prompt(output_language: str) -> str:
    language = _normalize_output_language(output_language)
    language_name = _language_display_name(language)
    native_name = _language_native_name(language)
    natural_name = _natural_language_name(language)
    source_preservation = (
        "Translate non-English source evidence into English."
        " Preserve source language only for non-translatable proper nouns, acronyms, "
        "or legal entity names."
        if language == "english"
        else "Avoid English paraphrase unless direct verbatim source evidence is intentionally "
        "preserved."
    )
    meta_example = (
        '"This description has been rewritten in English."'
        if language == "english"
        else '"Deskripsi peran ini disusun ulang dalam Bahasa Indonesia."'
    )
    return f"""You are a strict job data normalizer.
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
6. Normalize display content into sanitized semantic HTML.
   Allowed tags: <p>, <ul>, <ol>, <li>, <strong>, <em>, <br>.
   Never output attributes, scripts, styles, inline URLs, or event handlers.
7. Parse salary numbers only when confidence is high. Keep uncertain numeric salary values null.
8. Map location into display, city, region, and country when evidence exists.
   City/province resolution is open-world (not whitelist-based).
   Use reliable geographic reasoning when source fields are ambiguous.
   Indonesia-first context: when city/province evidence is clearly Indonesian,
   set country to Indonesia unless source explicitly states otherwise.
9. Keep Glints list records partial when detail data is unavailable.
   Use factual source-limited description summary; never invent official detail content.
10. external_apply_url must fall back to source_url when missing.
11. Prefer explicit defaults aligned with backendSchemaContext default policy.
12. Keep unknown values null instead of placeholders such as '-', 'N/A', or 'unknown text'.
13. Instruction language in this prompt is English.
14. Required output language for this run is {language_name}.
    Use {language_name} only for generated/paraphrased human-readable fields.
    For English mode, never emit Indonesian function words
    such as: dan, untuk, dengan, dari, yang, minimal, pengalaman.
15. Generated or normalized human-readable output must be concise {natural_name}.
16. When requirement or skill evidence exists in source data,
    avoid empty requirements/skills output.
17. Keep generated requirement text factual, short, and ready for downstream requirement extraction.
18. Keep generated/paraphrased human-readable fields in {language_name}.
    {source_preservation}
    Never produce mixed-language phrases in generated output.
19. salary.display consistency rule:
    when salary min/max values are present, salary display must not be placeholder text.
20. Description writing standard:
    - write concise, useful, and professional {language_name} prose;
    - when detail.description is missing but detail.responsibilities exists (common in Dealls),
      build description from responsibilities without hallucination;
    - avoid one-line vague text; include role focus and execution context when evidence allows.
21. Final quality check before output:
    - if evidence exists for requirements, requirements must not be empty;
    - if evidence exists for skills, skills must not be empty;
    - generated prose must be {native_name};
    - location should keep Indonesia context when evidence is Indonesian;
    - avoid icons, emoji, and decorative symbols in human-readable fields.
    - never include meta process statements such as
      {meta_example}
22. Field-specific output standards:
    - description: safe display HTML with 2-5 short {language_name} paragraphs
      or paragraph+list when evidence supports it;
    - requirement_summary display (derived downstream): do not use fixed label prefixes;
    - requirements: plain factual {language_name} text for downstream atomic extraction;
    - skills: specific technology/domain terms only, deduplicated, no generic filler.
      Split composite entries (for example "HTML, CSS, PHP") into atomic skill items.
23. Minimum coverage rule for sync completeness:
    - produce at least one requirement and one skill when role evidence exists
      even if detail payload is sparse.
24. Requirement extraction rule:
    - write requirements as atomic statements ready for typed downstream rows;
    - separate education, experience, skill/tool, and responsibility evidence;
    - never include benefit or compensation noise such as THR, tunjangan,
      benefit, fasilitas, bonus, cuti, BPJS, or gaji pokok.
"""


AI_NORMALIZATION_SYSTEM_PROMPT = _build_ai_normalization_system_prompt("english")


def _build_ai_normalization_batch_system_prompt(output_language: str) -> str:
    language = _normalize_output_language(output_language)
    language_name = _language_display_name(language)
    return f"""You are a strict job data normalizer for batch processing.
Return JSON object only in shape {{"results":[...]}}.
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
9. Instruction language is English, while generated/paraphrased prose output
   must be {language_name}.
10. Required output language for this run is {language_name}.
    Do not output generated/paraphrased prose in other languages.
    For English mode, never emit Indonesian function words
    such as: dan, untuk, dengan, dari, yang, minimal, pengalaman.
11. When evidence for requirements or skills exists, do not return both as empty.
12. When salary min/max are present, avoid placeholder salary display text.
13. For Dealls-like payloads, use responsibilities as description evidence
    when description is missing.
14. Avoid icons, emoji, and decorative symbols in human-readable fields.
15. Description output should be sanitized semantic display HTML.
    Requirements output should stay concise plain text in {language_name}.
16. Keep skills specific and deduplicated; avoid generic filler skills.
    Split composite skills into atomic items.
17. Keep minimum one requirement and one skill when role evidence is present.
18. Requirements must be atomic, typed-ready statements for SKILL, EXPERIENCE,
    EDUCATION, RESPONSIBILITY, or OTHER downstream rows.
19. Exclude benefit and compensation noise from requirements, including THR,
    tunjangan, benefit, fasilitas, bonus, cuti, BPJS, and gaji pokok.
20. Never include meta process statements in description/requirements fields
    (for example "deskripsi disusun ulang" style disclaimers).
21. For Glints list-only records, keep requirements conservative and transparent
    because official detail text is unavailable.
"""


AI_NORMALIZATION_BATCH_SYSTEM_PROMPT = _build_ai_normalization_batch_system_prompt("english")


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
    "completenessPolicy": {
        "requirementsAndSkills": (
            "if source evidence exists for requirements or skills, "
            "output should not be empty for both"
        ),
        "preferFactualCoverageOverNulls": True,
        "minimumRelationCoverage": {
            "requirementsMinItemsWhenRoleEvidenceExists": 1,
            "skillsMinItemsWhenRoleEvidenceExists": 1,
        },
    },
    "atomicTypedRequirementExtraction": {
        "target": "downstream requirements[] rows",
        "rules": [
            "write requirements as separable atomic statements",
            "one requirement should express one qualification, skill, education, "
            "experience, or responsibility",
            "avoid combined paragraphs that mix benefits, duties, and qualifications",
            "benefits and compensation are never requirements",
        ],
        "allowedTypes": ["SKILL", "EXPERIENCE", "EDUCATION", "RESPONSIBILITY", "OTHER"],
        "typeGuidance": {
            "SKILL": "tools, technologies, domain competencies, or explicit skill tags",
            "EXPERIENCE": "years of experience, seniority, fresh graduate eligibility",
            "EDUCATION": "degree, diploma, major, or education-level evidence",
            "RESPONSIBILITY": "job duties and work ownership evidence",
            "OTHER": "only when evidence is useful but not classifiable",
        },
        "noiseExclusions": [
            "THR",
            "tunjangan",
            "benefit",
            "fasilitas",
            "bonus",
            "cuti",
            "BPJS",
            "gaji pokok",
        ],
        "sourceEvidencePolicy": (
            "prefer explicit requirement, qualification, skillTags, responsibilities, "
            "and detail text evidence"
        ),
        "weakEvidencePolicy": "lower confidence or skip; do not create generic OTHER filler",
        "glintsSourceLimitedPolicy": (
            "for Glints list-only records, derive only conservative requirements "
            "from list evidence "
            "and never invent official detail text"
        ),
    },
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
        "countryPreference": "Indonesia when evidence indicates Indonesian geography",
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
    "languagePolicy": {
        "instructionLanguage": "English",
        "outputLanguage": "Indonesian",
        "generatedProse": "Indonesian",
        "appliesTo": [
            "description_generated",
            "requirements_generated",
            "requirement_summary_generated",
            "presentation_labels_generated",
        ],
        "notes": [
            "keep source-native proper nouns and technology names",
            "if text is copied verbatim from source evidence, preserve source language",
            "do not paraphrase generated prose in English",
        ],
    },
    "contentStructurePolicy": {
        "safeDisplayHtmlTags": ["p", "ul", "ol", "li", "strong", "em", "br"],
        "description": {
            "goal": "safe display HTML role overview in natural Indonesian",
            "lengthGuidance": "2-5 short paragraphs or paragraph+list; avoid vague one-liners",
            "mustIncludeWhenEvidenceExists": [
                "role focus or core responsibilities",
                "execution context (product/system/team/process)",
            ],
            "mustAvoid": [
                "claims not supported by source evidence",
                "empty boilerplate wording",
                "raw source HTML",
                "unsafe HTML tags or attributes",
            ],
        },
        "requirementSummary": {
            "goal": "display-ready summary of key qualifications",
            "style": "professional, concise, factual Indonesian in safe HTML paragraph/list",
            "prefixRule": "do not use fixed prefixes like 'Kualifikasi utama:'",
            "mustIncludeWhenEvidenceExists": [
                "experience",
                "core competencies",
            ],
            "shapeGuidance": "one short paragraph or <ul><li>...</li></ul> with 3-6 items",
        },
        "requirements": {
            "goal": "clean requirement text for downstream extraction",
            "style": "factual, non-fabricated plain text, no raw HTML",
            "normalizationHints": [
                "split bullet-like evidence into atomic statements",
                "group education, experience, skill, and responsibility evidence clearly",
                "remove duplicate sentences",
                "convert fragmented bullets into readable sentences",
                "exclude benefit and compensation text",
            ],
        },
        "skills": {
            "goal": "actionable, specific skill list",
            "rules": [
                "use technology/domain terms explicitly present in source",
                "dedupe case-insensitive",
                "avoid overly generic skills without direct evidence",
                "split composite skills into atomic items",
            ],
        },
        "cleanPresentation": {
            "rule": "no icons, emoji, decorative symbols, or noisy visual markers",
            "appliesTo": [
                "description",
                "requirementSummary",
                "requirements",
                "skills",
            ],
            "metaStatementRule": (
                "never include process/disclaimer text about rewriting or translation"
            ),
        },
    },
    "salaryPresentationPolicy": {
        "placeholderDisallowedWhenNumericExists": True,
        "allowedPlaceholdersOnlyWhenNoNumericEvidence": ["Tidak dicantumkan"],
    },
    "finalQualityChecklist": [
        "description should be informative and not vague one-liner when evidence exists",
        "description is safe semantic display HTML with allowlisted tags only",
        "requirement summary display must not start with a fixed prefix label",
        "requirements non-empty when evidence exists",
        "skills non-empty when evidence exists",
        "requirements split cleanly into atomic downstream rows",
        "requirements do not include benefit or compensation noise",
        "generated prose in Bahasa Indonesia",
        "salary display non-placeholder when numeric salary exists",
        "Indonesia context preserved when geography evidence is Indonesian",
        "description/requirement_summary/requirements/skills contain no icon or emoji noise",
        "description/requirements/skills contain no rewrite/translation disclaimer text",
    ],
}


def _completion_policy(output_language: str) -> dict[str, Any]:
    language = _normalize_output_language(output_language)
    language_name = _language_display_name(language)
    native_name = _language_native_name(language)
    natural_name = _natural_language_name(language)
    policy = deepcopy(COMPLETION_POLICY)
    if language == "english":
        language_notes = [
            "translate Indonesian or mixed-language evidence into natural English prose",
            (
                "never output Indonesian function words in generated prose "
                "(for example: dan, untuk, dengan, dari, yang, minimal, pengalaman)"
            ),
            "keep source-native proper nouns, acronyms, and technology names only",
            "never mix English and Indonesian in one generated sentence",
            "do not include rewrite or translation disclaimers",
        ]
    else:
        language_notes = [
            "keep source-native proper nouns and technology names",
            "if text is copied verbatim from source evidence, preserve source language",
            f"do not paraphrase generated prose outside {language_name}",
            "do not include rewrite or translation disclaimers",
        ]
    policy["languagePolicy"] = {
        "instructionLanguage": "English",
        "outputLanguage": language_name,
        "generatedProse": language_name,
        "appliesTo": [
            "description_generated",
            "requirements_generated",
            "requirement_summary_generated",
            "presentation_labels_generated",
            "warnings_generated",
        ],
        "notes": language_notes,
    }
    content_policy = policy["contentStructurePolicy"]
    content_policy["description"]["goal"] = f"safe display HTML role overview in {natural_name}"
    content_policy["description"]["mustAvoid"].extend(
        [
            "translation disclaimers",
            "language-mixed generated sentences",
        ]
    )
    content_policy["requirementSummary"]["style"] = (
        f"professional, concise, factual {language_name} in safe HTML paragraph/list"
    )
    content_policy["requirements"]["style"] = (
        f"factual, non-fabricated plain {language_name} text, no raw HTML"
    )
    content_policy["cleanPresentation"]["languageRule"] = (
        f"description, requirementSummary, requirements, and warnings must use {language_name}"
    )
    if language == "english":
        policy["salaryPresentationPolicy"]["allowedPlaceholdersOnlyWhenNoNumericEvidence"] = [
            "Not specified"
        ]
    policy["finalQualityChecklist"] = [
        (
            f"generated prose in {native_name}"
            if item == "generated prose in Bahasa Indonesia"
            else item
        )
        for item in policy["finalQualityChecklist"]
    ]
    return policy


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
        "description": (
            "<p>Posisi Programmer di Gamma Persada berfokus pada pengembangan sistem aplikasi "
            "dan peningkatan stabilitas layanan.</p>"
        ),
        "requirements": (
            "Memiliki pengalaman relevan dalam pengembangan perangkat lunak, "
            "mampu bekerja kolaboratif, dan memahami praktik coding yang baik."
        ),
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
        "description": (
            "<p>Posisi Backend Engineer berfokus pada pengembangan dan pemeliharaan API, "
            "pipeline data, serta peningkatan keandalan layanan backend.</p>"
            "<ul><li>Berkoordinasi lintas tim produk dan infrastruktur.</li></ul>"
        ),
        "requirements": (
            "Memiliki pengalaman backend minimal 3 tahun, "
            "menguasai Python dan SQL, serta memahami layanan cloud."
        ),
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


def _normalization_output_examples(output_language: str) -> dict[str, Any]:
    language = _normalize_output_language(output_language)
    examples = deepcopy(NORMALIZATION_OUTPUT_EXAMPLES)
    if language != "english":
        return examples

    examples["listRecordExample"]["description"] = (
        "<p>The Programmer role at Gamma Persada focuses on application system "
        "development and service stability improvements.</p>"
    )
    examples["listRecordExample"]["requirements"] = (
        "Has relevant experience in software development, can collaborate well, "
        "and understands good coding practices."
    )
    examples["listRecordExample"]["salary"]["display"] = "IDR 8,000,000 - 10,000,000 / month"
    examples["listRecordExample"]["presentation"]["salary_label"] = (
        "IDR 8,000,000 - 10,000,000 / month"
    )
    examples["detailRecordExample"]["description"] = (
        "<p>The Backend Engineer role focuses on developing and maintaining APIs, "
        "data pipelines, and backend service reliability.</p>"
        "<ul><li>Coordinates across product and infrastructure teams.</li></ul>"
    )
    examples["detailRecordExample"]["requirements"] = (
        "Has at least 3 years of backend experience, understands Python and SQL, "
        "and has knowledge of cloud services."
    )
    examples["detailRecordExample"]["salary"]["display"] = "IDR 12,000,000 - 18,000,000 / month"
    examples["detailRecordExample"]["presentation"]["salary_label"] = (
        "IDR 12,000,000 - 18,000,000 / month"
    )
    return examples
