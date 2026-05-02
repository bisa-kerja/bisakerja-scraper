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

The scraper pipeline executes source work through the ordered stages `scrape -> normalize -> enrich -> sync`.

Orchestration rules:

- Each run gets one `runId` and one correlation id.
- Source adapters are invoked through an injected source interface so tests can run without external network calls.
- Fetch runs per source, then raw records are normalized through the source mapper.
- Per-source normalization and enrichment use bounded concurrency.
- Persistence writes raw and normalized records idempotently before sync handoff.
- The sync stage is a hook for backend handoff; if no sync client is configured, the local pipeline still records persisted output.
- Partial mode allows one source to fail without stopping other sources.

## Stage Contracts

| Stage | Input | Output | Owner | Required checks |
| --- | --- | --- | --- | --- |
| Fetch | Source config, headers, query params | HTTP response body and safe metadata | Source adapter | Status, pagination, auth/header behavior |
| Raw capture | Source response | Redacted raw payload record | Scraper persistence | No tokens/cookies/session ids in published artifacts |
| Normalize | Raw payload | Canonical job/company/location/salary fields | Normalizer | Identity, title, company, source URL/apply URL |
| Dedup | Normalized candidate | Unique source-local job row | Deduplicator | `sourcePlatform + externalJobId/slug/id` |
| Enrich | Safe text fields | Skill/requirement enrichment | Enrichment worker | Batch size, timeout, confidence |
| Sync | Validated staging rows | Main DB records | Sync service | FK integrity, upsert idempotency |
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
