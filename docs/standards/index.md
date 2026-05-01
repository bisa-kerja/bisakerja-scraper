---
title: Standards
description: Scraper documentation standards for metadata, naming, review, lifecycle, sync, and source payload safety.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Standards

Scraper docs follow the central docs standards, scoped to this repository.

## Pages

- [Metadata Standard](./metadata-standard.md)
- [Naming Conventions](./naming-conventions.md)
- [Payload Redaction Policy](./payload-redaction-policy.md)
- [Contribution Guide](./contribution-guide.md)
- [Review Process](./review-process.md)
- [Structural Change Policy](./structural-change-policy.md)
- [Freshness and Lifecycle](./freshness-and-lifecycle.md)
- [Documentation Health Metrics](./documentation-health-metrics.md)
- [Archival Strategy](./archival-strategy.md)
- [Documentation Sync and Versioning](./documentation-sync-and-versioning.md)
- [Versioning and Audience Strategy](./versioning-and-audience-strategy.md)

## Rules

- Keep docs standalone.
- Keep source-specific implementation detail in scraper-owned docs.
- Link to Backend API docs only for consumer contracts and database expectations.
- Never publish raw cookies, bearer tokens, session ids, or tracking identifiers.
- Generated references must be clearly labeled and free from real source credentials.
- Sync output must preserve scraper service ownership and publish only into scraper service targets.
- Major docs changes must follow the review matrix and structural change policy.
- Stale, deprecated, or archived pages must keep owner and replacement context.
