---
title: AI Normalization Prompt Contract
description: Prompt, schema-validation, repair policy, and golden fixture contract for AI-assisted normalization output.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# AI Normalization Prompt Contract

This contract defines how AI-generated normalized job output must be shaped before persistence and sync.

## Input Envelope

Each normalization request includes:

- `inputItems[]`: batch items with:
  - `itemId`: stable per-item identifier.
  - `sourcePlatform`: source slug (`dealls`, `glints`, `jobstreet`, `kalibrr`).
  - `endpointType`: `list` or `detail`.
  - `rawPayloadSubset`: minimal source payload fragment used as evidence.
- `targetSchema`: canonical output contract name.
- `targetJsonSchema`: JSON schema generated from `CanonicalJobSchema`.
- `batchOutputJsonSchema`: JSON schema generated from `AINormalizationBatchOutput`.
- `backendSchemaContext`: embedded backend schema alignment rules.
- `standaloneSchemaBlueprint`: standalone canonical blueprint (type, required fields, defaults, constraints).
- `normalizationOutputExamples`: valid list/detail output examples.

## System Prompt Rules

The normalization system prompt enforces:

- AI acts as strict normalizer, not copywriter.
- Output must be one JSON object with `results[]`.
- `results[]` length and order must match `inputItems[]`.
- Every `results[]` item must keep `itemId` and return either:
  - `normalizedJob`, or
  - `errorCode` + `errorMessage`.
- No invented facts outside `rawPayloadSubset`.
- HTML fields are normalized into safe plain text.
- Salary parsing may use numeric fields or salary labels.
- Unknown values remain `null`.
- Glints list data must stay partial when detail fields are absent.
- `external_apply_url` falls back to `source_url` when unavailable.
- Contract is standalone and must not depend on external repositories or runtime file reads.

Implementation source: `src/modules/jobs/ai_normalization.py`.

## Output Validation Contract

AI output is accepted only when:

1. It parses into `AINormalizationBatchOutput`.
2. Output item order and `itemId` exactly match input order and identity.
3. Every successful item parses into `CanonicalJobSchema`.
4. Default normalization pass succeeds:
   - `external_apply_url` fallback is resolved.
   - salary values are normalized using shared salary parser.
   - HTML-like text fields are cleaned.
   - location display fallback is derived from city/region/country.
5. Source policy checks pass:
   - Glints list payloads without detail evidence must not contain `description` or `requirements`.

Rejected output raises `AINormalizationContractError`.

## Partial Item Policy

Batch response uses per-item partial handling:

- one item error must not fail the full batch response shape.
- when `ai_normalization_fail_open=true`, failed items fall back to mapper output.
- when `ai_normalization_fail_open=false`, failed items are quarantined.

Supported batch error codes:

- `INSUFFICIENT_EVIDENCE`
- `UNSUPPORTED_PAYLOAD`

## Pipeline Integration

- `PipelineOrchestrator` uses source mapper output as baseline.
- Execute normalize stage groups records into serial batches.
- Batch size is controlled by `OPENAI_NORMALIZATION_BATCH_SIZE` (default `5`).
- Fixed inter-batch delay is controlled by `OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS` and is always applied between batches.
- Success path: AI per-item result replaces baseline mapper result.
- Failure path:
  - fail-open mode persists mapper fallback.
  - fail-closed mode quarantines only failed items.

## Format Repair Policy

Format repair is allowed only for structural issues:

- invalid JSON syntax
- missing required key
- wrong type or enum

Repair prompt rules:

- fix JSON format only
- no semantic additions, deletions, or value rewrites
- return one corrected JSON object

If repaired output still fails schema/policy validation, the record is rejected and must not proceed to persistence or sync.

## Golden Fixture Coverage

Golden fixtures live in `tests/fixtures/normalization_golden/`:

- `dealls.json`
  - list minimal record
  - detail record with HTML and salary range
- `glints.json`
  - list record with partial data and no detail text
- `jobstreet.json`
  - list record with relative posted label and salary label parsing
  - detail record with uncertain salary label (numeric remains null)
- `kalibrr.json`
  - list record with embedded HTML detail fields

Contract tests:

- `tests/unit/modules/test_ai_normalization_contract.py`

## Official References

- OpenAI Structured Outputs:
  - `https://developers.openai.com/api/docs/guides/structured-outputs`
- OpenAI rate-limit handling guidance:
  - `https://developers.openai.com/cookbook/examples/how_to_handle_rate_limits`
- Pydantic model validation:
  - `https://docs.pydantic.dev/latest/concepts/models/`
  - `https://docs.pydantic.dev/latest/concepts/json/`
