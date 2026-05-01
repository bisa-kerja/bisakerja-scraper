---
title: Review Process
description: Required review workflow and reviewer matrix for scraper documentation changes.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Review Process

This process defines who must review scraper documentation before it is treated as trusted.

## Review Matrix

| Change type | Examples | Required reviewers |
| --- | --- | --- |
| Low-risk wording | Typo, grammar, formatting | `data-ingestion-owner` or delegated maintainer |
| Source adapter contract | Dealls, Glints, JobStreet, Kalibrr request or field rules | `data-ingestion-owner`, `backend-owner` |
| Raw payload or mapper contract | Nullability, identity, HTML handling, field transforms | `data-ingestion-owner`, `backend-owner` |
| Operations or runbook | Deployment, incident triage, observability, testing | `data-ingestion-owner`, `platform-docs-maintainer` |
| Security or redaction | Credential handling, raw capture publishing, secret scan | `data-ingestion-owner`, `engineering-lead` |
| Sync or versioning | Central path mapping, release snapshot, sync rollback | `data-ingestion-owner`, `platform-docs-maintainer` |
| Structural change | Paths, section moves, navigation, canonical names | `platform-docs-maintainer`, `engineering-lead`, affected owner |
| Cross-service boundary | Backend ownership, trust boundary, main DB sync behavior | `data-ingestion-owner`, `backend-owner`, `engineering-lead` |

## Workflow

1. Author updates the source page.
2. Author confirms reference-first context.
3. Author updates related navigation and linked docs.
4. Validation passes locally.
5. Required reviewers check scope, correctness, ownership, and link impact.
6. Change is merged or prepared for sync.

## Review Focus

- Page belongs in scraper docs.
- Metadata and lifecycle state are correct.
- Source adapter details are based on captured or verified behavior.
- Generated content is clearly labeled.
- Raw captures are sanitized before any public example is shown.
- Backend API responsibility is linked, not duplicated.
- New or moved paths do not break reader navigation.

## Major Change Rule

Major documentation changes require explicit reviewer roles before merge.

Major changes include:

- New top-level section.
- Canonical path rename.
- Source identity or dedup key change.
- Normalized schema contract change.
- Sync target or release snapshot rule change.
- Security or redaction policy change.

## Related Docs

- [Contribution Guide](./contribution-guide.md)
- [Structural Change Policy](./structural-change-policy.md)
- [Documentation Release Checklist](../operations/documentation-release-checklist.md)

