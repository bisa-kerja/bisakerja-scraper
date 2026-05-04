---
title: Scraper Verification Matrix
description: Module-level verification matrix for scraper happy paths, critical failures, release gates, and evidence.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Scraper Verification Matrix

This matrix defines the minimum evidence needed before scraper docs, code, or operational changes are considered verified.

## Module Matrix

| Area | Happy-path verification | Critical-failure verification | Evidence |
| --- | --- | --- | --- |
| Scheduler | Run starts inside configured window | Duplicate active run is skipped or rejected | Run record with `runId` |
| Source HTTP client | Per-source limiter spaces requests and retry classifier marks `429` and transient `5xx` retryable | Circuit breaker opens for repeated retryable failures without blocking unrelated sources | Unit test result |
| Dealls adapter | REST list and detail fixtures fetched and merged | Missing detail keeps list record valid | Contract test result |
| Glints adapter | GraphQL list fixture parsed | Missing detail endpoint uses list fallback | Contract test result |
| Glints partial metrics | Partial rows are counted per source in staging report | Partial-rate drift gate flags abnormal Glints ratio | Smoke test result |
| JobStreet adapter | GraphQL list and detail fixtures parsed without real auth | Missing bearer token is classified as config error and request bodies omit auth/session captures | Contract test result |
| Kalibrr adapter | Next.js build id is resolved and cached from page data | Stale `buildId` 404 refreshes and retries data request | Unit test result |
| Raw store | Redacted payload metadata stored | Unsafe header cannot be persisted | Redaction test |
| Normalizer | Canonical job fields, salary ranges, and UTC posted dates produced | Relative date labels do not become fake timestamps | Mapper and unit test result |
| Quarantine | Malformed raw records are held with safe error metadata | Quarantined records are excluded from sync | Unit or contract test result |
| Deduplicator | Existing job updates by source identity | Missing identity quarantines and identity collision is surfaced | Dedup test |
| Enrichment | Skills and requirements added from clean text | Timeout creates retry/dead letter | Worker test or run log |
| Persistence | Staging rows and sync batches write successfully | Batch error rolls back or isolates failed rows | DB integration test |
| Freshness | `lastSeenAt` updates for seen jobs | Partial source run does not expire unseen jobs | Freshness test |
| Sync | Main DB shape receives upsert-ready rows | Sync failure keeps staging recoverable | Sync dry-run/test |
| Notification handoff | Sent sync events become job candidate events | Failed handoff remains retryable and never reads backend user tables | Handoff unit or E2E test |
| AI audit | Sanitized request metadata and summaries are stored | API key, raw prompt, raw payload, headers, and tokens are not persisted | Unit test result |
| Stage queue | Eligible jobs are claimed and completed | Failed jobs retry then dead-letter after max attempts | Queue unit test result |
| Docs sync | Bundle manifest maps docs deterministically | Path escape or missing metadata rejects bundle | Docs check result |

## Source Coverage Matrix

| Source | List contract | Detail contract | Required special check |
| --- | --- | --- | --- |
| Dealls | Required | Required for slug endpoint | Null salary, REST pagination, and missing-detail tolerance |
| Glints | Required | Not captured | List-first fallback |
| JobStreet | Required | Required for `jobDetails` operation | Bearer/session redaction and HTML preservation |
| Kalibrr | Required | Included in job object | Dynamic `buildId` handling |

## Release Evidence Matrix

| Gate | Required result |
| --- | --- |
| Metadata | All changed docs have required frontmatter |
| Links | Relative docs links resolve |
| Secret scan | No bearer, cookie, session, visitor, or raw credential values in docs |
| Unit tests | Changed mapper/helper behavior passes |
| Contract tests | All source fixtures remain accepted |
| Fixture coverage | All supported sources have list, detail or fallback, mapper, malformed, and sanitization evidence |
| Integration tests | Changed DB/sync behavior passes against isolated DB |
| Smoke tests | Target runtime starts and processes fixture path |
| E2E fixture pipeline | Raw fixtures produce normalized, enriched, synced, and handed-off jobs without network |
| Staging validation report | Stage counts, latency percentiles, retries, consistency checks, and backend read sampling pass configured gates |
| Observability | Run logs include `runId`, source, stage, status, counts, and duration |
| Recovery | Rollback or retry path exists for changed operational behavior |

## Failure Acceptance Rule

A release may tolerate one degraded source only when:

- Other sources complete normally.
- Freshness docs say the degraded source is partial.
- Expiration logic is disabled for the failed source run.
- Backend-facing normalized output does not expose raw payload.
- Incident notes include `runId`, source, failure category, and next action.

## Related Docs

- [Testing Strategy](./testing.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Deployment](./deployment.md)
- [Documentation Sync](./documentation-sync.md)
