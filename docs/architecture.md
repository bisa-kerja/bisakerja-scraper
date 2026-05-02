---
title: Scraper Architecture
description: Architecture, module boundaries, daily pipeline, failure points, and database handoff model for Bisakerja Scraper.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Architecture

Bisakerja Scraper is a FastAPI-oriented ingestion service with scheduled workers, source adapters, a local scraper database, normalization, enrichment, and sync preparation for the Backend API database.

## Architecture Summary

```text
External Job Platforms
  -> source adapters
  -> raw payload capture
  -> Local Scraper DB
  -> normalizer
  -> staging tables
  -> enrichment worker
  -> sync service
  -> Main Backend DB
  -> Backend API reads normalized jobs
```

## Module Boundaries

| Module | Responsibility | Input | Output | Failure mode |
| --- | --- | --- | --- | --- |
| `services/scraper` | Per-source HTTP fetch adapters | Search term, page/window, source config | Raw source payload | Source throttle, auth failure, schema drift |
| `db/repositories` | Local raw/staging persistence | Raw payloads, staging rows | Durable local records | Duplicate records, transaction failure |
| `services/normalizer` | Raw-to-canonical mapping | Source payload | Normalized job/company/requirement shape | Missing identity, malformed fields |
| `services/enrichment` | Skill extraction and requirement structuring | Safe job text | Skill/requirement enrichment | Provider timeout, rate limit, low-confidence output |
| `services/queue` | Local stage job dispatch and retry tracking | Stage payload and correlation id | Completed, failed, or dead-letter stage job | Worker unavailable, retry exhaustion |
| `services/sync` | Main DB upsert preparation | Staging rows | Upserted normalized records | Partial chunk failure, FK mismatch |
| `services/pipeline` | Orchestration | Run config | Ingestion run state | Stage dependency failure |
| `workers` | Scheduled/background execution | Cron/Celery task | Batch execution | Worker unavailable, overlapping run |

## Daily Baseline

| Time | Stage | Owner | Input | Output |
| --- | --- | --- | --- | --- |
| 01:00 | Scrape | Source adapters | Source config and query windows | Raw captures per source |
| 01:30 | Normalize | Normalizer | Raw captures | Staging records keyed by source identity |
| 02:00 | Enrich | Enrichment worker | Safe title/description/requirements text | Skills and structured requirements |
| 03:00 | Sync | Sync service | Staging rows | Main DB normalized job rows |
| 05:00-06:00 | Notify handoff | Backend/product worker | Normalized jobs and user preferences | Recommendation emails |

## Data Ownership

| Store | Owner | Purpose |
| --- | --- | --- |
| Local Scraper DB | Scraper API | Raw captures, staging rows, ingestion runs, retries |
| Main Backend DB job tables | Scraper API writes normalized job data; Backend API reads | Product job catalog |
| Backend-owned user tables | Backend API | Users, auth, preferences, bookmarks, tracker, AI snapshots |

The scraper must not write backend-owned user tables. The Backend API must not write scraper-owned normalized job rows in MVP.

## Identity Strategy

Use source-local identity for deduplication:

```text
sourcePlatform + externalJobId
```

When a source lacks a single external id, use the most stable source value:

| Source | Identity |
| --- | --- |
| Dealls | `id`, with `slug` as secondary |
| Glints | GraphQL job `id` |
| JobStreet | numeric/string `id` |
| Kalibrr | numeric `id`, with `slug` as secondary |

Cross-source merge is future scope.

## Sync Rules

- Upsert by source platform and external job id.
- Preserve `lastSeenAt` for freshness.
- Mark missing listings as `STALE` or `EXPIRED` according to operational policy.
- Keep stale/expired records readable when linked by bookmarks or application history.
- Use chunked writes; failed chunks must be retryable without duplicating rows.

## Failure Points

| Stage | Failure point | Mitigation |
| --- | --- | --- |
| Scrape | Request blocked, source auth expired, dynamic build id changed | Retry with backoff, refresh source config, isolate source |
| Raw capture | Payload too large or contains sensitive headers | Store sanitized body/metadata; redact captured headers |
| Normalize | Missing title/company/identity, HTML unsafe, unexpected field shape | Quarantine row, keep raw capture, update mapper |
| Enrich | Provider timeout/rate limit | Batch retry; allow normalized job sync without enrichment if safe |
| Queue | Stage job retry limit exhausted | Move to dead-letter with correlation id and safe error metadata |
| Sync | FK/constraint conflict | Resolve source platform/company first; retry chunk |
| Notify | Preference/job match failure | Keep notification recovery outside scraper core |
