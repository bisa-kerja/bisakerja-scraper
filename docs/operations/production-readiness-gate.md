---
title: Production Readiness Gate
description: Final go or no-go gate, approval workflow, evidence requirements, and first-run production procedure for scraper operations.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Production Readiness Gate

Use this page to decide whether production scraping can start safely.

## Final Gates

All gates must be pass before a go decision:

| Gate | Evidence source | Required state |
| --- | --- | --- |
| Sync schema compatibility | `docs/references/backend-sync-schema-map.md`, backend schema checks | Canonical payload and backend schema align |
| AI normalization contract | `docs/references/ai-normalization-prompt.md`, golden fixtures | No fabricated fields; schema-safe output |
| Staging validation | `cli.pipeline staging-report` output | Gate status is `ok` |
| Backend sync and read checks | staging report backend sections | Database consistency and list/detail sample reads pass |
| Glints partial-data fallback | staging report partial-data gates | Partial-rate gate passes within configured band |
| Observability readiness | `docs/operations/observability.md`, run logs | Required run/stage fields and redaction behavior are present |
| Retry, throttle, and rate-limit controls | source adapter settings and logs | Retries bounded; throttle behavior observed |
| Idempotency | verify and staging reports | Duplicate identity count is zero |
| Recovery readiness | runbook and deployment docs | Retry, source isolation, and rollback sync procedures documented |
| Secret safety | `scripts/check_release_readiness.py` | No unsafe tokens, cookies, sessions, or DB passwords in scanned artifacts |

## Go/No-Go Thresholds

| Metric | Threshold | Source |
| --- | --- | --- |
| Schema mismatch count | `0` | contract checks + backend sync mapping review |
| Orphan relation count | `0` | backend consistency checks |
| Duplicate identity count | `0` | verify/staging consistency checks |
| Sync success rate | `>= 99%` for target run | staging report sync events |
| AI invalid output rate | `<= 1%` | AI request logs in staging report |
| Stage runtime p95 | `<=` environment-specific SLO | staging report latency summary |
| Source error rate | `<=` environment-specific SLO | run summary and staging error counts |
| Secret scan findings | `0` | release readiness checker |

If any threshold fails, decision must be `NO-GO`.

## Decision Record

Record one row per release decision:

| Date (UTC) | Environment | Decision | Decision Owner | Evidence Bundle | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-05-04 | staging | NO-GO | data-ingestion-owner | `pending-first-production-evidence` | Template row; replace with real decision |

Decision values:

- `GO`: all required gates pass, no unresolved critical risk.
- `NO-GO`: one or more required gates fail or evidence is incomplete.

## Approval Record

Owner approval must be explicit and traceable.

| Role | Approver | Status | Approval Timestamp (UTC) | Evidence Link |
| --- | --- | --- | --- | --- |
| Data ingestion owner | `pending` | pending | `pending` | `pending` |
| Backend owner | `pending` | pending | `pending` | `pending` |
| Platform docs maintainer | `pending` | pending | `pending` | `pending` |

## First Production Run Procedure

1. Run readiness checks and capture artifacts:
   - `uv run pytest`
   - `uv run python scripts/check_release_readiness.py`
   - `PYTHONPATH=src uv run python -m cli.pipeline verify --run-id <run-id> --env-file .env`
   - `PYTHONPATH=src uv run python -m cli.pipeline staging-report --run-id <run-id> --env-file .env`
2. Start first production run with controlled scope and fixed `runId`.
3. Monitor first hour:
   - stage durations
   - retry counts
   - queue backlog
   - quarantine growth
   - backend sync failures
4. Retry failed source only after failure category is confirmed retryable.
5. Perform quarantine review before replaying quarantined records.
6. Disable one source when needed without stopping all pipeline stages.
7. Rollback sync when backend consistency checks fail after sync.

## Known Limitations and Accepted Risks

| Limitation or Risk | Acceptance Criteria | Owner | Mitigation |
| --- | --- | --- | --- |
| PostgreSQL-specific edge cases are not fully covered by default SQLite integration path | Accepted only with successful staging database consistency checks | data-ingestion-owner | Run isolated PostgreSQL verification before production go |
| One source can degrade while others continue | Accepted only when partial-run policy and freshness safeguards remain active | data-ingestion-owner | Isolate source and replay after fix |
| AI provider latency spikes can increase enrichment delay | Accepted when retry policy is bounded and queue backlog stays under threshold | data-ingestion-owner | Monitor AI p95 and retry totals, then tune thresholds |

## Related Docs

- [Release Readiness](./release-readiness.md)
- [Daily Pipeline Runbook](./daily-pipeline-runbook.md)
- [Verification Matrix](./verification-matrix.md)
- [Staging End-to-End Validation Reference](../references/staging-e2e-validation.md)
