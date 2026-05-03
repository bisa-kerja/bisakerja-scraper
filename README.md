# Bisakerja Scraper

Scraper service for Bisakerja job ingestion, normalization, enrichment, freshness tracking, and sync to backend-owned consumers.

The service collects external job data from supported sources, stores raw and staging records, normalizes jobs into a stable shape, enriches safe job fields, and prepares sync output for the Bisakerja Backend API boundary.

## Table of Contents

- [Overview](#overview)
- [Service Boundary](#service-boundary)
- [Pipeline](#pipeline)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Environment Configuration](#environment-configuration)
- [Available Commands](#available-commands)
- [Testing And Verification](#testing-and-verification)
- [Container Runtime](#container-runtime)
- [Deployment](#deployment)
- [Documentation Sync](#documentation-sync)
- [Project Structure](#project-structure)
- [Contribution Guide](#contribution-guide)

## Overview

Bisakerja Scraper is the data ingestion service for external job platforms. It focuses on reliable collection, replayable raw data, deterministic parsing, deduplication, freshness control, and safe handoff to backend consumers.

This repository owns:

- Source adapters for Dealls, Glints, JobStreet, and Kalibrr.
- Raw fixture sanitization and source contract tests.
- Parsing, normalization, deduplication, persistence, enrichment, and sync logic.
- Scraper API health and internal job access endpoints.
- Scraper-owned operational docs and docs sync bundle generation.
- Docker and GitHub Actions deployment support.

This repository does not own:

- Frontend product rendering.
- User authentication, preferences, bookmarks, or application tracking.
- Backend public REST contracts consumed by the frontend.
- Model training or low-level inference internals.
- Central platform docs landing pages.

## Service Boundary

| Service     | Responsibility                                                                  |
| ----------- | ------------------------------------------------------------------------------- |
| Frontend UI | User-facing discovery and application workflows                                 |
| Backend API | Auth, user workflows, product REST contracts, backend-owned DB access           |
| Scraper API | Source ingestion, raw/staging data, normalization, enrichment, sync preparation |
| Model API   | Fit scoring, explanations, and CV analysis                                      |
| PostgreSQL  | Durable storage for scraper and backend-owned records                           |

Frontend clients must not call Scraper API directly. Backend API is the product-facing API boundary.

## Pipeline

Baseline daily flow:

```text
01:00 scrape
  -> 01:30 normalize
  -> 02:00 enrich
  -> 03:00 sync
  -> 05:00-06:00 notify handoff
```

Pipeline stages must keep raw/staging data replayable. Failed source runs must not expire unseen jobs.

## Tech Stack

| Area                   | Choice                   |
| ---------------------- | ------------------------ |
| Runtime                | Python `>=3.12`          |
| Package manager        | `uv`                     |
| HTTP framework         | FastAPI                  |
| Database               | PostgreSQL               |
| Migrations             | Alembic                  |
| ORM                    | SQLAlchemy               |
| Scheduling             | APScheduler              |
| HTTP client            | HTTPX                    |
| Parsing                | Selectolax               |
| AI client              | OpenAI-compatible client |
| Testing                | Pytest                   |
| Formatting and linting | Ruff                     |
| Container              | Docker                   |

## Getting Started

Install dependencies:

```bash
uv sync --locked
```

Create local env:

```bash
cp .env.example .env
```

Run tests:

```bash
uv run pytest
```

Run smoke checks:

```bash
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage scrape
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --env-file .env.example
```

The smoke dry-run command is fixture-backed and network-free. It validates parsing and mapping for a bounded Dealls fixture only. The pipeline command runs the local orchestrator against sanitized fixtures and an in-memory database by default.

Start the API:

```bash
PYTHONPATH=src uv run uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Default local API:

```text
http://localhost:8000
```

## Environment Configuration

Configuration is loaded with `pydantic-settings` and fails fast when required values are missing or invalid.

Important files:

| File                      | Purpose                                              |
| ------------------------- | ---------------------------------------------------- |
| `.env.example`            | Local development baseline                           |
| `.env.production.example` | Deployment-oriented baseline for Compose/VPS runtime |

Important groups:

- Application: `APP_NAME`, `APP_ENV`, `PORT`, `API_PREFIX`
- Database: `SCRAPER_DATABASE_URL`, `BACKEND_DATABASE_URL`, `BACKEND_SYNC_ENABLED`
- Schedule: scrape, normalize, enrich, sync, and notify handoff cron values
- Sources: Dealls, Glints, JobStreet, and Kalibrr settings
- Backend sync: base URL, service token, timeout, batch size, freshness thresholds
- AI enrichment: OpenAI-compatible API key, base URL, model, batch settings
- Security: internal token, CORS, body limit, rate limits
- Observability: log level, request id header, health timeout

Do not commit real secrets, cookies, bearer tokens, source sessions, or database credentials.

## Available Commands

| Command                                             | Purpose                                    |
| --------------------------------------------------- | ------------------------------------------ |
| `uv sync --locked`                                  | Install dependencies from lockfile         |
| `uv run ruff format --check .`                      | Check formatting                           |
| `uv run ruff check .`                               | Run lint checks                            |
| `uv run pytest tests/unit`                          | Run unit tests                             |
| `uv run pytest tests/contract`                      | Run source contract tests                  |
| `uv run pytest tests/integration`                   | Run integration tests                      |
| `uv run pytest tests/smoke`                         | Run smoke tests                            |
| `uv run pytest`                                     | Run full test suite                        |
| `uv run alembic upgrade head`                       | Apply migrations                           |
| `uv run alembic downgrade base`                     | Roll back migrations                       |
| `uv run python scripts/deploy/db_preflight.py --env-file .env.production.example` | Validate deployment DB preflight output safety |
| `uv run python scripts/sanitize_raw_fixtures.py`    | Sanitize raw fixtures                      |
| `uv run python scripts/check_release_readiness.py`  | Validate docs, links, and unsafe artifacts |
| `uv run python scripts/prepare_docs_sync_bundle.py` | Build central-docs sync bundle             |
| `PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example` | Validate config loading |
| `PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example` | Validate app liveness wiring |
| `PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage scrape` | Run fixture-backed smoke dry-run for one stage |
| `PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --env-file .env.example` | Run offline fixture-backed manual pipeline |
| `PYTHONPATH=src uv run python -m cli.pipeline status --run-id <run-id> --env-file .env` | Read safe run status from the configured DB |

`cli.smoke dry-run` validates a narrow Dealls fixture path. `cli.pipeline run` executes the local orchestrator with sanitized fixtures by default and prints compact JSON without secrets or raw payload bodies. Add `--execute` only for an operator-controlled environment with a migrated, non-production database.

## Testing And Verification

Fast local verification:

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/unit
uv run pytest tests/contract
uv run pytest tests/integration
uv run pytest tests/smoke
uv run python scripts/check_release_readiness.py
```

Database-backed tests must use isolated local or CI database targets. Never point tests at staging or production databases.

For local runtime boot checks without Docker:

```bash
PYTHONPATH=src uv run uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8000
```

## Container Runtime

Build the image:

```bash
docker build -t bisakerja-scraper:local .
```

Run with an env file:

```bash
docker run --rm --env-file .env -p 8000:8000 bisakerja-scraper:local
```

Run Compose with a published image:

```bash
APP_IMAGE=ghcr.io/bisa-kerja/bisakerja-scraper:develop \
RUNTIME_ENV_FILE=.env.production \
docker compose --env-file .env.production up -d
```

The image runs Uvicorn as a non-root user and checks `/health/live`.

Render Compose config safely from example env:

```bash
RUNTIME_ENV_FILE=.env.production.example docker compose --env-file .env.production.example config --no-env-resolution
```

## Deployment

Deployment workflow lives at:

```text
.github/workflows/deploy.yml
```

The workflow:

- Builds the Docker image from committed source and `uv.lock`.
- Pushes branch and SHA tags to GHCR.
- Writes the configured deployment env file on the VPS.
- Syncs the remote checkout to the exact build commit SHA.
- Pulls the immutable SHA-tagged image from the same build run.
- Runs `alembic upgrade head`.
- Starts the app through Docker Compose.
- Checks `/health/live` and `/health/ready`.
- Collects Compose logs on failure.

If deployment fails with database connection errors like `password authentication failed for user 'neondb_owner'`, rotate or correct the database secret in `DEPLOY_ENV_FILE` first, then redeploy. IPv6 `Network is unreachable` entries from Neon can appear alongside the real auth failure; treat failed IPv4 password authentication as the primary root cause when both are present.

Required GitHub environment secrets:

| Secret                     | Purpose                         |
| -------------------------- | ------------------------------- |
| `DEPLOY_VPS_HOST`          | VPS host                        |
| `DEPLOY_VPS_PORT`          | SSH port                        |
| `DEPLOY_VPS_USERNAME`      | SSH user                        |
| `DEPLOY_VPS_KEY`           | Private SSH key                 |
| `DEPLOY_REMOTE_PATH`       | Existing remote repository path |
| `DEPLOY_ENV_FILE`          | Full `.env.production` payload  |
| `GHCR_READ_PACKAGES_TOKEN` | GHCR pull token for the VPS     |
| `GH_USERNAME`              | GHCR username                   |

Remote prerequisites:

- `git`, `docker`, Docker Compose, and `curl` are installed.
- Deploy user can run Docker and write inside `DEPLOY_REMOTE_PATH`.
- `DEPLOY_REMOTE_PATH` is a clean checkout of this repository.
- Runtime env uses `APP_ENV=staging` for the active staging workflow.

## Documentation Sync

CI auto-syncs scraper docs to the central docs repository after quality gates pass on `develop` or `main`.

Sync workflow:

1. Validate code, tests, smoke checks, and release readiness.
2. Generate `.tmp/docs-sync`.
3. Convert `docs/**/*.md` to `.mdx`.
4. Rewrite local `.md` links to `.mdx`.
5. Add `manifest.json`.
6. Publish to `docs/services/scraper-api/synced` in `bisa-kerja/bisakerja-docs`.

Required secret:

| Secret            | Purpose                                              |
| ----------------- | ---------------------------------------------------- |
| `DOCS_REPO_TOKEN` | Token allowed to push to the central docs repository |

Central service landing pages remain central-owned and are not overwritten by scraper sync.

## Project Structure

```text
.
|-- .github/workflows/
|-- docs/
|-- migrations/
|-- scripts/
|   |-- deploy/
|   |-- check_release_readiness.py
|   |-- prepare_docs_sync_bundle.py
|   `-- sanitize_raw_fixtures.py
|-- src/
|   |-- api/
|   |-- cli/
|   |-- config/
|   |-- core/
|   `-- modules/
|-- tests/
|   |-- contract/
|   |-- integration/
|   |-- smoke/
|   `-- unit/
|-- docker-compose.yml
|-- Dockerfile
|-- pyproject.toml
`-- uv.lock
```

## Contribution Guide

Before changing behavior:

- Read the relevant docs in `docs/**`.
- Keep scraper boundaries focused on ingestion, normalization, enrichment, freshness, and sync.
- Add focused tests for changed behavior.
- Update related docs and env examples in the same change.
- Run release readiness before handoff.

Before deployment:

- Confirm required env values are present and non-empty.
- Confirm source credentials are in secret storage only.
- Run tests, smoke checks, and release readiness.
- Build the container image.
- Apply migrations before serving traffic.
