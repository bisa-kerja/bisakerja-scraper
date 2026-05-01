---
title: Archival Strategy
description: Strategy for retiring deprecated scraper docs, release snapshots, generated artifacts, and source-contract history.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Archival Strategy

Archival keeps old scraper documentation available for evidence without letting it guide new work.

## When To Archive

Archive or deprecate a page when:

- A source adapter is removed or replaced.
- A source endpoint contract no longer matches current capture.
- A normalized schema contract is superseded.
- A generated reference belongs to an old release.
- A runbook no longer matches current runtime topology.
- A release snapshot is kept for support or incident review.

## Archive States

| State | Use when | Reader expectation |
| --- | --- | --- |
| `deprecated` | Page is still useful during migration | Use replacement for new work |
| `archived` | Page is historical only | Do not use for implementation |

## Placement

| Content | Preferred placement |
| --- | --- |
| Current scraper docs | Existing `docs/**` path |
| Deprecated scraper page | Existing path with deprecated status and replacement link |
| Release snapshot | Central `versioned/<release>/**` during sync |
| Old generated artifact | Release snapshot or clearly labeled generated archive |
| Raw capture history | Keep root raw capture files private to repo workflow unless sanitized |

Do not create broad archive trees until volume requires it.

## Required Page Notes

Deprecated or archived pages must state:

- Why the page changed state.
- What replaced it.
- Last safe use case, if any.
- Owner for historical questions.

## Do Not Archive Silently

Do not silently archive:

- Active runbooks.
- Security or redaction policies.
- Source contracts still used by mappers.
- Backend sync contracts still consumed by downstream services.
- Incident evidence required for follow-up.

## Related Docs

- [Freshness and Lifecycle](./freshness-and-lifecycle.md)
- [Versioning and Audience Strategy](./versioning-and-audience-strategy.md)
- [Documentation Sync and Versioning](./documentation-sync-and-versioning.md)

