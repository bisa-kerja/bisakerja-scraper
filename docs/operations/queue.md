---
title: Scraper Stage Queue Operations
description: Local DB-backed queue behavior, retry policy, dead-letter handling, and recovery rules for scraper pipeline stages.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Scraper Stage Queue Operations

The scraper uses a local database-backed queue for stage work that should be retryable and recoverable without blocking the full pipeline.

## Queue Backend

The first queue backend is the scraper database table `stage_jobs`. This avoids requiring Redis for local development and CI, while preserving a clear adapter boundary for a future external queue.

## Job Types

| Job type | Purpose |
| --- | --- |
| `scrape-source` | Fetch source records for one platform or source window |
| `normalize-raw` | Transform stored raw records into normalized jobs |
| `enrich-batch` | Enrich a batch of normalized jobs with skills and requirements |
| `sync-batch` | Send a chunk of eligible records to the Backend API handoff path |
| `notify-handoff` | Prepare backend-owned recommendation or notification follow-up input |

## State Model

| Status | Meaning | Next state |
| --- | --- | --- |
| `pending` | Available for claim when `available_at` is reached | `running` |
| `running` | Claimed by a worker | `completed`, `failed`, or `dead-letter` |
| `completed` | Handler completed successfully | Terminal |
| `failed` | Handler failed but attempts remain | `running` after `available_at` |
| `dead-letter` | Attempts are exhausted | Manual review |

## Retry Policy

Each job stores `attempt_count` and `max_attempts`. A failed claim increments `attempt_count` exactly once. If attempts remain, the job becomes `failed` and can be claimed again after `available_at`. If the limit is reached, the job becomes `dead-letter`.

Use short retry delays for transient database/provider failures. Use no blind retry for invalid payloads, auth failures, or schema mismatches unless the underlying cause has been corrected.

Worker handlers should raise errors to the queue worker and let the queue worker own the fail transition, so attempt accounting stays consistent.

## Idempotency

Handlers must tolerate reprocessing:

- Raw records upsert by source platform and external id.
- Normalized jobs upsert by source platform and external id.
- Enrichment skills upsert by normalized job and normalized skill value.
- Enrichment requirements upsert by normalized job, requirement type, and normalized value.
- Sync events reuse target, normalized job id, and payload hash.
- Notification handoff events should use run id, source platform, and job identity.

## Correlation

Every queue job stores `correlation_id`. Workers must copy the same value when enqueueing downstream work so operators can trace the full stage chain.

## Dead-Letter Recovery

Before replaying a dead-letter job:

1. Confirm the error category and root cause.
2. Confirm the handler is idempotent.
3. Confirm the payload contains no raw credentials or unsafe source headers.
4. Enqueue replacement work with the same correlation id and safe payload.
5. Keep the original dead-letter row for audit.

Do not edit terminal queue rows in place unless a documented maintenance procedure exists.

## Related Docs

- [Database Design](../database.md)
- [Data Flow](../overview/data-flow.md)
- [Observability](./observability.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Testing Strategy](./testing.md)
