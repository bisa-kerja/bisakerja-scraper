---
title: Overview
description: Scraper documentation overview and reader paths for ingestion, normalization, and source-contract context.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Overview

This section gives top-down context for the Bisakerja Scraper service.

## Pages

- [Start Here](./start-here.md)
- [For Backend Engineers](./for-backend-engineers.md)
- [For Platform Engineers](./for-platform-engineers.md)
- [For Product Stakeholders](./for-product-stakeholders.md)
- [Glossary](./glossary.md)
- [System Landscape](./system-landscape.md)
- [Service Interactions](./service-interactions.md)
- [Authentication and Trust Boundaries](./authentication-and-trust-boundaries.md)
- [Data Flow](./data-flow.md)
- [Asynchronous Workflows](./asynchronous-workflows.md)
- [API Reference](../api-reference.md)
- [Scraper Modules](../modules/index.md)
- [Environment Configuration](../environment.md)
- [Security Operations](../operations/security.md)
- [Observability](../operations/observability.md)
- [Failure Scenarios](../operations/failure-scenarios.md)
- [Testing Strategy](../operations/testing.md)
- [Deployment](../operations/deployment.md)
- [Documentation Sync](../operations/documentation-sync.md)
- [Documentation Standards](../standards/index.md)
- [Documentation Release Checklist](../operations/documentation-release-checklist.md)
- [Future Docs Expansion](../roadmap/future-docs-expansion.md)

## Core Flow

```text
external job platforms
  -> Scraper API
  -> raw payload storage
  -> normalization
  -> AI enrichment handoff
  -> sync preparation
  -> main Backend API database
```

Baseline daily pipeline:

```text
01:00 scrape -> 01:30 normalize -> 02:00 enrich -> 03:00 sync -> 05:00-06:00 notify
```
