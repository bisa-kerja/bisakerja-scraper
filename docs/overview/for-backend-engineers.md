---
title: For Backend Engineers
description: Role path for backend engineers consuming normalized job data from the Bisakerja Scraper service.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# For Backend Engineers

This path is for engineers validating how scraper output becomes Backend API-readable job data.

## Read In This Order

1. [Scraper Alignment](../roadmap/alignment.md)
2. [Scraper API](../services/scraper-api/index.md)
3. [Glossary](./glossary.md)
4. [Naming Conventions](../standards/naming-conventions.md)
5. [References](../references/index.md)

## What To Check

- Backend API reads normalized records, not raw source payloads.
- `sourcePlatform + externalJobId` stays stable for bookmarks, tracker links, and AI context.
- Missing salary, partial location, and optional company logo must not break job responses.
- Raw HTML must be sanitized before any user-facing or model-facing use.
- JobStreet auth material and all source cookies must never enter docs or logs.

## Boundary

Backend API does not own external scraping, parser drift, source throttling, or raw payload shape. It owns user-facing response mapping and workflow authorization.

