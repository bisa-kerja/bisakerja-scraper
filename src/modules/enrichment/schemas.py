from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1)]
SECRET_LIKE_PATTERN = re.compile(
    r"(authorization|bearer|cookie|csrf|token|secret|credential|password|session|"
    r"visitor|device|raw_payload|raw payload|database_url|db_url)",
    re.IGNORECASE,
)
WORD_PATTERN = re.compile(r"[a-z0-9+#.]+", re.IGNORECASE)


class RequirementType(StrEnum):
    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    OTHER = "OTHER"


class EnrichmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class EnrichmentJobInput(EnrichmentModel):
    title: NonEmptyStr
    description: str | None = None
    requirements: str | None = None
    company: NonEmptyStr
    source: NonEmptyStr

    @field_validator("title", "description", "requirements", "company", "source")
    @classmethod
    def reject_secret_like_text(cls, value: str | None) -> str | None:
        if value is not None and SECRET_LIKE_PATTERN.search(value):
            raise ValueError("AI enrichment input must not contain secret-like or raw payload text")
        return value

    def clean_text(self) -> str:
        return "\n".join(
            part
            for part in (
                self.title,
                self.description,
                self.requirements,
                self.company,
                self.source,
            )
            if part
        )


class EnrichedSkill(EnrichmentModel):
    name: NonEmptyStr
    confidence: float = Field(ge=0, le=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class EnrichedRequirement(EnrichmentModel):
    type: RequirementType
    value: NonEmptyStr
    confidence: float = Field(ge=0, le=1)

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        return value.strip()


class EnrichmentOutput(EnrichmentModel):
    skills: list[EnrichedSkill] = Field(default_factory=list)
    requirements: list[EnrichedRequirement] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def deduplicate_items(self) -> EnrichmentOutput:
        self.skills = dedupe_by_key(self.skills, lambda skill: skill.name.casefold())
        self.requirements = dedupe_by_key(
            self.requirements,
            lambda requirement: (requirement.type.value, requirement.value.casefold()),
        )
        return self


class EnrichmentValidationError(ValueError):
    pass


def validate_enrichment_output(
    output: EnrichmentOutput,
    *,
    source_text: str,
) -> EnrichmentOutput:
    normalized_source = normalize_text(source_text)
    unsupported: list[str] = []

    for skill in output.skills:
        if not is_supported_by_source(skill.name, normalized_source):
            unsupported.append(f"skill:{skill.name}")

    for requirement in output.requirements:
        if not is_supported_by_source(requirement.value, normalized_source):
            unsupported.append(f"requirement:{requirement.value}")

    if unsupported:
        raise EnrichmentValidationError(
            "AI enrichment output contains unsupported facts: " + ", ".join(unsupported)
        )
    return output


def is_supported_by_source(value: str, normalized_source: str) -> bool:
    normalized_value = normalize_text(value)
    if not normalized_value:
        return False
    if normalized_value in normalized_source:
        return True
    tokens = [token for token in WORD_PATTERN.findall(normalized_value) if len(token) >= 2]
    if not tokens:
        return False
    return all(token in normalized_source for token in tokens)


def normalize_text(value: str) -> str:
    return " ".join(WORD_PATTERN.findall(value.casefold()))


def dedupe_by_key[T](items: list[T], key_fn) -> list[T]:  # noqa: ANN001
    seen: set[object] = set()
    deduped: list[T] = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
