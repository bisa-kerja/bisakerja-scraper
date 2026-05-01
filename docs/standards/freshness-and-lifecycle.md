---
title: Freshness and Lifecycle
description: Lifecycle states, review cadence, freshness rules, and escalation path for scraper documentation.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Freshness and Lifecycle

Scraper docs must show whether they are current enough for implementation and operations decisions.

## Lifecycle States

| State | Meaning | Allowed use |
| --- | --- | --- |
| `draft` | Written from references, not yet implementation-verified | Planning, early implementation, pending review |
| `active` | Current and reviewed against implementation or accepted contract | Normal contributor and operator guidance |
| `deprecated` | Still available, but replaced for new work | Migration window or backward reference |
| `archived` | Kept only for historical reference | Incident evidence or superseded release docs |

The local metadata standard currently requires `draft`, `active`, or `deprecated`. Use `archived` only when the archival page or sync target explicitly supports it.

## Review Cadence

| Page type | Cadence | Trigger for immediate review |
| --- | --- | --- |
| Source contracts | Every 60 days | Source API drift, auth/header change, mapper failure |
| Raw payload and field mapping | Every 60 days | New raw fixture, normalized schema change |
| Operations runbooks | Every 60 days | Incident, deploy change, monitoring change |
| Standards and governance | Every 90 days | Policy or sync process change |
| Architecture and data flow | Every 90 days | Pipeline, DB, queue, or service boundary change |
| Generated references | On generation source change | Route, schema, or sync-readiness change |

## Freshness Rules

- Every maintained page must have `last_reviewed`.
- `last_reviewed` must mean the content was checked, not only reformatted.
- Pages outside cadence must be flagged in the release checklist.
- Active pages must not be ownerless.
- Deprecated pages must link to the replacement.
- Archived pages must not appear as the primary reading path.

## Escalation

| Problem | First action | Escalation |
| --- | --- | --- |
| Stale source contract | Notify `data-ingestion-owner` | `engineering-lead` if source risk affects sync |
| Ownerless page | Assign owner or mark deprecated | `platform-docs-maintainer` |
| Broken incident runbook | Patch immediately | `engineering-lead` |
| Failed sync health | Retry or rollback sync | `platform-docs-maintainer` |
| Possible secret leak | Block publish and rotate if real | `engineering-lead` |

## Related Docs

- [Documentation Health Metrics](./documentation-health-metrics.md)
- [Archival Strategy](./archival-strategy.md)
- [Documentation Release Checklist](../operations/documentation-release-checklist.md)

