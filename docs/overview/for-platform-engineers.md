---
title: For Platform Engineers
description: Role path for platform engineers operating scraper schedules, reliability, and documentation hygiene.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# For Platform Engineers

This path is for engineers responsible for scraper reliability, schedules, and operational review.

## Read In This Order

1. [Start Here](./start-here.md)
2. [Operations](../operations/index.md)
3. [Scraper Alignment](../roadmap/alignment.md)
4. [Metadata Standard](../standards/metadata-standard.md)
5. [Naming Conventions](../standards/naming-conventions.md)

## What To Check

- Daily schedule follows `scrape -> normalize -> enrich -> sync -> notify`.
- Source failures degrade one platform without breaking existing job data.
- Kalibrr `buildId` discovery is monitored because it is dynamic.
- JobStreet credential expiry is treated as operational configuration, not documented static data.
- Documentation examples are sanitized before review.

## Boundary

Platform engineers maintain operational safety and docs structure. They do not redefine source mapping or normalized schema without data-ingestion and backend review.

