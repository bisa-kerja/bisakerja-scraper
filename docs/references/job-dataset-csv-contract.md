---
title: Job Dataset CSV Contract
description: Contract for job intelligence CSV exports used for product analytics, AI feature engineering, and quality monitoring.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-08
---

# Job Dataset CSV Contract

This reference defines the CSV export contract produced by the dataset CLI.

## CLI Command

```bash
PYTHONPATH=src uv run python -m cli.dataset jobs-csv --env-file .env --output-dir ./artifacts/datasets/jobs --format multi-csv
```

## Output Files

Default mode (`--format multi-csv`) writes:

- `job_listings_dataset.csv`
- `job_requirements_dataset.csv`
- `job_skills_dataset.csv`
- `job_user_signals_dataset.csv`
- `job_ai_model_training_dataset.csv` (when `--include-model-dataset` is enabled)
- `dataset_dictionary.csv`

Optional mode (`--format single-csv`) writes one additional file:

- `job_listings_single_dataset.csv`

## Core Rules

- CSV encoding: UTF-8.
- Datetime fields: ISO 8601 UTC.
- Enum fields: canonical uppercase values.
- Missing text and nullable numeric values: empty string.
- Aggregate counters: `0`.
- Output headers: deterministic and stable.

## Privacy Guard

Exported datasets must not include personal identifiers such as:

- `user_id`
- email address
- phone number
- CV raw text
- personal notes

User and AI behavior signals are represented only as anonymous aggregate values per job listing.

## Filtering Options

Supported filters:

- `--source` (`all`, `dealls`, `glints`, `jobstreet`, `kalibrr`, `kitalulus`)
- `--status` (`all`, `active`, `stale`, `expired`)
- `--limit`
- `--updated-since`
- `--timezone`

Signal switches:

- `--include-ai-signals` / `--no-include-ai-signals`
- `--include-user-signals` / `--no-include-user-signals`
- `--include-model-dataset` / `--no-include-model-dataset`

## Model Dataset Focus

`job_ai_model_training_dataset.csv` uses one row per job listing and includes:

- model input text context columns.
- labels for work type, employment type, experience level, role family, and salary bucket.
- requirement and skill JSON columns for multi-label and extraction tasks.
- feature-vector-style JSON columns for fit scoring and skill-gap modeling.
- weak labels for recommendation baseline and quality tiers.
- XAI evidence fields and evaluation rubric fields.
- deterministic split metadata (`train`, `validation`, `test`) with stable split grouping.

## Related Files

- `src/cli/dataset.py`
- `tests/smoke/test_dataset_cli.py`
- `backend-references/prisma/schema.prisma`
