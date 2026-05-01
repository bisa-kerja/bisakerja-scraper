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
uv run python --version
uv tree
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

## Configuration

Configuration is loaded by `pydantic-settings` from environment variables and optional `.env` files. Required values must be explicit and non-empty. Missing required values fail during settings creation before runtime work starts.
