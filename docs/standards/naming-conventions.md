---
title: Naming Conventions
description: Naming, slug, and path conventions for scraper-owned documentation and source identifiers.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Naming Conventions

## File And Directory Rules

- Use lowercase kebab-case.
- Use `index.md` only for section landing pages.
- Put scraper source contracts under `docs/integrations/sources/` when added.
- Put shared field matrices under `docs/references/`.
- Put standards under `docs/standards/`.

## Stable Service Names

| Name | Use |
| --- | --- |
| Frontend UI | User-facing web client |
| Backend API | Application API and user workflow owner |
| Scraper API | Job ingestion and normalization service |
| Model API | AI inference service |

## Stable Source Slugs

| Source | Slug |
| --- | --- |
| Dealls | `dealls` |
| Glints | `glints` |
| JobStreet | `jobstreet` |
| Kalibrr | `kalibrr` |

## Identity Naming

Use `externalJobId` as the normalized field name even when the source provides:

- Dealls `id` or `slug`.
- Glints `id`.
- JobStreet numeric `id`.
- Kalibrr numeric `id` or `slug`.

The deduplication key is:

```text
sourcePlatform + externalJobId
```

Do not rename this key without a migration plan.

