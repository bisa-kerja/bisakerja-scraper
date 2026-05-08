---
title: Deduplication Module
description: Source-local identity, duplicate handling, upsert rules, cross-source scope, observability, and tests.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Deduplication Module

The deduplication module prevents duplicate normalized jobs inside one source while preserving source identity.

## Responsibility

| Area | Rule |
| --- | --- |
| Identity key | Use source platform plus external job id |
| Fallback identity | Use a deterministic fingerprint only when source external id is missing |
| Duplicate handling | Upsert same-source records |
| Freshness | Update `lastSeenAt` on each observed listing |
| Scope control | Do not merge cross-source jobs in MVP |

## Identity Rules

| Source | Primary identity | Secondary |
| --- | --- | --- |
| Dealls | `id` | `slug` |
| Glints | GraphQL job `id` | none captured |
| JobStreet | job `id` | source URL path when available |
| Kalibrr | numeric `id` | `slug` |

Canonical unique key:

```text
(sourcePlatformId, externalJobId)
```

Fallback fingerprint input:

```text
sourcePlatform + sourceSlug + title + companyName + sourceUrl
```

Fallback identity is only a recovery path for records that lack a source external id. It must not replace the primary source identity when `externalJobId` is available.

## Input And Output

| Input | Output |
| --- | --- |
| Valid normalized candidate | Existing row update, new staging row, or quarantine reason |
| Identity decision | `insert`, `update`, or `quarantine` with a stable dedup reason |
| Raw scrape identity before normalize | Eligibility decision: `normalization_eligible`, `existing_backend`, `existing_normalized_unsynced`, `existing_normalized_synced`, `duplicate_in_scrape_scope`, `missing_identity`, `identity_conflict`, or `reprocess_required` |

## Failure Modes

| Failure | Handling |
| --- | --- |
| Missing identity | Quarantine |
| Same identity with changed title/company | Update mutable fields and keep audit signal |
| Conflicting secondary slug | Preserve primary id and flag drift |
| Same identity with changed slug and changed title/company | Preserve primary id and flag identity collision |
| Cross-source duplicate suspected | Keep separate records; future merge scope |

## Observability

Track:

- New rows.
- Updated rows.
- Duplicate ratio.
- Identity drift count.
- Identity collision count.
- Quarantine count.
- Eligibility decision distribution and top skip reasons before normalize.

## Tests

| Test | Purpose |
| --- | --- |
| Same source duplicate | Confirms upsert, not insert duplicate |
| Source-separated same id | Confirms different source slugs do not collide |
| Missing identity | Confirms quarantine |
| Slug drift | Confirms primary id remains source of truth |

## Related Docs

- [Database Design](../database.md)
- [Domain Entities](../references/domain-entities.md)
- [Freshness Module](./freshness.md)
