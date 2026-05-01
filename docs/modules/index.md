---
title: Scraper Modules
description: Entry point for scraper ingestion, parsing, deduplication, persistence, and freshness module documentation.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Modules

Scraper modules follow the existing adapter, pipeline, repository, and worker split.

## Pages

- [Ingestion](./ingestion.md)
- [Parsing and Normalization](./parsing-normalization.md)
- [Deduplication](./deduplication.md)
- [Persistence](./persistence.md)
- [Freshness](./freshness.md)

## Rule

Keep source fetching, normalization, persistence, enrichment, sync, and freshness decisions separated by module boundary.

