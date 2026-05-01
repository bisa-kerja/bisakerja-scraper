---
title: Ingestion Module
description: Scraper ingestion scheduler, source adapter execution, raw capture boundary, observability, failure modes, and tests.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Ingestion Module

The ingestion module fetches source job payloads through per-platform adapters and stores redacted raw captures for replay and normalization.

## Responsibility

| Area | Rule |
| --- | --- |
| Scheduler | Starts configured scrape windows |
| Source adapters | Own source-specific HTTP/GraphQL/Next.js request behavior |
| Raw capture | Persists response body plus safe metadata |
| Run tracking | Records counts, status, timing, and sanitized error class |

## Source Adapters

| Adapter | Transport | Special rule |
| --- | --- | --- |
| `dealls` | REST | List payload is primary source |
| `glints` | GraphQL | Detail endpoint not captured; use list-first mapping |
| `jobstreet` | GraphQL | Bearer/session material comes from secrets only |
| `kalibrr` | Next.js data | Refresh dynamic `buildId` when data path drifts |

## Input And Output

| Input | Output |
| --- | --- |
| Source config, schedule window, pagination, rate limit policy | `ScrapedJobRaw` rows, `IngestionRun` status, source freshness signals |

## Failure Modes

| Failure | Handling |
| --- | --- |
| Source timeout/5xx | Retry with bounded backoff |
| Source auth failure | Stop affected source; mark run partial |
| Schema drift | Store quarantined capture and fail mapper gate |
| Payload too large | Reject or truncate only by documented storage policy |
| Overlapping run | Return conflict or skip according to schedule lock |

## Observability

Track:

- Source platform.
- HTTP status class.
- Fetched page count.
- Raw record count.
- Retry count.
- Duration.
- Sanitized error category.

Never log credentials, cookies, session ids, visitor ids, or raw source payload bodies.

## Tests

| Test | Purpose |
| --- | --- |
| Adapter contract fixture | Confirms list response shape is accepted |
| Source auth failure | Confirms credentials are not logged |
| Retry behavior | Confirms bounded retry and partial run status |
| Raw redaction | Confirms sensitive header fields are removed |
| Run lock | Confirms duplicate active run is rejected or skipped |

## Related Docs

- [Job Sources](../integrations/job-sources.md)
- [Raw Payload Contract](../references/raw-payload-contract.md)
- [Payload Redaction Policy](../standards/payload-redaction-policy.md)

