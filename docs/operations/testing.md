---
title: Scraper Testing Strategy
description: Unit, integration, contract, smoke, fixture, security, and release verification strategy for scraper operations.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-02
---

# Scraper Testing Strategy

Scraper tests must prove that source adapters, mappers, deduplication, enrichment, persistence, freshness, and sync behavior are deterministic and safe.

## Principles

- Test raw source assumptions with sanitized fixtures.
- Test normalized output against Backend API consumer expectations.
- Keep unit tests free from external network and production data.
- Use isolated databases for persistence and sync tests.
- Cover happy paths and critical failure paths for each module.
- Never depend on live source credentials in ordinary CI.
- Treat raw payload leakage as a test failure.

## Test Categories

| Category | Scope | Required evidence |
| --- | --- | --- |
| Unit | Parsers, mappers, validators, dedup helpers | Deterministic input/output |
| Source contract | Sanitized `raw-response-*.txt` shape and payload roots | Required fields and nullability are accepted |
| Integration | Adapter to raw store, mapper to staging, sync writer to DB | Stage counts and safe failure handling |
| Smoke | Startup, config validation, one fixture-backed pipeline path | Service can start and process safe fixture data |
| Security | Redaction, no secret logging, internal-only endpoints | Sensitive strings absent from logs/docs/fixtures |
| Regression | Known source drift or mapper bug | Reproduces prior failure and proves fix |

## Fixture Rules

Fixture inputs should come from sanitized raw captures:

| Fixture source | Use |
| --- | --- |
| `raw-response-dealls.txt` | REST list mapper and null salary behavior |
| `raw-response-glints.txt` | GraphQL list mapper and missing detail fallback |
| `raw-response-jobstreet.txt` | GraphQL list/detail-ready fields and auth-free fixture |
| `raw-response-kalibrr.txt` | Next.js data mapper and dynamic `buildId` assumptions |

Rules:

- Strip authorization, cookie, session, visitor, device, and tracking identifiers.
- Keep representative null salary, HTML text, relative labels, and UI/noise fields.
- Keep fixture size small for normal CI; use larger replay fixtures only in dedicated jobs.
- Do not mutate root raw captures during tests.

## Module Test Mapping

| Module | Happy path | Critical failure path |
| --- | --- | --- |
| Ingestion | Fetch fixture pages and persist raw rows | Source timeout, auth failure, 429, schema root missing |
| Parsing/normalization | Produce canonical job fields from each source | Missing identity, unsafe HTML, unsupported field type |
| Deduplication | Upsert by `sourcePlatform + externalJobId` | Identity collision, repeated page overlap |
| Persistence | Write staging rows and sync batches | DB constraint error, partial batch rollback |
| Freshness | Mark seen jobs active and old jobs stale | Partial run must not expire source records |
| Quarantine | Store malformed raw records with safe errors | Quarantined records must not sync |
| Enrichment | Add skills/requirements from clean text | Model timeout or invalid output does not leak payload |
| Stage queue | Claim and complete eligible stage jobs | Failed jobs retry then dead-letter with correlation id retained |
| Documentation sync | Build deterministic bundle manifest | Missing metadata, bad link, path escape, secret pattern |

## Contract Tests

Source contract tests must verify:

- Payload root exists for each source.
- Required raw identity exists.
- Optional salary fields can be null.
- HTML fields are sanitized before normalized output.
- Relative labels are not used as canonical timestamps when timestamps exist.
- UI/noise fields do not reach Backend API-facing output.
- Glints list-first behavior works when no captured detail endpoint exists.
- Kalibrr `buildId` drift is handled as source fetch behavior, not mapper behavior.

Normalized contract tests must verify:

- `sourcePlatform + externalJobId` uniquely identifies a job.
- Title, company fallback, location/display text, source URL, and `lastSeenAt` are present when source data allows.
- Missing optional logo, salary, category, and skills do not fail the whole run.
- Raw source payload bodies do not leak into synced records.

Fixture coverage tests must also report, for every supported source:

- list fixture coverage.
- detail fixture coverage or documented list fallback.
- canonical mapper coverage.
- malformed payload coverage.
- fixture sanitization coverage.

## Smoke Tests

Minimum smoke checks:

| Check | Expected result |
| --- | --- |
| Startup env validation | Missing required config fails fast |
| Fixture pipeline | One fixture batch reaches normalized staging |
| Source health | Adapter health reports safe status without credentials |
| Sync dry-run | Sync validates shape without mutating production DB |
| Redaction | Logs and artifacts contain no token/cookie/session strings |
| Uvicorn local boot | ASGI app boots successfully from `src` module path |

## Local Verification Commands

Use the locked environment for routine validation:

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/unit
uv run pytest tests/contract
uv run pytest tests/integration
uv run pytest tests/smoke
uv run pytest
uv run python scripts/check_release_readiness.py
RUNTIME_ENV_FILE=.env.production.example docker compose --env-file .env.production.example config --no-env-resolution
```

Integration tests use isolated test databases. The default local integration baseline creates temporary SQLite databases, applies Alembic migrations, and then exercises repository writes and API reads against that migrated schema. This keeps routine verification safe when no PostgreSQL test instance is available.

```bash
uv run pytest tests/integration
```

Database-backed tests must not use development, staging, or production database URLs. When PostgreSQL-specific behavior is added, use a dedicated database whose name clearly identifies it as test-only, set `APP_ENV=test`, and keep `RUN_DATABASE_TESTS=true` explicit in the shell or env file used for that run.

Smoke checks are available through the scraper CLI and do not require external network access:

```bash
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage scrape
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --limit 1 --env-file .env.example
uv run pytest tests/smoke
```

Uvicorn local boot verification:

```bash
PYTHONPATH=src uv run uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8000
```

The automated smoke suite includes a runtime boot regression check:

```bash
uv run pytest tests/smoke/test_runtime_boot.py
```

The smoke dry-run command reads the sanitized Dealls fixture, parses the list payload, maps one job into the canonical schema, and prints a compact JSON result.

The pipeline command runs the local orchestrator with sanitized fixtures by default. It exercises scrape, normalize, enrichment staging, backend sync handoff preparation, and notification handoff preparation without external network access or production database mutation.

## CI Verification

The automated quality gate runs on push, pull request, and manual dispatch. It installs dependencies from `uv.lock`, checks formatting and linting, runs unit, contract, integration, and smoke suites, exercises the smoke CLI, and validates docs and artifact safety.

The CI workflow must not require source credentials, production database credentials, or live source network access. Optional external integration checks should stay separate until dedicated non-production credentials and isolated services exist.

For dependency visibility:

```bash
uv run python --version
uv tree --depth 1
```

## Current Automated Checks

The scraper test suite covers:

- Settings validation for required and conditional environment variables.
- JSON logging shape, correlation context, and sensitive field redaction.
- Pipeline error categories and retryability metadata.
- SQLAlchemy metadata for operational scraper tables.
- Database uniqueness for source platform plus external job identity.
- Alembic upgrade and downgrade on an isolated test database.
- Raw fixture sanitization and secret-pattern scanning.
- Source adapter contract parsing for Dealls, Glints, JobStreet, and Kalibrr.
- Source fixture coverage reporting across list, detail or fallback, mapper, malformed, and sanitization paths.
- Source HTTP retry classifier, per-source rate limiter isolation, capped backoff, and circuit breaker behavior.
- HTML cleaning for description and requirement fields.
- Canonical mapper output and field provenance for all supported sources.
- Alembic migration upgrade against isolated test databases before repository/API integration checks.
- Repository raw and normalized job upsert behavior against a migrated schema.
- Internal jobs API reads against a migrated isolated database.
- Backend sync client request contract using in-memory HTTP transport.
- OpenAI-compatible client boundary, custom base URL usage, structured output parsing, and classified provider errors.
- AI request audit logging stores request hashes and safe summaries without prompts, raw payloads, or secrets.
- Enrichment staging upsert behavior for skills and requirements.
- DB-backed stage queue retry, completion, and dead-letter behavior.
- CLI smoke checks for config, health, and fixture-backed dry-run behavior.
- Manual pipeline CLI dry-run, source/stage validation, status lookup, and output redaction.
- Release readiness checks for documentation metadata, local links, and secret-safe docs/fixtures/raw captures.

## Release Gate

A scraper release is not ready until:

- Unit tests pass for changed modules.
- Source contract fixture tests pass for all four sources.
- Normalized contract tests pass against Backend API expectations.
- Quarantine and freshness tests pass when mapper or freshness behavior changes.
- Persistence and sync tests pass against an isolated test DB when DB behavior changes.
- Smoke tests pass in target environment or staging.
- Redaction checks pass for docs, logs, fixtures, and generated artifacts.
- Documentation metadata and links are valid.
- CI quality gates pass from a clean checkout.

## Related Docs

- [Verification Matrix](./verification-matrix.md)
- [CI Quality Gates](./ci-quality-gates.md)
- [Release Readiness](./release-readiness.md)
- [Observability](./observability.md)
- [Raw Payload Contract](../references/raw-payload-contract.md)
- [Source Field Mapping Matrix](../references/source-field-mapping-matrix.md)
- [Payload Redaction Policy](../standards/payload-redaction-policy.md)
