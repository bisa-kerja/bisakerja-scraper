---
title: Scraper Observability
description: Structured logging, correlation, ingest metrics, health signals, and triage evidence for the scraper pipeline.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Observability

Scraper observability must make ingestion, normalization, enrichment, sync, and freshness failures diagnosable without exposing source credentials or raw sensitive payloads.

## Goals

- Correlate every scheduled or manual run with one `runId`.
- Correlate internal HTTP calls with `requestId` when endpoints exist.
- Separate source failure, parser drift, dedup behavior, enrichment degradation, sync failure, and stale data.
- Track daily ingest health by source.
- Keep logs safe for local, staging, and production debugging.

## Correlation

| Identifier | Scope | Rule |
| --- | --- | --- |
| `runId` | One scrape pipeline execution | Required for scheduler, source adapter, normalization, enrichment, sync, and freshness logs |
| `sourceRunId` | One source inside one run | Required for per-source counts and partial failure isolation |
| `requestId` | Internal HTTP request | Accept trusted incoming value or generate one |
| `jobIdentity` | One normalized job | Log only `sourcePlatform` plus `externalJobId`; do not log full raw payload |

Every pipeline log should include `runId`, `stage`, `sourcePlatform` when applicable, `status`, and `durationMs`.

## Structured Log Fields

| Field | Description |
| --- | --- |
| `timestamp` | ISO timestamp |
| `level` | `debug`, `info`, `warn`, or `error` |
| `service` | `bisakerja-scraper` |
| `env` | `local`, `test`, `staging`, or `production` |
| `runId` | Pipeline run id |
| `sourceRunId` | Per-source run id |
| `requestId` | Internal API request id if available |
| `stage` | `scrape`, `normalize`, `enrich`, `sync`, `notify-handoff`, or `freshness` |
| `sourcePlatform` | `dealls`, `glints`, `jobstreet`, `kalibrr`, or `all` |
| `status` | `started`, `succeeded`, `partial`, `failed`, or `skipped` |
| `durationMs` | Stage duration |
| `errorCategory` | Safe failure category |

Never log bearer tokens, cookies, session ids, visitor ids, device ids, raw request headers, full raw payload bodies, DB URLs, or unsanitized HTML.

## Daily Ingest Metrics

| Metric | Dimension | Purpose |
| --- | --- | --- |
| `fetch_success_rate` | Source, run, status class | Detect source outage or auth drift |
| `parse_failure_rate` | Source, mapper version | Detect payload schema drift |
| `dedup_ratio` | Source, run | Detect repeated records or unstable identity |
| `stale_job_count` | Source, age bucket | Detect freshness degradation |
| `sync_latency_ms` | Stage, batch size | Detect backend DB or writer slowdown |
| `raw_records_fetched` | Source, page | Confirm source coverage |
| `normalized_records_written` | Source | Confirm mapper output volume |
| `quarantined_records` | Source, reason | Track invalid identity or unsafe fields |
| `enrichment_failure_rate` | Batch, model/task | Detect AI enrichment degradation |
| `retry_count` | Source, stage | Detect throttling or unstable dependency |

## Health Signals

| Signal | Healthy | Degraded |
| --- | --- | --- |
| Scheduler | Expected run started inside window | No run by expected cutoff |
| Source adapters | Source returns list payload and safe status | Auth failure, 429, 5xx, timeout, or schema drift |
| Normalizer | Required identity/title/company/source URL present | Quarantine rate rises |
| Deduplicator | Stable ratio by source | Sudden duplicate spike or identity collisions |
| Enrichment | Batches complete within expected latency | AI timeout, invalid response, or dead letter growth |
| Sync writer | Upserts complete and counts match staging | Sync latency rises or DB write fails |
| Freshness | `lastSeenAt` within documented threshold | Stale count exceeds threshold |

## Alert Direction

Production alerting should start with these conditions:

- Daily run does not start or finish.
- Any source has repeated fetch failures.
- Parse failure rate spikes for one source.
- Dedup ratio changes sharply from baseline.
- Sync latency or sync failure blocks backend handoff.
- Stale jobs exceed freshness threshold.
- Source auth failure appears for JobStreet.
- Kalibrr `buildId` refresh repeatedly fails.

Severity follows user impact:

1. Sync blocked for all sources.
2. Freshness degraded for most sources.
3. One source unavailable.
4. Enrichment degraded while scrape and sync still work.

## Triage Evidence

For each incident, collect:

- `runId` and affected `sourceRunId`.
- Stage where failure started.
- Source status code class or dependency result.
- Counts before and after failure.
- First safe error category.
- Last successful run time.
- Recent deploy or config change.

## Related Docs

- [Failure Scenarios](./failure-scenarios.md)
- [Testing Strategy](./testing.md)
- [Deployment](./deployment.md)
- [Security](./security.md)
- [Ingestion Module](../modules/ingestion.md)
- [Freshness Module](../modules/freshness.md)

