---
title: Daily Pipeline Runbook
description: Production operation guide for the daily scrape, normalize, enrich, sync, and notification handoff pipeline.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-05
---

# Daily Pipeline Runbook

Use this runbook to operate the scheduled scraper pipeline and recover partial runs without exposing secrets or raw source payloads.

Deployment default runs two containers:

- `app` for API serving.
- `scheduler` for automatic stage execution by cron (`python -m cli.daemon`).

## Schedule

| Time        | Stage                | Expected result                                                       |
| ----------- | -------------------- | --------------------------------------------------------------------- |
| 00:00       | Scrape               | Raw records stored per source                                         |
| 02:00       | Normalize            | Valid records become normalized jobs; invalid records are quarantined |
| 04:00       | Enrich               | Skills and requirements staged from normalized safe text              |
| 06:00       | Sync                 | Eligible jobs are sent to Backend API in chunks                       |
| 08:00       | Notification handoff | Sent sync events become backend-owned recommendation candidates       |

## First Checks

| Stage                | Check                                                                              |
| -------------------- | ---------------------------------------------------------------------------------- |
| Scrape               | Run record exists; per-source fetched counts are non-zero or intentionally partial |
| Normalize            | Normalized count and quarantine count match source health                          |
| Enrich               | AI request logs contain status, retry count, model, and safe base URL alias; model usage summary is available by model |
| Sync                 | Sync events show `sent`, retryable `failed`, or reviewed `dead-letter` states      |
| Notification handoff | Handoff events exist only for sent sync events                                     |

## Manual Stage Commands

Run commands from the repository root with a complete environment loaded.

Use the smoke command for a narrow parser check. It uses a sanitized Dealls fixture, disables network access, and does not persist data, call AI enrichment, sync to Backend API, or perform notification handoff.

```bash
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage scrape
PYTHONPATH=src uv run python -m cli.smoke dry-run --source glints --stage scrape
PYTHONPATH=src uv run python -m cli.smoke dry-run --source jobstreet --stage scrape
PYTHONPATH=src uv run python -m cli.smoke dry-run --source kalibrr --stage scrape
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage normalize
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage enrich
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage sync
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage notify-handoff
```

Use the wizard command as the primary operator entrypoint. It guides mode, stage, source, keyword preset, limit, recency, env file, and optional run id, then prints a redacted pre-run summary and risk gates.

```bash
PYTHONPATH=src uv run python -m cli.pipeline wizard
PYTHONPATH=src uv run python -m cli.pipeline wizard --dry-run --source dealls --stage scrape --limit 1 --env-file .env.example --yes
PYTHONPATH=src uv run python -m cli.pipeline quick-dry-run --source all --stage full --env-file .env.example
```

Use the run command for explicit scripted flows. Use `--dry-run` mode with sanitized fixtures and an in-memory database, so it does not mutate staging or production data.

```bash
PYTHONPATH=src uv run python -m cli.pipeline preflight --stage full --source all --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --limit 5 --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --keywords developer,intern,ui/ux --limit 5 --latest --recency-days 7 --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage normalize --source dealls --limit 5 --dry-run --env-file .env.example
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

Execute sync semantics:

- When `BACKEND_SYNC_ENABLED=false`, sync and notification handoff use recording clients (no outbound backend API mutation).
- When `BACKEND_SYNC_ENABLED=true`, sync and notification handoff call backend internal endpoints using `BACKEND_SYNC_BASE_URL` and `BACKEND_SYNC_SERVICE_TOKEN`.
- Backend must expose `POST /api/v1/internal/scraper/jobs` and `POST /api/v1/internal/notification-events`; `BACKEND_SYNC_SERVICE_TOKEN` must match Backend API `SCRAPER_API_SERVICE_TOKEN`.
- Large runs are safe for Backend API: sync sends repeated `BACKEND_SYNC_BATCH_SIZE` chunks (maximum `100` jobs per request), and notification handoff sends repeated candidate chunks (maximum `1000` candidates per request).

Pipeline command rules:

- `--stage` accepts `full`, `scrape`, `normalize`, `enrich`, `sync`, and `notify-handoff`.
- `--source` accepts `all`, `dealls`, `glints`, `jobstreet`, and `kalibrr`.
- exactly one mode flag is required: `--dry-run` or `--execute`.
- `--limit` must be between `1` and `100` and limits each keyword, not the whole run. Total fetched/synced rows may be much larger because the run fans out across sources and keywords.
- `--keyword` may be repeated for individual keyword overrides.
- `--keywords` accepts a comma-separated keyword override.
- When keyword flags are absent, the command uses `SCRAPER_KEYWORDS`.
- `--latest` forces latest retrieval mode.
- `--recency-days` must be between `1` and `365`; when absent, the command uses `SCRAPER_RECENCY_DAYS`.
- `wizard` mode menu supports `dry-run`, `execute`, `status`, `verify`, and `staging-report`.
- `wizard` risk confirmation requires exact `YES`; default enter must reject risky runs.
- `wizard --yes` is only valid for non-TTY safe dry-run and must not bypass risky confirmation gates.
- Dry-run output is compact JSON and must not print service tokens, bearer tokens, cookies, raw headers, database passwords, or raw payload bodies.
- Dry-run output includes `requestedSources`, `executedSources`, and `skippedSources` so operators can see disabled-source skips explicitly.
- `preflight` validates env loading, migration target head, source enablement, fixture availability, backend sync mode, and redacted evidence preview before an operator run.
- Dry-run output includes source and keyword summaries with requested limit and newest/oldest source timestamps when available.
- Run output includes `stageStatuses` and `countBreakdown` so `rawPersisted`, `normalizedPersisted`, `enrichmentPersisted`, `syncSent`, and `notifyHandoffSent` are explicit.
- Run output includes `diagnostics.sync.failures` when sync attempts fail, including error category, status code, safe endpoint path, and count.
- Full-stage run status is `completed`, `partial`, or `failed`; treat `failed` as hard failure even when prior stages succeeded.
- Manual runs share the scheduler guard so only one in-process operator run is accepted at a time.
- `--execute` uses the configured scraper database and should only run after migration and readiness checks pass in a controlled non-production environment.
- `--run-id` must be unique per execute run. For `--stage full`, stage rows use deterministic ids (`<run-id>-scrape`, `<run-id>-normalize`, `<run-id>-enrich`, `<run-id>-sync`, `<run-id>-notify`), so reusing the same run id will fail on primary-key collisions.
- Deployed scheduler stage runs use deterministic day-based ids (`scheduled-YYYYMMDD-<stage>`). Completed day-stage rows are skipped; failed or partial rows run with retry ids (`scheduled-YYYYMMDD-<stage>-retry-XX`).
- `verify` summarizes run rows, raw and normalized counts, source/keyword counts, sync and handoff counts, duplicate identity counts, and latest metadata without printing raw payloads or secrets.
- `verify` also runs strict invariants for stage-row completeness, normalize gap evidence, quarantine error safety, failed-stage evidence, and zero-sent reason checks for sync and notification handoff.
- `staging-report` adds staging evidence checks for latency percentiles, retries, quarantine distribution, backend relation consistency, backend read-path sampling, strict invariants, and explicit `syncOutcome`/`notifyOutcome` zero-sent reasons.
- Normalize stage AI processing is serial per batch (`OPENAI_NORMALIZATION_BATCH_SIZE`) and always waits fixed inter-batch delay (`OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS`).
- Normalize and enrich stages use per-item partial handling; one failed item does not stop the whole stage.
- `OPENAI_MODEL` may be single-model or comma-separated multi-model. Runtime rotates requests round-robin by configured order, and retry attempts may continue on the next model.
- Multi-model rotation improves distribution but does not bypass organization/project/shared-family rate limits.
- Execute mode streams progress logs to `stderr`; machine-readable final JSON stays on `stdout`.
- Stage run-id derivation accepts base IDs and stage-suffixed IDs, including `-notify` and `-notify-handoff`.
- Source HTTP circuit breaker is retryable and auto-recovers after cooldown; if still open after repeated cooldown windows, treat as active incident and escalate.

The HTTP trigger route is still not exposed. Operators should use the CLI until the internal run API is implemented.

## Production Read-Only Verification

Run these checks without mutating data:

```bash
curl --fail http://127.0.0.1:${APP_PORT:-3003}/health/live
curl --fail http://127.0.0.1:${APP_PORT:-3003}/health/ready
docker compose -f docker-compose.yml --env-file .env.production ps
docker compose -f docker-compose.yml --env-file .env.production port app 3003
docker compose -f docker-compose.yml --env-file .env.production ps scheduler
git rev-parse HEAD
```

Expected:

- app health endpoints return `200`.
- published app port is `127.0.0.1:3003->3003/tcp`.
- scheduler is running and healthy.
- deployed git SHA matches immutable deployment SHA reference.

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
- No sync chunk may exceed the Backend API `100` job request cap.
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
