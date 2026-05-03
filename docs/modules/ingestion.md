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

## Scrape Plan

The scrape stage expands configured work into `source x keyword` items. Each item carries:

- Keyword.
- Requested per-keyword limit.
- Recency mode and recency days.
- Source timestamp bounds when the source provides timestamps.

The requested limit applies after latest sorting for that keyword. If a source returns more records than requested in one response, the adapter or pipeline truncates before persistence and records the truncated count.

## Latest Retrieval

| Source | Latest request contract | Canonical timestamp |
| --- | --- | --- |
| `dealls` | `sortParam=publishedAt`, `sortBy=desc`, `published=true`, `status=active` | `publishedAt`, fallback `latestUpdatedAt` |
| `glints` | GraphQL `sortBy=LATEST` | `createdAt`, fallback `updatedAt` |
| `jobstreet` | GraphQL `dateRange`; `newSince` when a valid value is available | `listingDate.dateTimeUtc`, fallback detail `listedAt.dateTimeUtc` |
| `kalibrr` | Next.js data query `sort=Freshness` | `activationDate`, fallback `createdAt` or `updatedAt` |

Rows with missing or invalid source timestamps may still be captured, but the run summary must make timestamp coverage visible so operators can distinguish source drift from a clean latest run.

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

## HTTP Client Baseline

All source adapters use a shared async HTTP client contract:

- `httpx.AsyncClient` is used for external requests.
- Every request uses an explicit timeout.
- Default source headers include a browser-like user agent and source-specific headers.
- Retries are bounded and only apply to transport failures, timeouts, `408`, `429`, and transient `5xx` responses.
- Non-retriable `4xx` responses fail immediately.
- Source rate limits are isolated by platform so one blocked source does not pause unrelated sources.
- Retryable failures use capped exponential backoff.
- Repeated retryable failures open a run-local circuit breaker for the affected source.
- Response bodies are streamed through a maximum-size guard before JSON decoding.
- The adapter receives a mockable JSON client interface for fixture-based tests.

## Observability

Track:

- Source platform.
- Keyword.
- Requested per-keyword limit.
- Recency mode and recency days.
- Newest and oldest source timestamps.
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
