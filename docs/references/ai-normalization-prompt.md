---
title: AI Normalization Prompt Contract
description: Prompt, schema-validation, repair policy, and golden fixture contract for AI-assisted normalization output.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-07
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
- `outputLanguage`: generated output language from `AI_OUTPUT_LANGUAGE`; allowed values are `indonesian` and `english` (default runtime example: `english`).
- `outputLanguagePolicy`: field-level language rules for generated text, source term preservation, and no-disclaimer behavior.
- `targetJsonSchema`: JSON schema generated from `CanonicalJobSchema`.
- `batchOutputJsonSchema`: JSON schema generated from `AINormalizationBatchOutput`.
- `sourceContext`: detail capability and effective endpoint mode (`list`, `list+detail`, `list+embedded-detail`).
- `rawEvidence`: evidence flags and `detailMetadata` snapshot.
- `deterministicBaseline`: mapper provenance baseline before AI completion.
- `backendSchemaContext`: embedded backend schema alignment rules.
- `completionPolicy`: explicit default and anti-fabrication rules for production sync safety.
- `outputShape`: canonical top-level output requirements.
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
- Display fields are normalized into sanitized semantic HTML.
- Safe display HTML tags are limited to: `<p>`, `<ul>`, `<ol>`, `<li>`, `<strong>`, `<em>`, `<br>`.
- HTML attributes, event handlers, inline URLs, script/style content, and non-allowlisted tags are removed.
- Salary parsing may use numeric fields or salary labels.
- Unknown values remain `null`.
- Glints list data stays partial when detail fields are absent and must use transparent source-limited summary text.
- Prompt instruction language is English.
- Generated/paraphrased prose output language follows `AI_OUTPUT_LANGUAGE`.
- In `english` mode, generated/paraphrased prose must be English-only; mixed-language output is disallowed.
- In `english` mode, non-English evidence should be translated to natural English, while proper nouns/acronyms can stay source-faithful.
- Process/disclaimer meta text is disallowed in display fields (for example rewrite/translation notices).
- `external_apply_url` falls back to `source_url` when unavailable.
- When salary numeric evidence exists (`minAmount`/`maxAmount`), `salary.display` must not be placeholder text.
- Location uses open-world city/province resolution and Indonesia-first country context when geography evidence is Indonesian.
- Post-validation quality guard may backfill missing `requirements` or `skills` from explicit raw evidence when model output leaves them empty.
- When explicit skill list evidence is absent but requirement/description text clearly mentions technologies or tools, post-validation quality guard may derive deterministic skills from that text.
- Post-validation quality guard may backfill missing `description` from explicit responsibilities/detail evidence when available.
- Requirement text must be shaped for downstream atomic rows:
  - education evidence maps to `EDUCATION`.
  - years, seniority, and fresh graduate evidence map to `EXPERIENCE`.
  - tools, technologies, and domain competencies map to `SKILL`.
  - job duties and ownership statements map to `RESPONSIBILITY`.
  - `OTHER` is allowed only for useful evidence that does not fit those groups.
- Benefit and compensation text must not become requirements, including THR, tunjangan, benefit, fasilitas, bonus, cuti, BPJS, and gaji pokok.
- Visual cleanup includes emoji/icon removal and residual invisible symbol stripping (for example variation selectors) on human-readable text fields.
- Sync-safe minimum relation fallback is enforced downstream so each job keeps at least one requirement and one skill relation, including sparse source records.
- Contract is standalone and must not depend on external repositories or runtime file reads.

## Explicit Content Expectations

Expected content structure is explicit so output stays consistent across sources.

| Field                 | Target shape                                                               | Minimum expectation                                                                                                                               |
| --------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `description`         | Safe display HTML (`<p>`, `<ul>/<ol>`, `<li>`, `<strong>`, `<em>`, `<br>`) | Mentions role focus/main responsibilities and execution context when evidence exists, using `AI_OUTPUT_LANGUAGE`                                  |
| `requirement_summary` | Short safe-display summary in professional style                           | Must not start with fixed labels such as `Kualifikasi utama:` or `Requirements:`; keep experience and core competency points in `AI_OUTPUT_LANGUAGE`                 |
| `requirements`        | Plain text requirement body for downstream extraction                      | Factual, no raw HTML, no duplicate sentences, no unsupported claims, generated in `AI_OUTPUT_LANGUAGE`                                            |
| `skills`              | Evidence-based specific skill list                                         | Dedupe case-insensitive, keep technology/tool names source-faithful, split composite skills into atomic items, avoid abstract low-evidence skills |

All four fields must avoid emoji, decorative icons, and noisy visual symbols.

Implementation source: `src/modules/jobs/ai_normalization.py`.

## Output Validation Contract

AI output is accepted only when:

1. It parses into `AINormalizationBatchOutput`.
2. Output item order and `itemId` exactly match input order and identity.
3. Every successful item parses into `CanonicalJobSchema`.
4. Default normalization pass succeeds:
   - `external_apply_url` fallback is resolved.
   - salary values are normalized using shared salary parser.
  - `description` is converted to sanitized semantic display HTML.
  - `requirements` stays plain text for structured requirement extraction.
   - work type defaults to `onsite` when unknown.
   - employment type defaults to `full_time` when unknown.
   - experience level uses deterministic inference and safe fallback.
   - location display/city/region use open-world resolver policy (no static city whitelist).
   - province/city finalization is AI-led from source evidence and geographic reasoning with uncertainty fallback to `null`.
   - when salary numeric evidence exists, salary display is finalized as non-placeholder presentation text for downstream sync.
5. Source policy checks pass:
   - Glints list payloads without detail evidence must produce transparent source-limited description summary.

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
- Model selection is controlled by `OPENAI_MODEL`:
  - single model: all requests use that model.
  - multi model (comma-separated): requests rotate round-robin by configured order.
  - retry attempts may continue on the next model in order.
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

- OpenAI prompt engineering:
  - `https://developers.openai.com/api/docs/guides/prompt-engineering`
- OpenAI Structured Outputs:
  - `https://developers.openai.com/api/docs/guides/structured-outputs`
- OpenAI rate-limit handling guidance:
  - `https://developers.openai.com/api/docs/guides/rate-limits`
- Pydantic model validation:
  - `https://docs.pydantic.dev/latest/concepts/models/`
  - `https://docs.pydantic.dev/latest/concepts/json/`
