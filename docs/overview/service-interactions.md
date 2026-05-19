---
title: Scraper Service Interactions
description: Interaction patterns and handoff points between the Scraper API, Backend API, data stores, model workflows, and external job sources.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Service Interactions

Scraper interactions are batch-oriented by default. User-facing reads should not call the scraper at request time.

## Interaction Matrix

| Interaction | Producer | Consumer | Mode | Purpose |
| --- | --- | --- | --- | --- |
| Source fetch | Scraper source adapter | External job platform | Scheduled HTTP | Collect list/detail job data |
| Raw persistence | Scraper pipeline | Local Scraper DB | Internal write | Store redacted raw payloads for replay and mapper checks |
| Normalization | Normalizer | Local staging tables | Internal batch | Convert raw source fields to canonical job records |
| Enrichment | Enrichment worker | Model provider or local extractor | Async batch | Extract skills and structure requirements |
| Sync | Sync service | Main Backend DB | Chunked upsert | Publish normalized jobs for Backend API reads |
| Job reads | Backend API | Main Backend DB | Synchronous read | Serve search, detail, bookmarks, tracker, and AI context |
| Notifications | Email worker | Backend-owned user preference/job data | Scheduled batch | Send daily recommendation emails |

## Primary Flow

```text
00:00 scrape
  -> fetch source pages/batches
  -> persist raw captures

02:00 normalize
  -> map company, location, salary, title, description, requirements
  -> deduplicate by source identity

04:00 enrich
  -> batch skill extraction and requirement structuring
  -> write staging outputs

06:00 sync
  -> upsert source platforms, companies, job listings, skills, requirements
  -> update status and last seen timestamps

08:00 notify
  -> backend/product notification pipeline reads normalized jobs
```

## Handoff Rules

| Handoff | Contract |
| --- | --- |
| Source to raw capture | Preserve source payload enough for replay; redact cookies, bearer tokens, session ids, tracking identifiers |
| Raw capture to normalizer | Normalizer reads source-specific payloads through adapter-owned mappers |
| Normalizer to enrichment | Enrichment receives safe text fields, not raw credential-bearing captures |
| Staging to main DB | Sync uses source-local identity and chunked upsert |
| Main DB to Backend API | Backend reads normalized records only and formats product responses |

## Failure Behavior

| Failure | Expected behavior |
| --- | --- |
| One source throttled | Continue other sources; keep previous normalized records; mark freshness degraded |
| Source API drift | Isolate adapter/parser failure; keep raw capture for mapper update |
| Enrichment unavailable | Continue scrape/normalize; queue enrichment retry; do not block raw capture |
| Sync partially fails | Retry chunk; avoid duplicate rows through source identity |
| Notification window fails | Backend-owned notification recovery handles user messaging; scraper keeps job data intact |

## Non-Interaction Rules

- Frontend UI does not call Scraper API.
- Backend API does not call Scraper API synchronously to repair job search.
- Model API does not decide user authorization.
- Scraper adapters do not write user-owned tables.
