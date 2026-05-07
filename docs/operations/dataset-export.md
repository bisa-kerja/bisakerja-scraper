---
title: Dataset Export Operations
description: Operational guide for exporting job intelligence CSV datasets from backend job-domain tables.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-08
---

# Dataset Export Operations

Use this guide to generate CSV datasets for analytics and AI workflows.

## Prerequisites

- `BACKEND_DATABASE_URL` is configured and reachable.
- target output directory is writable.
- schema tables for job-domain and signal-domain data exist.

## Standard Export

```bash
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --format multi-csv
```

## Common Variants

Export only one source and one status:

```bash
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --source dealls --status active
```

Export with bounded row scope:

```bash
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --limit 500 --updated-since 2026-05-01T00:00:00Z
```

Export without model file:

```bash
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --no-include-model-dataset
```

Export single-file mode with flatten guard:

```bash
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --format single-csv --single-file-max-flat-chars 20000
```

## Expected Output

The command prints compact JSON with:

- filter summary.
- row counts per dataset file.
- list of written file paths.

## Failure Signals

Command exits with fail status when:

- backend database URL is missing.
- output directory is not writable.
- backend query fails.
- single-file flatten text exceeds configured safety limit.
