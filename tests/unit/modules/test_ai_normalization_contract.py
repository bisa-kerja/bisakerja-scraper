from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from modules.jobs import (
    AINormalizationBatchPromptInput,
    AINormalizationBatchPromptItem,
    AINormalizationContractError,
    AINormalizationPromptInput,
    NormalizationEndpointType,
    SourcePlatform,
    build_ai_normalization_batch_messages,
    build_ai_normalization_format_repair_messages,
    build_ai_normalization_messages,
    validate_ai_normalization_batch_output,
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
                    == "<p>Build and maintain frontend dashboards for business operations</p>"
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
                assert normalized.description is not None
                assert "Revenue Ownership" in normalized.description
                assert "<strong>" in normalized.description or "<ul>" in normalized.description
                assert normalized.requirements == "Bachelor's degree in Business."
                assert normalized.location.display == "North Jakarta, DKI Jakarta, Indonesia"


def test_glints_list_contract_builds_source_limited_summary_when_detail_unavailable() -> None:
    fixture = json.loads((FIXTURE_ROOT / "glints.json").read_text(encoding="utf-8"))
    scenario = fixture["scenarios"][0]
    bad_output: dict[str, Any] = dict(scenario["aiOutput"])
    bad_output["description"] = None

    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.GLINTS,
        endpoint_type=NormalizationEndpointType.LIST,
        raw_payload_subset=scenario["rawPayloadSubset"],
    )

    normalized = validate_ai_normalization_output(bad_output, prompt_input=prompt_input)
    assert normalized.description is not None
    assert "level listing" in normalized.description


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
    assert payload["outputLanguage"] == "indonesian"
    assert payload["outputLanguagePolicy"]["name"] == "Indonesian"
    assert payload["targetSchema"] == "CanonicalJobSchema"
    assert "targetJsonSchema" in payload
    assert "rawPayloadSubset" in payload
    assert "backendSchemaContext" in payload
    assert "normalizationObjectives" in payload
    assert "standaloneSchemaBlueprint" in payload
    assert "normalizationOutputExamples" in payload
    assert payload["sourceContext"]["detailCapability"] == "available"
    assert "completionPolicy" in payload
    assert payload["completionPolicy"]["locationResolutionPolicy"]["openWorld"] is True
    assert payload["completionPolicy"]["locationResolutionPolicy"]["noStaticCityWhitelist"] is True
    assert (
        payload["completionPolicy"]["locationResolutionPolicy"]["countryPreference"]
        == "Indonesia when evidence indicates Indonesian geography"
    )
    assert payload["completionPolicy"]["languagePolicy"]["instructionLanguage"] == "English"
    assert payload["completionPolicy"]["languagePolicy"]["outputLanguage"] == "Indonesian"
    assert payload["completionPolicy"]["languagePolicy"]["generatedProse"] == "Indonesian"
    assert (
        payload["completionPolicy"]["completenessPolicy"]["preferFactualCoverageOverNulls"] is True
    )
    assert (
        payload["completionPolicy"]["completenessPolicy"]["minimumRelationCoverage"][
            "requirementsMinItemsWhenRoleEvidenceExists"
        ]
        == 1
    )
    assert (
        payload["completionPolicy"]["completenessPolicy"]["minimumRelationCoverage"][
            "skillsMinItemsWhenRoleEvidenceExists"
        ]
        == 1
    )
    assert payload["completionPolicy"]["salaryPresentationPolicy"][
        "placeholderDisallowedWhenNumericExists"
    ]
    assert "finalQualityChecklist" in payload["completionPolicy"]
    assert "atomicTypedRequirementExtraction" in payload["completionPolicy"]
    assert payload["completionPolicy"]["atomicTypedRequirementExtraction"]["allowedTypes"] == [
        "SKILL",
        "EXPERIENCE",
        "EDUCATION",
        "RESPONSIBILITY",
        "OTHER",
    ]
    assert (
        "THR" in payload["completionPolicy"]["atomicTypedRequirementExtraction"]["noiseExclusions"]
    )
    assert "contentStructurePolicy" in payload["completionPolicy"]
    assert (
        payload["completionPolicy"]["contentStructurePolicy"]["description"]["goal"]
        == "safe display HTML role overview in natural Indonesian"
    )
    assert payload["completionPolicy"]["contentStructurePolicy"]["safeDisplayHtmlTags"] == [
        "p",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "br",
    ]
    assert (
        payload["completionPolicy"]["contentStructurePolicy"]["requirementSummary"]["prefixRule"]
        == "do not use fixed prefixes like 'Kualifikasi utama:'"
    )
    assert (
        payload["completionPolicy"]["contentStructurePolicy"]["cleanPresentation"]["rule"]
        == "no icons, emoji, decorative symbols, or noisy visual markers"
    )
    assert (
        payload["completionPolicy"]["contentStructurePolicy"]["cleanPresentation"][
            "metaStatementRule"
        ]
        == "never include process/disclaimer text about rewriting or translation"
    )
    assert (
        "split composite skills into atomic items"
        in payload["completionPolicy"]["contentStructurePolicy"]["skills"]["rules"]
    )
    assert (
        "exclude benefit and compensation text"
        in payload["completionPolicy"]["contentStructurePolicy"]["requirements"][
            "normalizationHints"
        ]
    )
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


def test_prompt_contract_can_target_english_output() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.DEALLS,
        endpoint_type=NormalizationEndpointType.DETAIL,
        raw_payload_subset={"id": "job-1", "title": "Backend Engineer"},
        output_language="english",
    )

    messages = build_ai_normalization_messages(prompt_input)
    assert "generated prose must be English" in messages[0]["content"]
    assert "plain factual English text" in messages[0]["content"]

    payload = json.loads(messages[1]["content"])
    assert payload["outputLanguage"] == "english"
    assert payload["outputLanguagePolicy"]["name"] == "English"
    assert payload["completionPolicy"]["languagePolicy"]["outputLanguage"] == "English"
    assert (
        payload["completionPolicy"]["contentStructurePolicy"]["description"]["goal"]
        == "safe display HTML role overview in natural English"
    )
    assert (
        "The Backend Engineer role focuses"
        in payload["normalizationOutputExamples"]["detailRecordExample"]["description"]
    )


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


def test_batch_prompt_contract_includes_array_shape_and_identity_rules() -> None:
    prompt_input = AINormalizationBatchPromptInput(
        items=[
            AINormalizationBatchPromptItem(
                item_id="item-1",
                source_platform=SourcePlatform.DEALLS,
                endpoint_type=NormalizationEndpointType.DETAIL,
                raw_payload_subset={"id": "job-1", "title": "Backend Engineer"},
            )
        ]
    )

    messages = build_ai_normalization_batch_messages(prompt_input)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "batch processing" in messages[0]["content"].lower()
    payload = json.loads(messages[1]["content"])
    assert payload["inputItems"][0]["itemId"] == "item-1"
    assert payload["batchOutputPolicy"]["ordering"] == "must preserve inputItems order"
    assert "batchOutputJsonSchema" in payload


def test_batch_output_rejects_item_order_mismatch() -> None:
    prompt_input = AINormalizationBatchPromptInput(
        items=[
            AINormalizationBatchPromptItem(
                item_id="item-1",
                source_platform=SourcePlatform.DEALLS,
                endpoint_type=NormalizationEndpointType.DETAIL,
                raw_payload_subset={"id": "job-1", "title": "Backend Engineer"},
            )
        ]
    )

    with pytest.raises(AINormalizationContractError, match="preserve input item order"):
        validate_ai_normalization_batch_output(
            {
                "results": [
                    {
                        "itemId": "item-x",
                        "normalizedJob": {
                            "source": {
                                "platform": "dealls",
                                "external_job_id": "job-1",
                                "source_url": "https://example.test/job-1",
                                "external_apply_url": "https://example.test/job-1",
                                "scraped_at": "2026-05-05T00:00:00Z",
                                "source_updated_at": None,
                            },
                            "title": "Backend Engineer",
                            "company": {"name": "Bisakerja"},
                            "location": {"display": "Jakarta"},
                            "salary": None,
                            "employment_types": [],
                            "work_type": "unknown",
                            "description": None,
                            "requirements": None,
                            "skills": [],
                            "posted_at": None,
                            "last_seen_at": "2026-05-05T00:00:00Z",
                            "status": "active",
                            "presentation": {
                                "posted_label": None,
                                "salary_label": None,
                                "badges": [],
                                "source_labels": {},
                            },
                        },
                        "errorCode": None,
                        "errorMessage": None,
                    }
                ]
            },
            prompt_input=prompt_input,
        )


def test_quality_guard_backfills_requirements_and_skills_from_evidence() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.DEALLS,
        endpoint_type=NormalizationEndpointType.DETAIL,
        raw_payload_subset={
            "payload": {
                "requirements": "Minimal 2 tahun pengalaman backend dan memahami REST API.",
                "skills": ["Python", "PostgreSQL"],
            }
        },
    )
    output = {
        "source": {
            "platform": "dealls",
            "external_job_id": "job-123",
            "source_url": "https://dealls.com/jobs/job-123",
            "external_apply_url": "https://dealls.com/jobs/job-123",
            "scraped_at": "2026-05-06T00:00:00Z",
            "source_updated_at": None,
        },
        "title": "Backend Engineer",
        "company": {"name": "Bisakerja"},
        "location": {"display": "Jakarta"},
        "salary": None,
        "employment_types": [],
        "work_type": "unknown",
        "description": None,
        "requirements": None,
        "skills": [],
        "posted_at": None,
        "last_seen_at": "2026-05-06T00:00:00Z",
        "status": "active",
        "presentation": {
            "posted_label": None,
            "salary_label": None,
            "badges": [],
            "source_labels": {},
        },
    }
    normalized = validate_ai_normalization_output(output, prompt_input=prompt_input)
    assert normalized.requirements is not None
    assert "pengalaman backend" in normalized.requirements.casefold()
    assert "Python" in normalized.skills


def test_quality_guard_derives_skills_from_requirement_text_when_skill_list_missing() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.JOBSTREET,
        endpoint_type=NormalizationEndpointType.DETAIL,
        raw_payload_subset={
            "payload": {
                "requirements": (
                    "Minimal 3 tahun pengalaman backend, menguasai Python, PostgreSQL, "
                    "dan Docker untuk API service."
                ),
                "skills": [],
            }
        },
    )
    output = {
        "source": {
            "platform": "jobstreet",
            "external_job_id": "job-200",
            "source_url": "https://jobstreet.test/jobs/200",
            "external_apply_url": "https://jobstreet.test/jobs/200",
            "scraped_at": "2026-05-06T00:00:00Z",
            "source_updated_at": None,
        },
        "title": "Backend Engineer",
        "company": {"name": "Bisakerja"},
        "location": {"display": "Jakarta"},
        "salary": None,
        "employment_types": [],
        "work_type": "unknown",
        "description": None,
        "requirements": None,
        "skills": [],
        "posted_at": None,
        "last_seen_at": "2026-05-06T00:00:00Z",
        "status": "active",
        "presentation": {
            "posted_label": None,
            "salary_label": None,
            "badges": [],
            "source_labels": {},
        },
    }

    normalized = validate_ai_normalization_output(output, prompt_input=prompt_input)
    assert "Python" in normalized.skills
    assert "PostgreSQL" in normalized.skills
    assert "Docker" in normalized.skills


def test_quality_guard_builds_description_from_responsibilities_evidence() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.DEALLS,
        endpoint_type=NormalizationEndpointType.DETAIL,
        raw_payload_subset={
            "payload": {
                "detail": {
                    "description": None,
                    "responsibilities": (
                        "Membangun dan memelihara dashboard frontend untuk kebutuhan operasional."
                    ),
                }
            }
        },
    )
    output = {
        "source": {
            "platform": "dealls",
            "external_job_id": "job-321",
            "source_url": "https://dealls.com/jobs/job-321",
            "external_apply_url": "https://dealls.com/jobs/job-321",
            "scraped_at": "2026-05-06T00:00:00Z",
            "source_updated_at": None,
        },
        "title": "Frontend Engineer",
        "company": {"name": "Bisakerja"},
        "location": {"display": "Jakarta"},
        "salary": None,
        "employment_types": [],
        "work_type": "unknown",
        "description": None,
        "requirements": None,
        "skills": [],
        "posted_at": None,
        "last_seen_at": "2026-05-06T00:00:00Z",
        "status": "active",
        "presentation": {
            "posted_label": None,
            "salary_label": None,
            "badges": [],
            "source_labels": {},
        },
    }
    normalized = validate_ai_normalization_output(output, prompt_input=prompt_input)
    assert normalized.description is not None
    assert "dashboard frontend" in normalized.description.casefold()


def test_defaults_force_last_seen_to_current_run_scraped_at() -> None:
    prompt_input = AINormalizationPromptInput(
        source_platform=SourcePlatform.KITALULUS,
        endpoint_type=NormalizationEndpointType.DETAIL,
        raw_payload_subset={
            "scrapedAt": "2026-05-06T14:50:00Z",
            "payload": {"id": "kita-1", "title": "Software Engineer"},
        },
    )
    output = {
        "source": {
            "platform": "kitalulus",
            "external_job_id": "kita-1",
            "source_url": "https://kitalulus.com/jobs/kita-1",
            "external_apply_url": "https://kitalulus.com/jobs/kita-1",
            "scraped_at": "2024-05-04T08:00:00Z",
            "source_updated_at": "2026-05-04T08:00:00Z",
        },
        "title": "Software Engineer",
        "company": {"name": "KitaLulus"},
        "location": {"display": "Jakarta"},
        "salary": None,
        "employment_types": [],
        "work_type": "onsite",
        "description": "Build and maintain backend systems.",
        "requirements": "At least 2 years experience.",
        "skills": ["Python"],
        "posted_at": None,
        "last_seen_at": "2024-05-04T08:00:00Z",
        "status": "active",
        "presentation": {
            "posted_label": None,
            "salary_label": None,
            "badges": [],
            "source_labels": {},
        },
    }

    normalized = validate_ai_normalization_output(output, prompt_input=prompt_input)
    assert normalized.source.scraped_at.isoformat() == "2026-05-06T14:50:00+00:00"
    assert normalized.last_seen_at.isoformat() == "2026-05-06T14:50:00+00:00"
