---
title: Versioning and Audience Strategy
description: Strategy for latest docs, release snapshots, audience-specific reading paths, and generated references.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Versioning and Audience Strategy

Scraper docs use latest-by-default documentation. Versioned docs are created only when release history matters.

## Latest Vs Versioned

| Track | Use for | Target |
| --- | --- | --- |
| Latest | Normal engineering and operations work | `docs/**` and central `synced/**` |
| Versioned release | Contract history, incident support, stakeholder handoff | Central `versioned/<release>/**` |
| Generated reference snapshot | Route/schema evidence tied to a release | Central release snapshot or labeled generated path |

## Versioning Decision

Use release snapshots when:

- Source contract behavior differs by release.
- Normalized schema or mapper output changes materially.
- Sync behavior changes.
- Incident review needs historical evidence.
- A capstone/demo handoff needs a stable documentation set.

Do not version routine wording, typo fixes, or navigation-only changes.

## Audience Paths

| Audience | Primary docs |
| --- | --- |
| Backend engineer | API reference, database, sync contract, source field mapping |
| Data engineer | Integrations, raw payload contract, parsing-normalization, deduplication |
| Platform engineer | Environment, deployment, observability, docs sync |
| Product stakeholder | Start here, system landscape, data flow, future docs expansion |
| Operator | Operations index, failure scenarios, release checklist |

Audience pages should route readers to canonical docs. They should not fork technical truth.

## Generated References

Generated references must be:

- Clearly labeled as generated.
- Reproducible from code or validation tools.
- Stored under `docs/generated/**`.
- Linked from hand-authored orientation pages.
- Included in release snapshots only when they represent release-specific behavior.

## Localization

Do not localize scraper docs by default. Add localization only when there is an owner who can keep translated pages current.

## Related Docs

- [Documentation Sync and Versioning](./documentation-sync-and-versioning.md)
- [Generated References](../generated/index.md)
- [Future Docs Expansion](../roadmap/future-docs-expansion.md)

