---
title: Bisakerja Scraper Documentation
description: Entry point for scraper-owned documentation covering ingestion, normalization, source contracts, and operational boundaries.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Bisakerja Scraper Documentation

This documentation covers only the Bisakerja Scraper service. It does not replace the central platform docs or Backend API service docs.

## Read First

1. [Start Here](./overview/start-here.md)
2. [Alignment](./roadmap/alignment.md)
3. [Scraper API Service](./services/scraper-api/index.md)
4. [Scraper Architecture](./architecture.md)
5. [API Reference](./api-reference.md)
6. [Integrations](./integrations/index.md)
7. [Database Design](./database.md)
8. [Environment Configuration](./environment.md)
9. [Scraper Modules](./modules/index.md)
10. [Operations](./operations/index.md)
11. [Security](./operations/security.md)
12. [Testing Strategy](./operations/testing.md)
13. [Deployment](./operations/deployment.md)
14. [Documentation Sync](./operations/documentation-sync.md)
15. [Documentation Standards](./standards/index.md)
16. [Documentation Release Checklist](./operations/documentation-release-checklist.md)
17. [Future Docs Expansion](./roadmap/future-docs-expansion.md)
18. [Glossary](./overview/glossary.md)

## Scraper Boundary

The Scraper service owns external job source collection, raw payload retention, source-specific adapters, normalization, enrichment handoff, deduplication, and sync preparation.

The Backend API owns user workflows, authentication, authorization, user-owned records, and frontend-facing API responses.

## MVP Focus

MVP documentation prioritizes:

- Daily ingestion pipeline.
- Dealls, Glints, JobStreet, and Kalibrr source contract reality.
- Raw-to-normalized job field handling.
- Source-local identity and deduplication.
- Sanitized documentation examples with no credentials, cookies, session ids, or bearer tokens.
- Internal interface contracts, environment config, modules, and security gates.
- Observability, failure triage, testing, deployment, recovery, and docs sync gates.
- Contribution, review, lifecycle, health, versioning, archival, and release readiness governance.
