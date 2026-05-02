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
| `correlationId` | Cross-stage queue chain | Required when stage jobs enqueue follow-up work |
| `jobIdentity` | One normalized job | Log only `sourcePlatform` plus `externalJobId`; do not log full raw payload |

Every pipeline log should include `runId`, `stage`, `sourcePlatform` when applicable, `status`, and `durationMs`.

## Run State Tracking

Each pipeline execution creates one run record with status `started`, then finishes as `completed`, `partial`, or `failed`.

Run records store:

- `startedAt` and `finishedAt`.
- Source platform scope, usually `all` for a full pipeline run.
- Stage scope, usually `pipeline` for full orchestration.
- Counts for `fetched`, `parsed`, `normalized`, `persisted`, and `skipped`.
- Per-source count summaries.
- Sanitized error summaries with source platform, category, message, external id when available, and retryability.

Status rules:

| Status | Rule |
| --- | --- |
| `completed` | All enabled sources finish without recorded errors |
| `partial` | At least one source fails while another source can still complete |
| `failed` | The run cannot continue or partial mode is disabled |

Partial failures must not be reported as full success. Count totals must match source-level summaries so operators can isolate source drift, persistence failures, or sync failures from one run id.

## Logger Implementation

Runtime logging uses `structlog` with JSON rendering. The logger binds context through Python context variables so request handlers, jobs, adapters, normalizers, persistence code, and sync workers can add correlation fields without passing logger metadata through every function call.

Required behavior:

- Configure the logger once during process startup with the service name, environment, and log level.
- Generate a `requestId` when an internal HTTP request does not provide a trusted one.
- Generate a `runId` for every scrape pipeline execution.
- Bind `sourceRunId` for each source-specific sub-run.
- Emit one JSON object per log line.
- Redact sensitive keys recursively before rendering the log event.

The redaction processor must treat key names containing credentials, tokens, cookies, sessions, visitors, devices, or database URLs as sensitive. String values must also redact bearer tokens, cookie/session pairs, and PostgreSQL URLs.

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

## Error Categories

Pipeline errors use stable stage categories:

| Category | Stage | Retry direction |
| --- | --- | --- |
| `FETCH_ERROR` | Source fetch | Retry only for bounded transient failures |
| `PARSE_ERROR` | Payload parse | Treat as source contract drift unless clearly malformed input |
| `NORMALIZE_ERROR` | Canonical mapping | Quarantine the record when identity or required fields are invalid |
| `PERSIST_ERROR` | Local database write | Retry when database failure is transient |
| `SYNC_ERROR` | Backend handoff | Retry when backend or network failure is transient |

Error logs should include the category, stage, source platform, external job id when available, retryability, and sanitized details.

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
| `ai_request_latency_ms` | Provider, model, status | Detect model/provider latency regressions |
| `stage_queue_depth` | Job type, status | Detect blocked stage workers |
| `dead_letter_count` | Job type, error category | Detect recovery backlog requiring operator action |
| `retry_count` | Source, stage | Detect throttling or unstable dependency |

## Health Signals

| Signal | Healthy | Degraded |
| --- | --- | --- |
| Scheduler | Expected stage job is registered and only one stage is active at a time | No run by expected cutoff or overlapping stage attempts are rejected repeatedly |
| Liveness | `/health/live` returns a success envelope without dependency checks | Process does not respond |
| Readiness | `/health/ready` returns a success envelope after a lightweight scraper DB query | Scraper DB query fails or times out |
| Source adapters | Source returns list payload and safe status | Auth failure, 429, 5xx, timeout, or schema drift |
| Normalizer | Required identity/title/company/source URL present | Quarantine rate rises |
| Deduplicator | Stable ratio by source | Sudden duplicate spike or identity collisions |
| Enrichment | Batches complete within expected latency | AI timeout, invalid response, or dead letter growth |
| Stage queue | Pending jobs drain and failed jobs retry within policy | Queue depth grows, jobs remain running too long, or dead-letter count rises |
| Sync writer | Upserts complete and counts match staging | Sync latency rises or DB write fails |
| Freshness | `lastSeenAt` within documented threshold | Stale count exceeds threshold |

## Alert Direction

Production alerting should start with these conditions:

- Daily run does not start or finish.
- Readiness fails for the scraper database.
- Any source has repeated fetch failures.
- Parse failure rate spikes for one source.
- Dedup ratio changes sharply from baseline.
- Sync latency or sync failure blocks backend handoff.
- Stage queue dead-letter count rises.
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
- Queue job id and correlation id when a stage job is involved.
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
