---
title: Daily Pipeline Runbook
description: Production operation guide for the daily scrape, normalize, enrich, sync, and notification handoff pipeline.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Daily Pipeline Runbook

Use this runbook to operate the scheduled scraper pipeline and recover partial runs without exposing secrets or raw source payloads.

## Schedule

| Time        | Stage                | Expected result                                                       |
| ----------- | -------------------- | --------------------------------------------------------------------- |
| 01:00       | Scrape               | Raw records stored per source                                         |
| 01:30       | Normalize            | Valid records become normalized jobs; invalid records are quarantined |
| 02:00       | Enrich               | Skills and requirements staged from normalized safe text              |
| 03:00       | Sync                 | Eligible jobs are sent to Backend API in chunks                       |
| 05:00-06:00 | Notification handoff | Sent sync events become backend-owned recommendation candidates       |

## First Checks

| Stage                | Check                                                                              |
| -------------------- | ---------------------------------------------------------------------------------- |
| Scrape               | Run record exists; per-source fetched counts are non-zero or intentionally partial |
| Normalize            | Normalized count and quarantine count match source health                          |
| Enrich               | AI request logs contain status, retry count, model, and safe base URL alias        |
| Sync                 | Sync events show `sent`, retryable `failed`, or reviewed `dead-letter` states      |
| Notification handoff | Handoff events exist only for sent sync events                                     |

## Manual Stage Commands

Run commands from the repository root with a complete environment loaded.

Use the smoke command for a narrow parser check. It uses a sanitized Dealls fixture, disables network access, and does not persist data, call AI enrichment, sync to Backend API, or perform notification handoff.

```bash
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage scrape
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage normalize
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage enrich
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage sync
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage notify-handoff
```

Use the pipeline command for an operator-style end-to-end dry run. By default it uses sanitized fixtures and an in-memory database, so it does not mutate staging or production data.

```bash
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --limit 5 --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --keywords developer,intern,ui/ux --limit 5 --latest --recency-days 7 --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage normalize --source dealls --limit 5 --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline status --run-id <run-id> --env-file .env
```

Use execute mode only against a controlled local or staging environment. It reads the configured source endpoints and scraper database from the env file.

```bash
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env
uv run alembic upgrade head
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --run-id local-e2e --execute --env-file .env
PYTHONPATH=src uv run python -m cli.pipeline verify --run-id local-e2e --env-file .env
PYTHONPATH=src uv run python -m cli.pipeline staging-report --run-id local-e2e --env-file .env
```

Pipeline command rules:

- `--stage` accepts `full`, `scrape`, `normalize`, `enrich`, `sync`, and `notify-handoff`.
- `--source` accepts `all`, `dealls`, `glints`, `jobstreet`, and `kalibrr`.
- `--limit` must be between `1` and `100` and limits each keyword, not the whole run.
- `--keyword` may be repeated for individual keyword overrides.
- `--keywords` accepts a comma-separated keyword override.
- When keyword flags are absent, the command uses `SCRAPER_KEYWORDS`.
- `--latest` forces latest retrieval mode.
- `--recency-days` must be between `1` and `365`; when absent, the command uses `SCRAPER_RECENCY_DAYS`.
- Dry-run output is compact JSON and must not print service tokens, bearer tokens, cookies, raw headers, database passwords, or raw payload bodies.
- Dry-run output includes source and keyword summaries with requested limit and newest/oldest source timestamps when available.
- Full-stage run status is `completed`, `partial`, or `failed`; treat `failed` as hard failure even when prior stages succeeded.
- Manual runs share the scheduler guard so only one in-process operator run is accepted at a time.
- `--execute` uses the configured scraper database and should only run after migration and readiness checks pass in a controlled non-production environment.
- `verify` summarizes run rows, raw and normalized counts, source/keyword counts, sync and handoff counts, duplicate identity counts, and latest metadata without printing raw payloads or secrets.
- `staging-report` adds staging evidence checks for latency percentiles, retries, quarantine distribution, backend relation consistency, and backend read-path sampling.
- Stage run-id derivation accepts base IDs and stage-suffixed IDs, including `-notify` and `-notify-handoff`.
- Source HTTP circuit breaker is retryable and auto-recovers after cooldown; if still open after repeated cooldown windows, treat as active incident and escalate.

The HTTP trigger route is still not exposed. Operators should use the CLI until the internal run API is implemented.

## Recovery

| Failure                          | Recovery                                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------------------- |
| One source scrape fails          | Re-run only the affected source after checking source auth, headers, rate limits, and timeout   |
| Normalize fails for some records | Inspect quarantine metadata, fix mapper, then replay affected raw records                       |
| Enrichment fails                 | Retry failed enrichment jobs when error is timeout, rate limit, or provider unavailable         |
| Sync chunk fails                 | Retry pending or retryable failed sync events; do not replay sent or dead-letter events blindly |
| Notification handoff fails       | Retry failed handoff events after backend notification endpoint is healthy                      |

## Safe Partial Run Rules

- Healthy sources may continue when one source fails.
- Failed source runs must not expire unseen jobs for that source.
- Failed sync chunks must not block later chunks.
- Sent sync and handoff events must be idempotent on replay.
- Dead-letter rows require operator review before replay.

## Release Evidence

Before production promotion, capture:

| Gate                    | Evidence                                               |
| ----------------------- | ------------------------------------------------------ |
| Unit and contract tests | Passing test output                                    |
| Database migration      | Upgrade and rollback result                            |
| E2E fixture pipeline    | Offline fixture run result                             |
| Smoke CLI               | Dry-run output per stage                               |
| Secret safety           | Scan showing no raw secrets in docs, logs, or fixtures |
| Backend contract        | Sync payload and handoff payload checked against docs  |

## Related Docs

- [Observability](./observability.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Verification Matrix](./verification-matrix.md)
- [Staging End-to-End Validation Reference](../references/staging-e2e-validation.md)
- [Recommendation Email Handoff](../integrations/recommendation-email-handoff.md)
