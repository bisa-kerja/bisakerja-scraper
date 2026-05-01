---
title: Generated References
description: Entry point for generated scraper interface references such as routes, OpenAPI artifacts, and sync readiness reports.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Generated References

Generated references belong here when scraper implementation exposes FastAPI routes or machine-readable schemas.

## Current Status

No generated route or OpenAPI artifact is committed yet.

## Expected Artifacts

| Artifact | Source | Rule |
| --- | --- | --- |
| `routes.md` | FastAPI route registry | Regenerate after route add/remove |
| `openapi.json` | FastAPI OpenAPI schema | Regenerate after request/response schema change |
| `sync-readiness.md` | Docs sync validation | Regenerate before central docs sync |

Generated artifacts must not include real bearer tokens, cookies, source request headers, session ids, or raw source payload bodies.

## Related Docs

- [API Reference](../api-reference.md)
- [API Response Standard](../api-response-standard.md)
- [Documentation Sync](../operations/documentation-sync.md)
- [Versioning and Audience Strategy](../standards/versioning-and-audience-strategy.md)
- [Documentation Release Checklist](../operations/documentation-release-checklist.md)
