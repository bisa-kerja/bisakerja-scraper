# Bisakerja Scraper

Scraper service for Bisakerja job ingestion, normalization, enrichment, freshness tracking, and sync to backend-owned consumers.

The service collects external job data from supported sources, stores raw and staging records, normalizes jobs into a stable shape, enriches safe job fields, and prepares sync output for the Bisakerja Backend API boundary.

## Table of Contents

- [Overview](#overview)
- [Service Boundary](#service-boundary)
- [Pipeline](#pipeline)
- [Documentation Map](#documentation-map)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Environment Configuration](#environment-configuration)
- [Available Commands](#available-commands)
- [Testing And Verification](#testing-and-verification)
- [Container Runtime](#container-runtime)
- [Deployment Notes](#deployment-notes)
- [Project Structure](#project-structure)
- [Contribution Guide](#contribution-guide)

## Overview

Bisakerja Scraper is data ingestion service for external job platforms. It focuses on reliable collection, replayable raw data, deterministic parsing, deduplication, freshness control, and safe handoff to backend consumers.

This repository is responsible for:

- Source adapters for Dealls, Glints, JobStreet, Kalibrr, and Kitalulus
- Raw capture, staging persistence, normalization, enrichment, and sync preparation
- Scraper API health and internal job access endpoints
- Source contract tests, smoke flows, and dataset export tooling
- Scraper-owned documentation, docs sync bundle generation, and deployment support

This repository does not own:

- Frontend product rendering
- User auth, preferences, bookmarks, or application tracking
- Backend public REST contracts consumed by frontend
- Model training or low-level inference internals
- Central platform docs landing pages

## Service Boundary

| Service     | Responsibility                                                                  |
| ----------- | ------------------------------------------------------------------------------- |
| Frontend UI | User-facing discovery and application workflows                                 |
| Backend API | Auth, user workflows, product REST contracts, backend-owned DB access           |
| Scraper API | Source ingestion, raw/staging data, normalization, enrichment, sync preparation |
| Model API   | Fit scoring, explanations, and CV analysis                                      |
| PostgreSQL  | Durable storage for scraper and backend-owned records                           |

Frontend clients must not call Scraper API directly. Backend API stays product-facing boundary.

## Pipeline

Baseline daily flow:

```text
00:00 scrape
  -> 02:00 normalize
  -> 04:00 enrich
  -> 06:00 sync
  -> 08:00 notify handoff
```

Pipeline stages must keep raw and staging data replayable. Failed source runs must not expire unseen jobs.

## Documentation Map

Use this reading order when onboarding or reviewing changes:

1. `docs/intro.md` for scraper scope and docs entry point.
2. `docs/architecture.md` for system flow, module boundaries, and ownership.
3. `docs/api-reference.md` for internal API routes and contracts.
4. `docs/environment.md` for runtime variables and env rules.
5. `docs/database.md` for persistence model and ownership boundaries.
6. `docs/operations/testing.md` for test strategy and verification commands.
7. `docs/operations/deployment.md` for runtime and deployment assumptions.
8. `docs/operations/daily-pipeline-runbook.md` for operator flow.
9. `docs/modules/*.md` and `docs/references/*.md` for module-level and contract detail.

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

Run basic smoke checks:

```bash
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline quick-dry-run --source all --stage full --env-file .env.example
```

Apply migrations:

```bash
uv run alembic upgrade head
```

Start API:

```bash
PYTHONPATH=src uv run uvicorn api.app:create_app --factory --host 0.0.0.0 --port 3003
```

Default local API:

```text
http://localhost:3003
```

## Environment Configuration

Configuration uses `pydantic-settings` and fails fast when required values are missing or invalid.

Important files:

| File                      | Purpose                                              |
| ------------------------- | ---------------------------------------------------- |
| `.env.example`            | Local development baseline                           |
| `.env.production.example` | Deployment-oriented baseline for Compose/VPS runtime |

Important groups:

- Application: `APP_NAME`, `APP_ENV`, `PORT`, `API_PREFIX`
- Database: `SCRAPER_DATABASE_URL`, `BACKEND_DATABASE_URL`, `BACKEND_SYNC_ENABLED`
- Schedule: scrape, normalize, enrich, sync, notify handoff cron values
- Scrape plan: keywords, limits, recency mode, recency days
- Sources: Dealls, Glints, JobStreet, Kalibrr, Kitalulus settings
- Backend sync: base URL, service token, timeout, batch size, freshness thresholds
- AI provider: API key, base URL, model, enrichment and normalization batch settings
- Security and observability: internal token, CORS, body limit, log level, request id, health timeout

Do not commit real secrets, cookies, bearer tokens, source sessions, or DB credentials. Full env contract lives in `docs/environment.md`.

## Available Commands

| Command                                                                                                                                         | Purpose                            |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `uv sync --locked`                                                                                                                              | Install dependencies from lockfile |
| `uv run ruff format --check .`                                                                                                                  | Check formatting                   |
| `uv run ruff check .`                                                                                                                           | Run lint checks                    |
| `uv run pytest`                                                                                                                                 | Run full test suite                |
| `uv run alembic upgrade head`                                                                                                                   | Apply migrations                   |
| `PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example`                                                                      | Validate config loading            |
| `PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example`                                                                      | Validate app liveness wiring       |
| `PYTHONPATH=src uv run python -m cli.pipeline quick-dry-run --source all --stage full --env-file .env.example`                                  | Run default fixture-backed dry run |
| `PYTHONPATH=src uv run python -m cli.pipeline wizard`                                                                                           | Run operator wizard                |
| `PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 3 --run-id local-e2e-<timestamp> --execute --env-file .env` | Run controlled execute pipeline    |
| `PYTHONPATH=src uv run python -m cli.pipeline verify --run-id <run-id-prefix> --env-file .env`                                                  | Verify pipeline results            |
| `PYTHONPATH=src uv run python -m cli.pipeline staging-report --run-id <run-id-prefix> --env-file .env`                                          | Build operational report           |
| `PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --format multi-csv`                | Export dataset CSV                 |
| `PYTHONPATH=src uv run python -m cli.daemon --env-file .env.production`                                                                         | Run scheduled stage daemon         |

Primary operator path is `cli.pipeline wizard`. For command variants, dry-run behavior, execute behavior, and guardrails, see `docs/operations/daily-pipeline-runbook.md`.

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

Database-backed tests must use isolated local or CI databases. Never point tests at staging or production databases.

## Container Runtime

Build image:

```bash
docker build -t bisakerja-scraper:local .
```

Run with env file:

```bash
docker run --rm --env-file .env -p 3003:3003 bisakerja-scraper:local
```

Run Compose with published image:

```bash
APP_IMAGE=ghcr.io/bisa-kerja/bisakerja-scraper:develop \
RUNTIME_ENV_FILE=.env.production \
docker compose --env-file .env.production up -d
```

Compose runs `app` and `scheduler`. Runtime detail lives in `docs/operations/deployment.md`.

## Deployment Notes

Deployment workflow lives at:

```text
.github/workflows/deploy.yml
```

Deployment flow:

- build Docker image from committed source and `uv.lock`
- push branch and SHA tags to GHCR
- write deployment env file on VPS
- sync remote checkout to exact build SHA
- pull immutable image, run `alembic upgrade head`, start Compose services
- check `/health/live` and `/health/ready`

Required GitHub environment secrets:

| Secret                     | Purpose                         |
| -------------------------- | ------------------------------- |
| `DEPLOY_VPS_HOST`          | VPS host                        |
| `DEPLOY_VPS_PORT`          | SSH port                        |
| `DEPLOY_VPS_USERNAME`      | SSH user                        |
| `DEPLOY_VPS_KEY`           | Private SSH key                 |
| `DEPLOY_REMOTE_PATH`       | Existing remote repository path |
| `DEPLOY_ENV_FILE`          | Full `.env.production` payload  |
| `GHCR_READ_PACKAGES_TOKEN` | GHCR pull token for VPS         |
| `GH_USERNAME`              | GHCR username                   |

Documentation sync and deeper deployment troubleshooting live in `docs/operations/documentation-sync.md` and `docs/operations/deployment.md`.

## Project Structure

```text
.
|-- .github/workflows/
|-- docs/
|-- migrations/
|-- scripts/
|-- src/
|   |-- api/
|   |-- cli/
|   |-- config/
|   |-- core/
|   |-- integrations/
|   |-- jobs/
|   |-- modules/
|   `-- shared/
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

- read relevant docs in `docs/**`
- keep scraper boundary focused on ingestion, normalization, enrichment, freshness, and sync
- add focused tests for changed behavior
- update related docs and env examples in same change
- run release readiness before handoff

Before deployment:

- confirm required env values are present and non-empty
- keep source credentials in secret storage only
- run tests, smoke checks, and release readiness
- build image and apply migrations before serving traffic
