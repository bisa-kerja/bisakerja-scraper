---
title: Release Readiness
description: Release readiness checklist, validation evidence, and future improvement backlog for the scraper service.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: active
last_reviewed: 2026-05-02
---

# Release Readiness

The scraper is release-ready when its automated gates pass, documentation matches implemented behavior, and unsafe artifacts are absent from the repository.

## Readiness Checklist

| Area | Required state | Evidence |
| --- | --- | --- |
| Package | Dependencies install from `uv.lock` | `uv sync --locked` |
| Formatting | Python files match formatter output | `uv run ruff format --check .` |
| Linting | Ruff checks pass | `uv run ruff check .` |
| Unit behavior | Local code paths pass unit tests | `uv run pytest tests/unit` |
| Source contracts | Supported source fixtures remain parseable | `uv run pytest tests/contract` |
| Persistence and sync | Isolated migrated integration checks pass | `uv run pytest tests/integration` |
| Runtime smoke | Config, health, and dry-run checks pass | `uv run pytest tests/smoke` and smoke CLI |
| Documentation | Metadata and local links are valid | `uv run python scripts/check_release_readiness.py` |
| Artifact safety | Docs, fixtures, raw captures, and example env contain no detected secrets | `uv run python scripts/check_release_readiness.py` |
| Container runtime | Image builds and liveness healthcheck works before deploy | Docker build and healthcheck |
| Deploy workflow | Image publish, remote branch sync, migration, startup, and health checks are defined | `.github/workflows/deploy.yml` and `scripts/deploy/remote-deploy.sh` |
| Docs sync | Service docs bundle converts Markdown to MDX and publishes only scraper docs | `uv run python scripts/prepare_docs_sync_bundle.py` |

## Current Validation Evidence

| Date | Check | Result |
| --- | --- | --- |
| 2026-05-02 | Release readiness checker | Pass: docs metadata, local links, fixtures, raw captures, and env example checked |
| 2026-05-02 | Locked dependency sync | Pass: 44 packages resolved, 40 packages checked |
| 2026-05-02 | Ruff format and lint | Pass: 108 files formatted; lint checks passed |
| 2026-05-02 | Unit tests | Pass: 90 tests |
| 2026-05-02 | Contract tests | Pass: 31 tests |
| 2026-05-02 | Integration tests | Pass: 4 tests |
| 2026-05-02 | Smoke tests | Pass: 3 tests |
| 2026-05-02 | Full test suite | Pass: 128 tests |
| 2026-05-02 | Smoke CLI | Pass: config, health, and Dealls dry run |

## Release Decision Rules

- Do not release with failing unit, contract, integration, smoke, or readiness checks.
- Do not release with real source credentials, cookies, session ids, visitor ids, device ids, or database passwords in docs, fixtures, raw captures, or examples.
- Do not release if normalized job behavior changed without updating API, database, testing, and operations docs.
- Do not release if migration behavior changed without an isolated upgrade and downgrade check.
- Do not release if a source is degraded unless the degraded source is documented, isolated, and freshness expiration is safe.

Use [Production Readiness Gate](./production-readiness-gate.md) for final go/no-go thresholds, decision record, approval record, and first-run execution procedure.

## Future Improvements

| Backlog item | Reason | Owner |
| --- | --- | --- |
| PostgreSQL-specific integration job | SQLite covers repository flow but not every PostgreSQL-specific behavior | `data-ingestion-owner` |
| Dependency vulnerability audit | CI currently validates lockfile install and tests; advisory review should be added when release policy is finalized | `data-ingestion-owner` |
| Generated OpenAPI artifact | Consumers need machine-readable route/schema output after route inventory stabilizes | `backend-owner` |
| Generated docs sync readiness report | Platform docs sync can consume a richer machine-readable readiness artifact later | `platform-docs-maintainer` |
| Source drift replay dataset | Larger replay fixtures can catch source schema drift beyond compact CI fixtures | `data-ingestion-owner` |
| Scheduled freshness report | Operators need automated freshness evidence after daily runs | `data-ingestion-owner` |

## Related Docs

- [CI Quality Gates](./ci-quality-gates.md)
- [Documentation Release Checklist](./documentation-release-checklist.md)
- [Testing Strategy](./testing.md)
- [Security](./security.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Production Readiness Gate](./production-readiness-gate.md)
