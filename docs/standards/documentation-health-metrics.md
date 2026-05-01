---
title: Documentation Health Metrics
description: Operational metrics for scraper documentation coverage, freshness, ownership, links, and sync health.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Documentation Health Metrics

Health metrics show whether scraper docs remain usable for engineers, operators, and central docs sync.

## Core Metrics

| Metric | Measures | Target |
| --- | --- | --- |
| Coverage | Required scraper docs exist for each docs section | Phase target files present |
| Freshness | Pages are within review cadence | No stale active page without backlog |
| Ownership completeness | Every active page has owner and reviewers | 100% |
| Broken links | Local docs links resolve | 0 broken links |
| Sync health | Source docs can publish to central target | Latest bundle validates |
| Secret safety | Docs contain no raw credentials or session values | 0 detected raw secrets |
| Generated reference freshness | Generated artifacts match implementation | No stale generated artifact after contract change |
| Scope hygiene | Scraper docs do not duplicate central or Backend API ownership | No unresolved scope conflict |

## Operational Indicators

| Indicator | Source | Healthy signal |
| --- | --- | --- |
| Broken links | Link checker | `0` broken local links |
| Ownerless active pages | Metadata scan | `0` active pages missing owner or reviewers |
| Stale pages | `last_reviewed` scan | No active page older than cadence |
| Sync health | Sync readiness report | Manifest, paths, metadata, links, and secret scan pass |
| Source contract drift | Contract tests or adapter failures | No unresolved source drift |
| Raw payload safety | Secret-pattern scan | No bearer, cookie, session, visitor, or device tokens |

## Review Use

Run health checks before:

- Major docs release.
- Central sync publish.
- Release snapshot.
- Source adapter contract update.
- Incident closeout.

Health metrics are not reader-facing product metrics. They are maintenance controls for documentation trust.

## Backlog Rules

- Record unresolved metric failures in the release checklist.
- Assign an owner for each backlog item.
- Do not mark a release-ready checklist complete with unresolved broken links or possible real secret leaks.
- Stale pages may ship only with an explicit owner and remediation date.

## Related Docs

- [Freshness and Lifecycle](./freshness-and-lifecycle.md)
- [Documentation Release Checklist](../operations/documentation-release-checklist.md)
- [Documentation Sync](../operations/documentation-sync.md)

