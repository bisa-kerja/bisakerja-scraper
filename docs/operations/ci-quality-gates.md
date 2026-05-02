---
title: CI Quality Gates
description: Automated quality gates for scraper formatting, linting, tests, smoke checks, documentation checks, and artifact secret scanning.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: active
last_reviewed: 2026-05-02
---

# CI Quality Gates

Continuous integration protects the scraper from regressions before code is merged or released. The default workflow runs deterministic local checks with dependencies installed from the committed lockfile.

## Workflow

The workflow lives at `.github/workflows/ci.yml` and runs on push, pull request, and manual dispatch.

The workflow uses:

- Python `3.12`.
- `uv sync --locked` for dependency installation from `uv.lock`.
- A read-only GitHub token permission scope.
- Cached `uv` dependencies.
- No source credentials or production database credentials.

## Required Gates

| Gate | Command | Purpose |
| --- | --- | --- |
| Dependency sync | `uv sync --locked` | Install exactly from the committed lockfile |
| Format check | `uv run ruff format --check .` | Prevent formatting drift |
| Lint | `uv run ruff check .` | Catch Python style, import, and bug-risk issues |
| Unit tests | `uv run pytest tests/unit` | Validate local helpers, config, mappers, modules, and scripts |
| Contract tests | `uv run pytest tests/contract` | Validate source fixture and Backend API handoff contracts |
| Integration tests | `uv run pytest tests/integration` | Validate isolated migrated persistence/API/sync behavior |
| Smoke tests | `uv run pytest tests/smoke` | Validate smoke command behavior |
| Smoke CLI | `PYTHONPATH=src uv run python -m cli.smoke ...` | Validate example config, health, and fixture-backed dry run |
| Release readiness | `uv run python scripts/check_release_readiness.py` | Validate docs metadata, local links, and secret-safe artifacts |

Integration tests use isolated temporary databases and must not require staging or production credentials.

## Secret And Artifact Scan

The release readiness checker scans:

- `docs/**/*.md`.
- `tests/fixtures/**/*.json`.
- `raw-response-*.txt`.
- `.env.example`.

It rejects likely bearer credentials, cookie values, session identifiers, visitor identifiers, device identifiers, and database URLs with non-placeholder passwords. Header names and placeholder values are allowed.

## Failure Rules

| Failure | Required action |
| --- | --- |
| Lockfile sync failure | Update dependencies intentionally and commit the lockfile |
| Format or lint failure | Fix the code or generated docs that caused the failure |
| Unit or contract failure | Fix the behavior or update tests only when the documented contract changed |
| Integration failure | Confirm isolated database setup and migration compatibility |
| Smoke failure | Fix config validation, health behavior, or fixture-backed pipeline behavior |
| Readiness failure | Fix metadata, links, unsafe artifacts, or placeholder usage before release |

## Related Docs

- [Testing Strategy](./testing.md)
- [Security](./security.md)
- [Release Readiness](./release-readiness.md)
- [Verification Matrix](./verification-matrix.md)
