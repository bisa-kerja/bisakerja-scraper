# Bisakerja Scraper

Scraper service for job ingestion, normalization, enrichment, and sync to Bisakerja backend-owned consumers.

## Runtime

- Python `>=3.12`
- Package manager: `uv`
- Lockfile: `uv.lock`

## Setup

```bash
uv sync --locked
cp .env.example .env
uv run pytest
```

## Verification

```bash
uv sync --locked
uv run python --version
uv tree
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/unit
uv run pytest tests/contract
uv run pytest tests/integration
uv run pytest tests/smoke
uv run pytest
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls
uv run python scripts/check_release_readiness.py
```

The release readiness check validates docs metadata, local docs links, fixtures, raw captures, and example env placeholders for common secret patterns.

## Database Migrations

```bash
uv run alembic upgrade head
uv run alembic downgrade base
```

Migrations use `SCRAPER_DATABASE_URL` unless an explicit Alembic URL override is provided.

## Container Runtime

```bash
docker build -t bisakerja-scraper:local .
docker run --rm --env-file .env -p 8000:8000 bisakerja-scraper:local
```

The image runs Uvicorn as a non-root user and checks `/health/live` for container health.

## Raw Fixture Sanitization

```bash
uv run python scripts/sanitize_raw_fixtures.py
```

Sanitized fixtures are written to `tests/fixtures/raw/<source>/` and are checked by tests for common token, cookie, session, visitor, and device leaks.

## Continuous Integration

GitHub Actions runs locked dependency sync, Ruff format and lint gates, unit tests, contract tests, isolated integration tests, smoke tests, smoke CLI checks, and release readiness checks.

## Configuration

Configuration is loaded by `pydantic-settings` from environment variables and optional `.env` files. Required values must be explicit and non-empty. Missing required values fail during settings creation before runtime work starts.
