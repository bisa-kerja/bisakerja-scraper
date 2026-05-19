---
title: Freshness Module
description: Job freshness state, stale/expired handling, source health, sync latency, observability, and tests.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Freshness Module

The freshness module determines whether normalized job records remain active, stale, or expired after daily ingestion.

## Responsibility

| Area | Rule |
| --- | --- |
| `lastSeenAt` | Update when source listing is observed |
| `postedAt` | Preserve source timestamp when available |
| Status | Move records through `ACTIVE`, `STALE`, `EXPIRED` based on policy |
| Source health | Distinguish source outage from real job disappearance |

## Freshness Rules

| Condition | Status behavior |
| --- | --- |
| Seen in current successful run | `ACTIVE` |
| Not seen because source failed | Keep previous status; mark source degraded |
| Not seen after successful source run | Candidate for `STALE` |
| Stale beyond retention policy | Candidate for `EXPIRED` |
| Referenced by bookmark/application | Keep readable even if expired |

Freshness thresholds are configured with `FRESHNESS_STALE_AFTER_HOURS` and `FRESHNESS_EXPIRED_AFTER_HOURS`. The expired threshold must be greater than the stale threshold.

## Input And Output

| Input | Output |
| --- | --- |
| Ingestion run result, source success/failure, last observed jobs | Updated status, source freshness summary, sync metadata |

The sweep is idempotent. Re-running it with the same source, timestamp, and seen identity set must not keep incrementing changed counts after the first update.

When a stale or expired job appears again in a successful source run, the job becomes `ACTIVE` and receives the current `lastSeenAt`.

## Failure Modes

| Failure | Handling |
| --- | --- |
| Whole source outage | Do not expire jobs from that source based on missing data |
| Partial pagination failure | Mark run partial and avoid broad expiry |
| Clock skew | Use server timestamp and documented timezone policy |
| Missing `postedAt` | Use `lastSeenAt` for freshness, not fake posted date |

## Observability

Track:

- Active count per source.
- Stale count per source.
- Expired count per source.
- Source success rate.
- Sync latency.
- Last successful run timestamp.

## Tests

| Test | Purpose |
| --- | --- |
| Successful missing listing | Confirms stale candidate behavior |
| Source outage | Confirms jobs are not expired from failed source |
| Referenced expired job | Confirms row remains readable |
| Missing posted date | Confirms no fake timestamp is generated |

## Related Docs

- [Data Flow](../overview/data-flow.md)
- [Database Design](../database.md)
- [Ingestion Module](./ingestion.md)
