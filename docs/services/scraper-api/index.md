---
title: Scraper API
description: Service boundary, responsibilities, and integration expectations for the Bisakerja Scraper API.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper API

The Scraper API collects external job data and adapts it into the normalized Bisakerja job catalog shape.

## Responsibilities

| Area | Scraper API owns |
| --- | --- |
| Source adapters | Dealls REST, Glints GraphQL, JobStreet GraphQL, Kalibrr Next.js data, Kitalulus GraphQL |
| Raw capture | Store source payloads for debug, replay, and mapper validation |
| Normalization | Map source fields to Backend API database-compatible job records |
| Deduplication | Use `sourcePlatform + externalJobId/slug/id` as source-local identity |
| Enrichment handoff | Prepare batches for skill extraction and requirement structuring |
| Sync preparation | Upsert-ready records for main Backend API database |

## Core References

- [Scraper API Reference](../../api-reference.md)
- [Scraper API Response Standard](../../api-response-standard.md)
- [Scraper Architecture](../../architecture.md)
- [Scraper Data Flow](../../overview/data-flow.md)
- [Scraper Service Interactions](../../overview/service-interactions.md)
- [Scraper API Contract](../../integrations/scraper-api-contract.md)
- [Scraper Database Design](../../database.md)
- [Scraper Environment Configuration](../../environment.md)
- [Scraper Security Operations](../../operations/security.md)
- [Scraper Observability](../../operations/observability.md)
- [Scraper Testing Strategy](../../operations/testing.md)
- [Scraper Deployment Operations](../../operations/deployment.md)
- [Scraper Documentation Sync](../../operations/documentation-sync.md)
- [Scraper Documentation Standards](../../standards/index.md)
- [Scraper Documentation Release Checklist](../../operations/documentation-release-checklist.md)

## Non-Responsibilities

| Area | Owner |
| --- | --- |
| User auth and sessions | Backend API |
| Bookmarks and application tracker | Backend API |
| Frontend rendering | Frontend UI |
| Model training and inference internals | Model API |
| Central documentation governance | Central docs repository |

## Implementation Shape

Current repository structure centers on `src/`:

```text
src/api -> internal HTTP routes and app factory
src/cli -> operator entrypoints and smoke/pipeline commands
src/integrations/sources -> per-source adapters
src/integrations/ai -> OpenAI-compatible client boundary
src/integrations/backend -> backend sync and notification clients
src/jobs -> pipeline orchestration and scheduler
src/modules -> persistence, enrichment, sync, queue, freshness, deduplication
```

Do not mix scraping, persistence, normalization, and sync logic in one module.

## Module Docs

- [Ingestion](../../modules/ingestion.md)
- [Parsing and Normalization](../../modules/parsing-normalization.md)
- [Deduplication](../../modules/deduplication.md)
- [Persistence](../../modules/persistence.md)
- [Freshness](../../modules/freshness.md)

## Operations Docs

- [Observability](../../operations/observability.md)
- [Failure Scenarios](../../operations/failure-scenarios.md)
- [Verification Matrix](../../operations/verification-matrix.md)
- [Deployment Overview](../../operations/deployment-overview.md)
- [Documentation Sync and Versioning](../../standards/documentation-sync-and-versioning.md)
- [Contribution Guide](../../standards/contribution-guide.md)
- [Review Process](../../standards/review-process.md)
- [Freshness and Lifecycle](../../standards/freshness-and-lifecycle.md)
- [Versioning and Audience Strategy](../../standards/versioning-and-audience-strategy.md)
