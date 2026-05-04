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
Return a single JSON object that must match the provided JSON schema exactly.
Rules:
1. Use only facts from rawPayloadSubset. Never invent or infer unsupported facts.
2. Output JSON only. No prose, markdown, comments, or extra keys.
3. Normalize HTML fields into safe plain text while preserving meaning.
4. Parse salary numbers only when confidence is high. Keep uncertain numeric salary values null.
5. Map location into display, city, region, and country when present in source.
6. Keep Glints list records partial when detail data is unavailable.
   Do not create description or requirement text.
7. Set external_apply_url to source_url when source apply URL is missing.
8. Keep null for unknown values instead of placeholders.
"""


AI_NORMALIZATION_REPAIR_SYSTEM_PROMPT = """Fix JSON format only.
Do not add, remove, or alter any semantic values.
Only return one corrected JSON object that matches the given schema."""
