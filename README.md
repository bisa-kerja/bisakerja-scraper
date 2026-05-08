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
00:00 scrape
  -> 02:00 normalize
  -> 04:00 enrich
  -> 06:00 sync
  -> 08:00 notify handoff
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
PYTHONPATH=src uv run python -m cli.smoke dry-run --source glints
PYTHONPATH=src uv run python -m cli.smoke dry-run --source jobstreet
PYTHONPATH=src uv run python -m cli.smoke dry-run --source kalibrr
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls --stage scrape
PYTHONPATH=src uv run python -m cli.pipeline preflight --stage full --source all --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline wizard --dry-run --source dealls --stage scrape --limit 1 --env-file .env.example --yes
PYTHONPATH=src uv run python -m cli.pipeline quick-dry-run --source all --stage full --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --keywords developer,intern,ui/ux --limit 1 --latest --recency-days 7 --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --format multi-csv
```

The smoke dry-run command is fixture-backed and network-free. It validates parsing and mapping for Dealls, Glints, JobStreet, and Kalibrr fixtures. The pipeline command requires explicit mode: `--dry-run` or `--execute`.

`cli.dataset jobs-csv` exports CSV datasets from backend job-domain tables. Default output is multi-file (job listings, requirements, skills, user signals, model dataset, and dictionary). It also supports single-file flatten mode with a configured length guard.

Recommended operator entrypoint is `cli.pipeline wizard`. It shows an interactive menu for mode, stage, source, keyword preset, limit, recency, env file, and optional run id. It prints a pre-run summary with command equivalent, redacted DB target, backend sync mode, expected mutation scope, and risk indicators.

Wizard guard rules:

- Risk confirmation gate requires exact `YES` for execute mode and other risky combinations.
- Non-TTY wizard usage is allowed only for safe dry-run with `--yes`.
- Non-TTY wizard must reject risky runs (`APP_ENV=staging|production`, backend sync enabled, and other flagged risks).

`cli.pipeline run --execute` has two sync modes:

- When `BACKEND_SYNC_ENABLED=false`, sync and notification handoff use recording clients (no outbound backend API mutation).
- When `BACKEND_SYNC_ENABLED=true`, sync and notification handoff use real backend API clients with `BACKEND_SYNC_BASE_URL` and `BACKEND_SYNC_SERVICE_TOKEN`.
- Live backend mode calls `POST /api/v1/internal/scraper/jobs` and `POST /api/v1/internal/notification-events`; `BACKEND_SYNC_SERVICE_TOKEN` must match Backend API `SCRAPER_API_SERVICE_TOKEN`.
- Large runs are split into backend-safe chunks: sync uses `BACKEND_SYNC_BATCH_SIZE` with a maximum of `100` jobs per request, and notification handoff uses candidate chunks with a maximum of `1000` candidates per request.

Recommended controlled local execute sequence:

```bash
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env
uv run alembic upgrade head
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 3 --run-id local-e2e-$(date +%Y%m%d-%H%M%S) --execute --env-file .env
PYTHONPATH=src uv run python -m cli.pipeline verify --run-id <run-id-prefix> --env-file .env
PYTHONPATH=src uv run python -m cli.pipeline staging-report --run-id <run-id-prefix> --env-file .env
```

Use a unique `--run-id` for each execute run. A repeated run id causes primary-key collisions on stage run rows (`<run-id>-scrape`, `<run-id>-normalize`, and so on).

Start the API:

```bash
PYTHONPATH=src uv run uvicorn api.app:create_app --factory --host 0.0.0.0 --port 3003
```

Default local API:

```text
http://localhost:3003
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
- Scrape plan: `SCRAPER_KEYWORDS`, `SCRAPER_MAX_ITEMS_PER_KEYWORD`, `SCRAPER_MAX_ITEMS_PER_SOURCE_RUN`, `SCRAPER_MAX_PAGES_PER_KEYWORD`, `SCRAPER_TARGET_TOTAL_JOBS_PER_RUN`, `SCRAPER_RECENCY_MODE`, `SCRAPER_RECENCY_DAYS`
- Sources: Dealls, Glints, JobStreet, and Kalibrr settings
- Backend sync: base URL, service token, timeout, batch size, freshness thresholds
- AI provider: OpenAI-compatible API key, base URL, model, enrichment batch settings, normalization batch settings, and fixed inter-batch delay
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
| `PYTHONPATH=src uv run python -m cli.smoke dry-run --source <dealls|glints|jobstreet|kalibrr> --stage scrape` | Run fixture-backed smoke dry-run for one source and one stage |
| `PYTHONPATH=src uv run python -m cli.pipeline preflight --stage full --source all --dry-run --env-file .env.example` | Validate env, migration target, source enablement, fixture availability, backend sync mode, and safe redacted evidence preview |
| `PYTHONPATH=src uv run python -m cli.pipeline wizard` | Interactive operator wizard for run/status/verify/staging-report with validation and risk confirmation |
| `PYTHONPATH=src uv run python -m cli.pipeline wizard --dry-run --source dealls --stage scrape --limit 1 --env-file .env.example --yes` | Non-interactive safe wizard dry-run for CI-like checks |
| `PYTHONPATH=src uv run python -m cli.pipeline quick-dry-run --source all --stage full --env-file .env.example` | Short command for default safe fixture dry-run |
| `PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --dry-run --env-file .env.example` | Run offline fixture-backed manual pipeline |
| `PYTHONPATH=src uv run python -m cli.pipeline run --stage scrape --source dealls --keywords developer,intern,ui/ux --limit 1 --latest --recency-days 7 --dry-run --env-file .env.example` | Run multi-keyword latest scrape dry-run |
| `PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 3 --run-id local-e2e-<timestamp> --execute --env-file .env` | Run controlled execute pipeline (real source fetch and DB writes; backend sync/handoff real only when `BACKEND_SYNC_ENABLED=true`) |
| `PYTHONPATH=src uv run python -m cli.pipeline status --run-id <run-id> --env-file .env` | Read safe run status from the configured DB |
| `PYTHONPATH=src uv run python -m cli.pipeline verify --run-id <run-id-prefix> --env-file .env` | Verify stage rows, counts, duplicate identities, and safe metadata |
| `PYTHONPATH=src uv run python -m cli.pipeline staging-report --run-id <run-id-prefix> --env-file .env` | Build operational report with latency, retry, consistency, and backend-read evidence |
| `PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --format multi-csv` | Export job intelligence CSV datasets for analytics and model workflows |
| `PYTHONPATH=src uv run python -m cli.daemon --env-file .env.production` | Run scheduled stage daemon (scrape, normalize, enrich, sync, notify-handoff) |

`cli.smoke dry-run` validates one source fixture path per command across all supported sources. `cli.pipeline preflight` provides a read-only local readiness check before operator runs. `cli.pipeline wizard` is the primary operator path and always returns machine-readable JSON while still guiding interactive choices. `cli.pipeline run` remains available for explicit scripted flows. `--dry-run` uses sanitized fixtures with in-memory DB and can validate JobStreet fixture flow even when `JOBSTREET_ENABLED=false` for live mode. Keyword flags override `SCRAPER_KEYWORDS`; otherwise the env list is used. `--limit` applies per keyword. Add `--execute` only for an operator-controlled environment with a migrated, non-production database.

Execute mode behavior:

- `--execute` always uses configured source endpoints and configured scraper database.
- Enrichment stage with `AI_ENRICHMENT_ENABLED=true` uses OpenAI structured output and persists AI request logs.
- Enrichment stage with `AI_ENRICHMENT_ENABLED=false` still persists enrichment staging rows from normalized source fields (no outbound AI call).
- Normalize stage uses serial AI batch normalization with per-item partial handling. Batch size and fixed delay are controlled by `OPENAI_NORMALIZATION_BATCH_SIZE` and `OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS`.
- `--execute` with `BACKEND_SYNC_ENABLED=false` keeps backend sync/handoff local (recording clients).
- `--execute` with `BACKEND_SYNC_ENABLED=true` sends sync payloads to Backend API and sends notification handoff payloads to Backend API. Sync batches are capped at `100` jobs to match the Backend API internal endpoint.
- A run can sync `1000`-`2000` total jobs when multiple source/keyword fan-out items produce that many rows; the scraper will send multiple backend requests instead of dropping overflow rows.
- Execute runs stream stage and job progress logs to `stderr` while preserving JSON result output on `stdout`.

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
PYTHONPATH=src uv run uvicorn api.app:create_app --factory --host 127.0.0.1 --port 3003
```

## Container Runtime

Build the image:

```bash
docker build -t bisakerja-scraper:local .
```

Run with an env file:

```bash
docker run --rm --env-file .env -p 3003:3003 bisakerja-scraper:local
```

Run Compose with a published image:

```bash
APP_IMAGE=ghcr.io/bisa-kerja/bisakerja-scraper:develop \
RUNTIME_ENV_FILE=.env.production \
docker compose --env-file .env.production up -d
```

This Compose setup runs two services:

- `app`: Uvicorn API container.
- `scheduler`: APScheduler daemon container (`python -m cli.daemon`) that triggers pipeline stages automatically by cron.

The app image runs as a non-root user and checks `/health/live`.

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
- Starts app and scheduler through Docker Compose.
- Checks `/health/live` and `/health/ready` with retry windows during warm-up.
- Collects Compose logs on failure.

Current deploy runtime behavior:

- `app` serves HTTP (`/health/live`, `/health/ready`, internal jobs routes).
- `scheduler` runs cron-driven stage automation using `SCRAPE_SCHEDULE_CRON`, `NORMALIZE_SCHEDULE_CRON`, `ENRICH_SCHEDULE_CRON`, `SYNC_SCHEDULE_CRON`, and `NOTIFY_HANDOFF_SCHEDULE_CRON`.
- Scheduler execute mode uses live source endpoints and scraper DB writes.
- Backend mutation is controlled by `BACKEND_SYNC_ENABLED`:
  - `true`: sync and notification handoff call backend internal endpoints.
  - `false`: sync and notification handoff stay local via recording clients.
- Scheduled stage run IDs are deterministic per day (`scheduled-YYYYMMDD-<stage>`). Repeated trigger is skipped only when that stage already completed for the day; failed/partial rows use retry IDs (`scheduled-YYYYMMDD-<stage>-retry-XX`).

If deployment fails with database connection errors like `password authentication failed for user 'neondb_owner'`, rotate or correct the database secret in `DEPLOY_ENV_FILE` first, then redeploy. IPv6 `Network is unreachable` entries from Neon can appear alongside the real auth failure; treat failed IPv4 password authentication as the primary root cause when both are present.

Neon runtime compatibility is normalized automatically:

- runtime async checks use `postgresql+asyncpg`
- CLI/deploy sync checks use `postgresql+psycopg`
- Neon URLs enforce `sslmode=require` when absent
- async runtime removes `channel_binding` query parameter to avoid asyncpg startup-parameter conflicts

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
