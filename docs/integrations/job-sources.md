---
title: Job Sources
description: Source integration matrix for Dealls, Glints, JobStreet, Kalibrr, and Kitalulus support, including coverage, auth, field handling, and fallback rules.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Job Sources

The scraper supports five source adapters behind one normalized job contract.

## Source Matrix

| Source | Transport | Auth/header requirement | List | Detail | Identity |
| --- | --- | --- | --- | --- | --- |
| Dealls | REST `GET /v1/explore-job/job` and `GET /v1/job-portal/job/slug/{slug}` | Browser headers recommended; no auth required; list query `limit` must be `<= 20` | Available | Available by slug; missing detail does not block list records | `id`, fallback `slug` |
| Glints | GraphQL `searchJobsV3` | Browser headers and `x-glints-country-code`; cookies optional/redacted | Available | Not captured | job `id` |
| JobStreet | GraphQL `JobSearchV6` | Bearer auth and session-like headers/cookies from configured secret flow; Cloudflare-protected periods require operator-managed cookie | Available | Detail-ready fields/source URL assumptions | job `id` |
| Kalibrr | Next.js `_next/data/{buildId}` JSON | `x-nextjs-data: 1`; browser headers recommended | Available | Included in `jobs[]` | numeric `id`, fallback `slug` |
| Kitalulus | GraphQL `Vacancies` and `VacancyBySlug` | Browser headers, `origin`/`referer`, `x-channel: web`; no auth captured | Available | Available by slug | `id`, fallback `slug` |

## Source Enablement

Each source has one explicit boolean enablement variable. Live execute mode respects these flags; fixture dry-run may still validate disabled sources.

| Source | Flag |
| --- | --- |
| Dealls | `DEALLS_ENABLED` |
| Glints | `GLINTS_ENABLED` |
| JobStreet | `JOBSTREET_ENABLED` |
| Kalibrr | `KALIBRR_ENABLED` |
| Kitalulus | `KITALULUS_ENABLED` |

## Normalized Minimum

Every adapter should produce:

- `sourcePlatform`.
- `externalJobId`.
- `sourceUrl` or `externalApplyUrl`.
- `title`.
- `company.name`.
- `location.display` when present.
- `salary.min`, `salary.max`, `salary.currency`, `salary.period`, `salary.display` when present.
- `description` and `requirements` as sanitized text when present.
- `postedAt` when source timestamp exists.
- `lastSeenAt` from scrape time.
- `status`.

## Fallback Rules

| Case | Rule |
| --- | --- |
| Detail endpoint unavailable | Use list payload as source of truth and store public source URL for user/apply navigation |
| Glints detail unavailable | Keep `description` `null`, allow safe requirement summary from list fields only, and mark detail completeness as partial |
| Detail record missing | Keep list payload, mark detail coverage, and avoid failing the source batch |
| Salary missing or empty | Store `null` numeric salary fields and optional sanitized display label |
| Relative posted label only | Keep label as display-only; do not compute exact timestamp without capture time and parser rule |
| HTML description/qualification | Sanitize to safe text/allowed HTML before display or model use |
| Source throttled | Keep previous normalized records; mark source freshness degraded |
| Source schema drift | Quarantine affected payloads and update mapper |

## Retry And Timeout

| Source | Timeout baseline | Rate limit policy | Retry posture |
| --- | --- | --- | --- |
| Dealls | Standard HTTP timeout | Per-source request spacing from configuration | Retry transient 5xx/timeouts; avoid aggressive pagination |
| Glints | Standard HTTP timeout | Per-source request spacing from configuration | Retry network failures; isolate GraphQL schema errors |
| JobStreet | Standard HTTP timeout | Per-source request spacing from configuration | Stop on auth failure until credential refresh; retry transient errors |
| Kalibrr | Standard HTTP timeout | Per-source request spacing from configuration | Refresh dynamic `buildId` on 404/data miss; retry transient errors |
| Kitalulus | Standard HTTP timeout | Per-source request spacing from configuration | Retry transient GraphQL/network failures; isolate schema errors |

## Backoff And Circuit Breaker

Source requests use isolated rate limiter state per source platform. A throttled or failing source must not delay another source in the same run.

| Condition | Handling |
| --- | --- |
| Request spacing | Apply configured requests-per-minute before each source request |
| `429` | Treat as retryable and apply exponential backoff within the retry limit |
| `408` and transient `5xx` | Treat as retryable and apply exponential backoff within the retry limit |
| Non-retryable `4xx` | Fail the affected source without blind retry |
| Repeated retryable failures | Open a run-local circuit breaker for that source and mark the source degraded |

Circuit breaker state is local to the running client instance. Persistent recovery decisions belong to run tracking and operations review, not a process-global block list.

## High-Volume Pagination Policy

All live sources use multi-page retrieval with deterministic stop rules:

- Stop when target per-keyword limit is reached.
- Stop when source pagination indicates exhaustion.
- Stop when max pages per keyword is reached.
- Stop when repeated empty pages indicate no additional records.

Run-level controls:

- `SCRAPER_MAX_ITEMS_PER_KEYWORD`
- `SCRAPER_MAX_ITEMS_PER_SOURCE_RUN`
- `SCRAPER_MAX_PAGES_PER_KEYWORD`
- `SCRAPER_TARGET_TOTAL_JOBS_PER_RUN`
- `SCRAPER_DETAIL_FETCH_CONCURRENCY`

Source page-size controls:

- `DEALLS_PAGE_SIZE`
- `GLINTS_PAGE_SIZE`
- `JOBSTREET_PAGE_SIZE`
- `KALIBRR_PAGE_SIZE`
- `KITALULUS_PAGE_SIZE`

Ordering control:

- `SCRAPER_RECENCY_MODE=latest` keeps current newest-first behavior.
- `SCRAPER_RECENCY_MODE=native` omits scraper-added latest sort/filter parameters and preserves platform response order.

Each source report should expose `pagesAttempted`, `pagesSucceeded`, `pagesFailed`, `stopReason`, and `dedupedCount`.

## Source Pages

- [Dealls](./sources/dealls.md)
- [Glints](./sources/glints.md)
- [JobStreet](./sources/jobstreet.md)
- [Kalibrr](./sources/kalibrr.md)
- [Kitalulus](./sources/kitalulus.md)
