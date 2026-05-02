---
title: Daily Pipeline Runbook
description: Production operation guide for the daily scrape, normalize, enrich, sync, and notification handoff pipeline.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-02
---

# Daily Pipeline Runbook

Use this runbook to operate the scheduled scraper pipeline and recover partial runs without exposing secrets or raw source payloads.

## Schedule

| Time | Stage | Expected result |
| --- | --- | --- |
| 01:00 | Scrape | Raw records stored per source |
| 01:30 | Normalize | Valid records become normalized jobs; invalid records are quarantined |
| 02:00 | Enrich | Skills and requirements staged from normalized safe text |
| 03:00 | Sync | Eligible jobs are sent to Backend API in chunks |
| 05:00-06:00 | Notification handoff | Sent sync events become backend-owned recommendation candidates |

## First Checks

| Stage | Check |
| --- | --- |
| Scrape | Run record exists; per-source fetched counts are non-zero or intentionally partial |
| Normalize | Normalized count and quarantine count match source health |
| Enrich | AI request logs contain status, retry count, model, and safe base URL alias |
| Sync | Sync events show `sent`, retryable `failed`, or reviewed `dead-letter` states |
| Notification handoff | Handoff events exist only for sent sync events |

## Manual Stage Commands

Run commands from the repository root with a complete environment loaded.

```bash
PYTHONPATH=src python -m cli.smoke dry-run --stage scrape
PYTHONPATH=src python -m cli.smoke dry-run --stage normalize
PYTHONPATH=src python -m cli.smoke dry-run --stage enrich
PYTHONPATH=src python -m cli.smoke dry-run --stage sync
PYTHONPATH=src python -m cli.smoke dry-run --stage notify-handoff
```

Dry runs must not print service tokens, bearer tokens, cookies, raw headers, or raw payload bodies.

## Recovery

| Failure | Recovery |
| --- | --- |
| One source scrape fails | Re-run only the affected source after checking source auth, headers, rate limits, and timeout |
| Normalize fails for some records | Inspect quarantine metadata, fix mapper, then replay affected raw records |
| Enrichment fails | Retry failed enrichment jobs when error is timeout, rate limit, or provider unavailable |
| Sync chunk fails | Retry pending or retryable failed sync events; do not replay sent or dead-letter events blindly |
| Notification handoff fails | Retry failed handoff events after backend notification endpoint is healthy |

## Safe Partial Run Rules

- Healthy sources may continue when one source fails.
- Failed source runs must not expire unseen jobs for that source.
- Failed sync chunks must not block later chunks.
- Sent sync and handoff events must be idempotent on replay.
- Dead-letter rows require operator review before replay.

## Release Evidence

Before production promotion, capture:

| Gate | Evidence |
| --- | --- |
| Unit and contract tests | Passing test output |
| Database migration | Upgrade and rollback result |
| E2E fixture pipeline | Offline fixture run result |
| Smoke CLI | Dry-run output per stage |
| Secret safety | Scan showing no raw secrets in docs, logs, or fixtures |
| Backend contract | Sync payload and handoff payload checked against docs |

## Related Docs

- [Observability](./observability.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Verification Matrix](./verification-matrix.md)
- [Recommendation Email Handoff](../integrations/recommendation-email-handoff.md)
