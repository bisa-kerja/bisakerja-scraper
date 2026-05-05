---
title: Recommendation Email Handoff
description: Scraper-owned job candidate handoff contract for backend-owned recommendation email delivery.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-05
---

# Recommendation Email Handoff

The scraper provides a feed of newly synced job candidates. Backend-owned notification logic decides which users receive recommendations, applies preferences, ranks matches, and sends email through the approved delivery provider.

## Ownership

| Area | Owner | Rule |
| --- | --- | --- |
| Job scrape, normalize, enrich, and sync | Scraper API | Produce safe job candidate data only |
| User preferences | Backend API | Scraper must not query or copy user preference tables |
| Recommendation matching | Backend API or backend-owned worker | Uses user preferences and synced job candidates |
| Email provider and templates | Backend API | Delivery credentials and templates stay out of scraper |

## Trigger

Handoff runs only after backend sync succeeds for a job. A job is eligible when its sync event is `sent` for the same run. Pending, failed, and dead-letter sync events are excluded.

## Idempotency

Each handoff event is unique by:

```text
runId + sourcePlatform + externalJobId + target
```

Repeating the same handoff reuses the existing event. Sent handoff events are not sent again. Failed events may retry until the configured attempt limit, then move to dead-letter for operator review.

## Candidate Payload

Default backend endpoint:

```text
POST /api/v1/internal/notification-events
```

The request uses `Authorization: Bearer <BACKEND_SYNC_SERVICE_TOKEN>`. This token must match Backend API `SCRAPER_API_SERVICE_TOKEN`.

The scraper sends only job-level fields needed by backend-owned matching:

| Field | Meaning |
| --- | --- |
| `eventId` | Stable event id composed from run and source job identity |
| `syncEventId` | Sync event that made the job eligible |
| `sourcePlatform` | External source name |
| `externalJobId` | Source job id used for deduplication |
| `title` | Normalized job title |
| `companyName` | Normalized company display name |
| `sourceUrl` | External job page |
| `location` | Normalized location object when available |
| `salary` | Normalized salary object or null |
| `status` | Normalized job freshness status |
| `lastSeenAt` | Last observed timestamp |

The payload must not include email addresses, user ids, preference rows, cookies, bearer tokens, raw source headers, or raw source payloads.

## Matching Inputs Owned By Backend

Backend-side matching may use:

| Input | Purpose |
| --- | --- |
| Target roles | Role/title relevance |
| Preferred locations | Location filtering and ranking |
| Minimum salary | Salary filtering when normalized salary exists |
| `emailNotificationsEnabled` | Master opt-out for non-security email |

Recommendation email output should cap candidates to 10-20 jobs per user and sort by relevance before recency.

## Failure Handling

| Failure | Behavior |
| --- | --- |
| No sent sync events | Handoff exits with zero candidates |
| Backend notification endpoint fails | Handoff event becomes retryable failure |
| Repeated backend failure | Handoff event moves to dead-letter |
| User preference unavailable | Backend suppresses or delays delivery; scraper does not compensate |

Failure response summaries store only safe fields: status code, status class, error code, message, and endpoint path.

## Verification

- Handoff event exists only for sent sync events.
- Re-running handoff does not create duplicate events.
- Scraper code has no dependency on backend user preference tables.
- Payload contains only normalized job candidate data.

## Related Docs

- [Scraper API Contract](./scraper-api-contract.md)
- [Failure Scenarios](../operations/failure-scenarios.md)
- [Daily Pipeline Runbook](../operations/daily-pipeline-runbook.md)
