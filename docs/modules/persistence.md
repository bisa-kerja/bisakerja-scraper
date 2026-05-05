---
title: Persistence Module
description: Local scraper database writes, staging persistence, sync preparation, transactions, failure handling, observability, and tests.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Persistence Module

The persistence module stores raw, staging, and sync-ready records in scraper-owned tables before handoff to Backend API-consumable tables.

## Responsibility

| Area | Rule |
| --- | --- |
| Raw storage | Store response bodies and safe metadata for replay |
| Staging storage | Store canonical candidate records after validation |
| Sync preparation | Build idempotent upsert batches |
| Transactions | Keep related company/job/requirement writes consistent |

## Write Boundaries

| Store | Writer | Rule |
| --- | --- | --- |
| Local raw tables | Ingestion | Redact request metadata before persistence or sharing |
| Local staging tables | Normalizer/enrichment | Keep retryable and replayable |
| Main job tables | Sync service | Upsert source platform, company, job, requirements, skills |
| Backend user tables | None | Scraper must not write |

## Repository Behavior

Persistence writes use the source-local identity pair `sourcePlatform + externalId` as the idempotency key for both raw and normalized records.

Required behavior:

- Re-running the same fixture or source page updates the existing raw row instead of inserting a duplicate.
- Normalized job rows update title, company, URLs, status, payload snapshot, `postedAt`, and `lastSeenAt` on repeat writes.
- Raw and normalized writes for one job share a transaction boundary.
- If the normalized write fails after raw storage starts, the raw insert is rolled back with the same transaction.
- Payload hashes are deterministic JSON SHA-256 values so replay checks can detect source payload changes.

The writer accepts canonical job models only after mapper validation. Source-specific payloads remain in raw storage and are not exposed through normalized output fields.

## Failure Modes

| Failure | Handling |
| --- | --- |
| DB unavailable | Mark run failed/partial; retry later |
| Constraint conflict | Resolve by source identity and retry chunk |
| Partial sync chunk | Retry idempotently |
| Raw storage overflow | Apply retention policy; never drop unsynced critical state silently |
| Sensitive metadata | Redact or reject write |

## Observability

Track:

- Raw rows stored.
- Staging rows written.
- Sync chunks attempted/succeeded/failed.
- Large backend sync runs are persisted per job while outbound requests are chunked, so one failed `100`-job backend request does not discard other chunks.
- Transaction latency.
- Constraint conflict count.
- Retention cleanup count.

## Tests

| Test | Purpose |
| --- | --- |
| Repository insert/upsert | Confirms idempotent writes |
| Transaction rollback | Confirms partial related writes roll back |
| Chunk retry | Confirms no duplicate rows after retry |
| Redacted metadata | Confirms headers/cookies are absent |
| Backend boundary | Confirms no user-owned tables are written |

## Related Docs

- [Database Design](../database.md)
- [Scraper API Contract](../integrations/scraper-api-contract.md)
- [API Response Standard](../api-response-standard.md)
