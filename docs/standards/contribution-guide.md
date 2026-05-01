---
title: Contribution Guide
description: Contribution paths for scraper-owned documentation, synced docs, generated references, and governance changes.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Contribution Guide

Scraper documentation changes must preserve service ownership. This repository owns scraper-specific ingestion, adapter, normalization, deduplication, enrichment, sync, and operations docs.

## Contribution Paths

| Path | Use for | Owner | Review gate |
| --- | --- | --- | --- |
| Direct edit | Scraper-owned docs under `docs/**` | `data-ingestion-owner` | Required reviewers by change type |
| Generated reference refresh | Machine-derived routes, schemas, sync readiness reports | `data-ingestion-owner` | Regeneration evidence and validation |
| Central sync publish | Publishing scraper docs into central docs | `platform-docs-maintainer` with scraper source owner | Sync validation and central path check |
| Source reference update | Changes to root source-contract docs or raw captures | `data-ingestion-owner` | Sanitization and scope review |

Do not edit central synced output manually. Update the scraper-owned source page, then publish through the sync path.

## Direct Edit Workflow

1. Confirm the page belongs to scraper scope.
2. Check relevant references before writing.
3. Keep required frontmatter intact.
4. Update related navigation or landing pages.
5. Run metadata, link, and secret-pattern checks.
6. Request reviewers from the review matrix.

## Generated Reference Workflow

Generated pages must be reproducible from source code or validation scripts.

| Artifact | Placement | Required evidence |
| --- | --- | --- |
| Route inventory | `docs/generated/routes.md` | Command or script used to generate it |
| OpenAPI schema | `docs/generated/openapi.json` | Scraper app version or source SHA |
| Sync readiness | `docs/generated/sync-readiness.md` | Metadata, link, path, and secret scan result |

Generated references must not replace hand-authored contracts.

## Synced Docs Workflow

Scraper docs may be copied to central docs only through the documented sync pipeline.

Required checks before sync:

- Source path is under `docs/**`.
- Page has required metadata.
- Local links resolve.
- No raw credentials, cookies, bearer tokens, session ids, visitor ids, or device ids appear.
- Central target stays under `docs/services/scraper-api/synced/**` or `versioned/<release>/**`.
- Central service landing page is not overwritten.

## Scope Rules

| Content | Correct location |
| --- | --- |
| Scraper source adapter detail | This repository |
| Raw payload contract and field mapping | This repository |
| Backend user workflow and public API behavior | Backend API repository |
| Cross-service platform summary | Central docs repository |
| Documentation governance source standard | Central docs repository |

## Related Docs

- [Review Process](./review-process.md)
- [Structural Change Policy](./structural-change-policy.md)
- [Documentation Sync and Versioning](./documentation-sync-and-versioning.md)
- [Metadata Standard](./metadata-standard.md)

