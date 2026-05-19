---
title: Staging End-to-End Validation Reference
description: Validation contract for staging pipeline evidence, latency thresholds, consistency checks, and backend read verification.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Staging End-to-End Validation Reference

Use this reference when validating a real staging run from source fetch to backend read path.

## Scope

Validation covers:

- scrape to normalized staging flow
- enrichment and sync outcomes
- quarantine and retry behavior
- backend database consistency checks
- backend read checks for list and detail paths

## Command

Run from repository root:

```bash
PYTHONPATH=src uv run python -m cli.pipeline staging-report --run-id <run-id> --env-file .env
```

Optional overrides:

```bash
PYTHONPATH=src uv run python -m cli.pipeline staging-report \
  --run-id <run-id> \
  --scraper-database-url <scraper-db-url> \
  --backend-database-url <backend-db-url> \
  --backend-base-url <backend-base-url> \
  --sample-per-source 2 \
  --stage-p95-threshold-ms 60000 \
  --ai-p95-threshold-ms 45000 \
  --sync-p95-threshold-ms 30000 \
  --retry-threshold 2
```

## Report Contract

`staging-report` returns compact JSON:

- `stageCounts`
  - `fetched`
  - `rawPersisted`
  - `normalized`
  - `enriched`
  - `syncUpserted`
  - `skipped`
  - `quarantined`
  - `errors`
- `latency`
  - `stageDurationsMs`
  - `stageP95Ms`
  - `aiP95Ms`
  - `syncP95Ms`
- `retries`
  - `aiTotalRetries`
  - `aiMaxRetryCount`
  - `syncFailedEvents`
- `queue`
  - `backlogByStatus`
  - `totalRows`
- `quarantine`
  - `count`
  - `openCount`
  - `byReason`
- `consistency`
  - `duplicateRawIdentities`
  - `duplicateNormalizedIdentities`
  - `activeMissingLastSeenAt`
- `stageStatuses`
  - stage-level `runId`, `status`, safe error summary, and recorded counts
- `syncOutcome`
  - `attempted`
  - `sent`
  - `failed`
  - `zeroSentReason`
- `notifyOutcome`
  - `attempted`
  - `sent`
  - `failed`
  - `zeroSentReason`
- `invariants`
  - strict checks for stage-row completeness, normalize gap evidence, quarantine safety, failed-stage error evidence, and zero-sent reason coverage
- `partialData`
  - `totalPartial`
  - `totalNormalized`
  - `bySource.{source}.total`
  - `bySource.{source}.partial`
  - `bySource.{source}.complete`
  - `bySource.{source}.unknown`
  - `bySource.{source}.partialRate`
- `backendDatabaseConsistency`
  - duplicate `(source_platform_id, external_job_id)` rows
  - orphan `company_id`, `skill_id`, and `job_listing_id` checks
  - active rows with missing `last_seen_at`
- `backendApiReadCheck`
  - `GET /api/v1/jobs` by source
  - `GET /api/v1/jobs/:jobId` sample detail per source
- `gates`
  - pass/fail entries for consistency and thresholds
  - `glintsPartialRate` gate for list-only partial data drift

## Pass Criteria

Treat run as valid when:

- no duplicate identities
- no orphan relation in backend checks
- active jobs include `lastSeenAt`
- backend list and detail checks succeed for sampled sources
- configured latency and retry thresholds pass
- strict invariant checks pass

## Release Evidence Mapping

Use the staging report output as the evidence bundle input for production go/no-go decision:

- `stageCounts`, `latency`, `retries`, `queue`, and `quarantine` support runtime and recovery checks.
- `consistency` and `backendDatabaseConsistency` support duplicate/orphan threshold checks.
- `backendApiReadCheck` supports backend list/detail read-path verification.
- `partialData` and `gates.glintsPartialRate` support list-only partial-data drift checks.
- `gates` summary supports pass/fail decision aggregation.

Final decision and approval records are documented in [Production Readiness Gate](../operations/production-readiness-gate.md).

## Safety Rules

- Do not print raw source payload bodies.
- Do not print service tokens, bearer tokens, cookies, headers, or DB passwords.
- Store only safe aggregates and safe identifiers in evidence artifacts.
