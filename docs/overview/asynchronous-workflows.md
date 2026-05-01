---
title: Scraper Asynchronous Workflows
description: Scheduled and background workflows for scraping, normalization, enrichment, sync, retry, and notification handoff.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Asynchronous Workflows

Scraper work runs as scheduled and retryable jobs. User-facing Backend API requests should read existing normalized data and avoid live scraper calls.

## Workflow Inventory

| Workflow | Trigger | Input | Output | Owner | Failure mode |
| --- | --- | --- | --- | --- | --- |
| Daily scrape | Cron/Celery Beat at 01:00 | Source list config | Raw captures | Scraper workers | Source unavailable, auth/header rejected |
| Normalize batch | Scheduled after scrape at 01:30 | Raw captures | Staging jobs | Normalizer worker | Mapper mismatch, missing identity |
| Enrichment batch | Scheduled at 02:00 | Safe staging text | Skills and structured requirements | Enrichment worker | Provider timeout, rate limit |
| Sync batch | Scheduled at 03:00 | Valid staging rows | Main DB upserts | Sync worker | Constraint conflict, partial chunk failure |
| Notification handoff | 05:00-06:00 | Fresh normalized jobs | Backend/product notification inputs | Backend/product worker | User preference mismatch, mail provider failure |
| Retry quarantine | Event or manual task | Failed raw/staging rows | Reprocessed rows or rejected state | Scraper operator | Repeated malformed payload |

## Run State

Each run should track:

- Source platform.
- Started and finished timestamps.
- Stage.
- Status: `RUNNING`, `SUCCEEDED`, `FAILED`, `PARTIAL`.
- Fetched count.
- Normalized count.
- Enriched count.
- Synced count.
- Error class and sanitized message.

## Retry Rules

| Failure | Retry |
| --- | --- |
| Network timeout | Retry with exponential backoff and source-specific cap |
| HTTP 429 or source throttle | Back off longer and mark source freshness degraded |
| Auth/session rejected | Stop source run, refresh configured credential, do not retry with invalid token repeatedly |
| Mapper error | Quarantine payload, keep raw capture, update source mapper |
| Enrichment timeout | Retry batch; do not block base job visibility if required fields are valid |
| Sync chunk failure | Retry chunk idempotently by source identity |

## Concurrency Rules

- Run sources independently when possible.
- Keep per-source rate limits separate.
- Avoid overlapping sync jobs for the same source/platform window.
- Batch enrichment in small groups, with `10` jobs as the baseline.
- Ensure retry tasks are idempotent.

## Observability Minimum

Each workflow should emit:

- `ingestion_run_id`.
- `source_platform`.
- `stage`.
- `duration_ms`.
- Count metrics.
- Sanitized error class.
- Retry count.

Logs must not include bearer tokens, cookies, session ids, raw CV content, or unredacted source headers.

