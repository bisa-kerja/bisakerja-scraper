---
title: Scraper Data Flow
description: End-to-end data flow from external source jobs to Backend API-consumable normalized records.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Data Flow

The scraper converts source-specific job payloads into normalized Bisakerja job records. The Backend API consumes only the normalized result.

## Flow

```text
source request
  -> source list/detail payload
  -> redacted raw capture
  -> raw job record
  -> normalized company
  -> normalized job listing
  -> normalized requirements and skills
  -> staging validation
  -> main DB upsert
  -> Backend API read
```

## Pipeline Orchestration

The scraper pipeline executes source work through the ordered stages `scrape -> normalize -> enrich -> sync -> notify-handoff`.

Orchestration rules:

- Each run gets one `runId` and one correlation id.
- Source adapters are invoked through an injected source interface so tests can run without external network calls.
- Fetch runs per source, then raw records are normalized through the source mapper.
- Per-source normalization and enrichment use bounded concurrency.
- Persistence writes raw and normalized records idempotently before sync handoff.
- Enrichment batch work reads normalized jobs without skill staging rows, processes up to the configured batch size, writes sanitized AI audit metadata, and stores skills/requirements in staging tables.
- Stage queue jobs can decouple scrape, normalize, enrich, sync, and notify handoff work while preserving retry state and correlation id.
- The sync stage is a hook for backend handoff; if no sync client is configured, the local pipeline still records persisted output.
- Partial mode allows one source to fail without stopping other sources.
- Notification handoff is a boundary stage. The scraper prepares normalized job data; user preference filtering and email delivery remain Backend API or notification-worker concerns.

## Stage Contracts

| Stage | Input | Output | Owner | Required checks |
| --- | --- | --- | --- | --- |
| Fetch | Source config, headers, query params | HTTP response body and safe metadata | Source adapter | Status, pagination, auth/header behavior |
| Raw capture | Source response | Redacted raw payload record | Scraper persistence | No tokens/cookies/session ids in published artifacts |
| Normalize | Raw payload | Canonical job/company/location/salary fields | Normalizer | Identity, title, company, source URL/apply URL |
| Dedup | Normalized candidate | Unique source-local job row | Deduplicator | `sourcePlatform + externalJobId/slug/id` |
| Enrich | Safe title, description, requirements text, company, source | Skills, typed requirements, confidence, warnings | Enrichment worker | Batch size, timeout, confidence, schema validity |
| Enrichment audit | Safe normalized enrichment input | Request hash, provider/model metadata, latency, status, response summary | Enrichment worker | No API key, raw prompt, raw payload, headers, or tokens stored |
| Queue | Stage payload, correlation id, retry policy | Claimed, completed, failed, or dead-letter stage job | Worker process | Retry limit, idempotent handler, dead-letter visibility |
| Sync | Validated staging rows | Main DB records | Sync service | FK integrity, upsert idempotency |
| Notify handoff | Synced normalized jobs and freshness metadata | Backend-owned recommendation and email work | Backend API or notification worker | User preference filtering, delivery retry, frontend-safe fields |
| Read | Main DB normalized rows | Backend API product response | Backend API | Response envelope, user auth, frontend-safe fields |

## Source Detail Reality

| Source | List data | Detail data | Flow impact |
| --- | --- | --- | --- |
| Dealls | Available and rich | Separate detail endpoint not captured | Use list as primary source; public URL fallback |
| Glints | Available | Detail endpoint not captured | Use list-first mapping; public source URL fallback |
| JobStreet | Available | Detail-ready fields observed in GraphQL shape/source path assumptions | Preserve list fields and fetch detail only if adapter supports it |
| Kalibrr | Available | Included in `jobs[]` payload | Sanitize `description` and `qualifications` HTML |

## Field Handling

| Field | Rule |
| --- | --- |
| Salary | Keep `null` for unknown min/max; do not infer exact values from vague labels |
| HTML | Sanitize before display, enrichment, or model input |
| Relative labels | Preserve source timestamp when present; labels like `3 hari yang lalu` are display-only unless parsed with capture time |
| UI/noise fields | Drop facets, suggestions, tracking ids, session fields, and unneeded flags |
| Source URL | Store stable public URL when available for fallback and traceability |
| Raw payload | Keep internally for replay; publish only sanitized examples |

## Visibility Gate

A job can become visible in normal search only after it has:

- Source platform.
- External identity.
- Title.
- Company name or company relation.
- Source/apply URL.
- `lastSeenAt`.
- Safe text fields if description or requirements are present.

## AI Enrichment Boundary

AI enrichment receives only safe normalized text:

- Title.
- Description clean text.
- Requirements clean text.
- Company name.
- Source platform.

It must not receive raw source payloads, source request headers, bearer tokens, cookies, session ids, visitor ids, device ids, or backend service credentials. Invalid structured AI output is treated as enrichment failure and must not block base normalized job sync when the visibility gate is satisfied.

## Queue Boundary

The local queue persists stage jobs in the scraper database. A queued job stores job type, stage payload, correlation id, attempt count, retry limit, availability time, and terminal error metadata.

Queue handlers must be idempotent:

- Scrape handlers upsert raw records by source identity.
- Normalize handlers upsert normalized jobs by source identity.
- Enrich handlers upsert skill and requirement staging rows by normalized value/type.
- Sync handlers reuse payload hashes and sync events.
- Notify handoff handlers use run/source/job identity for duplicate prevention.

## Flow Readiness Reference

Implementation status and remaining gaps are tracked in [Scraper Flow Gap Matrix](../roadmap/scraper-flow-gap-matrix.md).
