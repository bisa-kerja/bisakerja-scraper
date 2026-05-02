import pytest
from pydantic import ValidationError

from modules.enrichment import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentJobInput,
    EnrichmentOutput,
    EnrichmentValidationError,
    RequirementType,
    validate_enrichment_output,
)


def test_enrichment_output_accepts_valid_supported_facts() -> None:
    job = make_job_input()
    output = EnrichmentOutput(
        skills=[EnrichedSkill(name="Python", confidence=0.9)],
        requirements=[
            EnrichedRequirement(
                type=RequirementType.EXPERIENCE,
                value="3 years backend experience",
                confidence=0.8,
            )
        ],
        confidence=0.85,
        warnings=[],
    )

    validated = validate_enrichment_output(output, source_text=job.clean_text())

    assert validated.skills[0].name == "Python"


def test_enrichment_output_rejects_unsupported_facts() -> None:
    job = make_job_input()
    output = EnrichmentOutput(
        skills=[EnrichedSkill(name="Kubernetes", confidence=0.9)],
        requirements=[],
        confidence=0.8,
        warnings=[],
    )

    with pytest.raises(EnrichmentValidationError, match="unsupported facts"):
        validate_enrichment_output(output, source_text=job.clean_text())


def test_enrichment_output_rejects_wrong_requirement_type() -> None:
    with pytest.raises(ValidationError, match="type"):
        EnrichmentOutput(
            skills=[],
            requirements=[
                {
                    "type": "LOCATION",
                    "value": "Jakarta",
                    "confidence": 0.5,
                }
            ],
            confidence=0.5,
            warnings=[],
        )


def test_enrichment_input_rejects_secret_like_text() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        EnrichmentJobInput(
            title="Backend Engineer",
            description="Authorization: Bearer secret-token",
            requirements="Python",
            company="Bisakerja",
            source="dealls",
        )


def make_job_input() -> EnrichmentJobInput:
    return EnrichmentJobInput(
        title="Backend Engineer",
        description="Build APIs with Python and PostgreSQL.",
        requirements="3 years backend experience.",
        company="Bisakerja",
        source="dealls",
    )
