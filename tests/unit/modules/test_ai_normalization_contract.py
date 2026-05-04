from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from modules.jobs import (
    AINormalizationContractError,
    AINormalizationPromptInput,
    NormalizationEndpointType,
    SourcePlatform,
    build_ai_normalization_format_repair_messages,
    build_ai_normalization_messages,
    validate_ai_normalization_output,
)

FIXTURE_ROOT = Path("tests/fixtures/normalization_golden")


def test_golden_outputs_validate_against_canonical_contract() -> None:
    fixtures = sorted(FIXTURE_ROOT.glob("*.json"))
    assert fixtures

    for fixture_path in fixtures:
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        for scenario in document["scenarios"]:
            prompt_input = AINormalizationPromptInput(
                source_platform=document["sourcePlatform"],
                endpoint_type=scenario["endpointType"],
                raw_payload_subset=scenario["rawPayloadSubset"],
            )

            normalized = validate_ai_normalization_output(
                scenario["aiOutput"],
                prompt_input=prompt_input,
            )

            assert normalized.source.external_apply_url
            assert (
                normalized.source.external_apply_url == normalized.source.source_url
                or isinstance(normalized.source.external_apply_url, str)
            )
            if scenario["name"] == "detail-html-and-salary":
                assert (
                    normalized.description
                    == "Build and maintain frontend dashboards for business operations"
                )
                assert (
                    normalized.requirements == "Minimum 3 years of experience as Frontend Engineer"
                )
                assert normalized.salary is not None
                assert normalized.salary.currency == "IDR"
                assert normalized.salary.period.value == "monthly"
            if scenario["name"] == "list-relative-label-and-salary-range":
                assert normalized.salary is not None
                assert normalized.salary.min_amount == 8000000
                assert normalized.salary.max_amount == 10000000
                assert normalized.salary.currency == "IDR"
                assert normalized.salary.period.value == "monthly"
            if scenario["name"] == "detail-html-and-uncertain-salary":
                assert normalized.salary is not None
                assert normalized.salary.min_amount is None
                assert normalized.salary.max_amount is None
            if scenario["name"] == "list-with-embedded-detail-html":
                assert (
                    normalized.description
                    == "Revenue Ownership Take full ownership of revenue targets."
                )
                assert normalized.requirements == "Bachelor's degree in Business."
                assert normalized.location.display == "North Jakarta, DKI Jakarta, Indonesia"


def test_glints_list_contract_rejects_invented_detail_fields() -> None:
    fixture = json.loads((FIXTURE_ROOT / "glints.json").read_text(encoding="utf-8"))
    scenario = fixture["scenarios"][0]
    bad_output: dict[str, Any] = dict(scenario["aiOutput"])
    bad_output["description"] = "Invented detail text"

    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.GLINTS,
        endpoint_type=NormalizationEndpointType.LIST,
        raw_payload_subset=scenario["rawPayloadSubset"],
    )

    with pytest.raises(AINormalizationContractError, match="must not invent detail fields"):
        validate_ai_normalization_output(bad_output, prompt_input=prompt_input)


def test_prompt_contract_includes_schema_and_strict_rules() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.DEALLS,
        endpoint_type=NormalizationEndpointType.DETAIL,
        raw_payload_subset={"id": "job-1", "title": "Backend Engineer"},
    )

    messages = build_ai_normalization_messages(prompt_input)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "strict job data normalizer" in messages[0]["content"].lower()
    assert "output json only" in messages[0]["content"].lower()
    assert "backendschemacontext" in messages[0]["content"].lower()

    payload = json.loads(messages[1]["content"])
    assert payload["sourcePlatform"] == "dealls"
    assert payload["endpointType"] == "detail"
    assert payload["targetSchema"] == "CanonicalJobSchema"
    assert "targetJsonSchema" in payload
    assert "rawPayloadSubset" in payload
    assert "backendSchemaContext" in payload
    assert "normalizationObjectives" in payload
    assert "standaloneSchemaBlueprint" in payload
    assert "normalizationOutputExamples" in payload
    assert "backend-references/prisma/schema.prisma" not in json.dumps(payload)
    assert (
        payload["backendSchemaContext"]["reference"]["source"]
        == "standalone embedded backend schema contract snapshot"
    )
    assert payload["backendSchemaContext"]["reference"]["externalDependencyAllowed"] is False
    assert (
        payload["standaloneSchemaBlueprint"]["canonicalOutputModel"]["source"][
            "external_apply_url"
        ]["defaultRule"]
        == "fallback_to_source_url_when_missing"
    )
    assert payload["normalizationOutputExamples"]["detailRecordExample"]["source"][
        "external_apply_url"
    ]
    assert payload["backendSchemaContext"]["targetModels"]["JobListing"]["defaultPolicy"] == {
        "salaryCurrency": "IDR",
        "status": "ACTIVE",
        "externalApplyUrlFallback": "sourceUrl",
    }


def test_repair_prompt_only_targets_format_errors() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.JOBSTREET,
        endpoint_type=NormalizationEndpointType.LIST,
        raw_payload_subset={"id": "91789576"},
    )
    messages = build_ai_normalization_format_repair_messages(
        prompt_input=prompt_input,
        invalid_output='{"source":{"platform":"jobstreet"',
        validation_errors=[{"loc": ["source"], "msg": "missing"}],
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Fix JSON format only." in messages[0]["content"]

    payload = json.loads(messages[1]["content"])
    assert payload["sourcePlatform"] == "jobstreet"
    assert payload["endpointType"] == "list"
    assert payload["validationErrors"][0]["loc"] == ["source"]
    assert "backend-references/prisma/schema.prisma" not in json.dumps(payload)
    assert "standaloneSchemaBlueprint" in payload
    assert payload["backendSchemaContext"]["targetModels"]["Company"]["required"] == ["name"]
