---
title: Dealls Source Contract
description: Dealls REST source adapter contract, request requirements, payload mapping, fallback behavior, and error handling.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Dealls Source Contract

## Request

| Item | Value |
| --- | --- |
| Base URL | `https://api.sejutacita.id/v1` |
| Endpoint | `GET /explore-job/job` |
| Auth | None observed |
| Required posture | Browser-like headers with Dealls origin/referer |

Recommended sanitized headers:

```http
origin: https://dealls.com
referer: https://dealls.com/
user-agent: Mozilla/5.0
x-client-app-name: Deall-Talent-Web
x-client-app-version: <version>
```

## Coverage

| Capability | Status |
| --- | --- |
| List | Available |
| Detail | Available by public slug endpoint |
| Pagination | `page`, `limit`, `totalPages` |
| Primary identity | `id` |
| Secondary identity | `slug` |

## List Adapter Behavior

The Dealls list adapter fetches one paginated REST page at a time from `/explore-job/job`.

Default query posture:

| Parameter | Value |
| --- | --- |
| `sortParam` | `publishedAt` |
| `sortBy` | `desc` |
| `status` | `active` |
| `published` | `true` |
| `boostTheBoostedJob` | `true` |
| `externalPlatformApplyUrlSet` | `null` |

The adapter reads pagination from `data.page`, `data.limit`, `data.totalDocs`, and `data.totalPages`. If a sanitized fixture omits `limit`, in-memory parsing uses the observed `docs` count; live source responses should still be expected to include the requested limit.

Each `data.docs[]` item becomes a raw source job with:

- `sourcePlatform = dealls`.
- `externalId = id`.
- `sourceUrl = https://dealls.com/jobs/{slug}` when `slug` exists.
- `rawPayload = original job object`.

## Detail Adapter Behavior

The Dealls detail adapter fetches one job from `/job-portal/job/slug/{slug}`. It only sends non-identifying public parameters:

| Parameter | Value |
| --- | --- |
| `trId` | `view` |
| `guest` | `true` |

Tracking identifiers such as guest ids must not be stored in source fixtures, docs, or request builders.

The detail response is read from `data.result`. The parser requires `id` and `slug`, then exposes the full result object as detail raw payload. The enrichment helper stores list and detail evidence together:

- `rawPayload.list` contains the original list job object.
- `rawPayload.detail` contains the detail result object when available.
- `rawPayload.detailMetadata.coverage` is `available` or `missing`.

If the detail endpoint returns a missing record, the job remains valid with the list payload and a missing-detail marker. Transient fetch failures are still surfaced as source fetch errors.

## Field Mapping

| Source field | Normalized field | Rule |
| --- | --- | --- |
| `id` | `externalJobId` | Required |
| `slug` | `sourceSlug`, source URL component | Preserve |
| `role` | `title` | Required |
| `employmentTypes[]` | `employmentType` | Map known values |
| `workplaceType` | `workType` | Map `onSite`, `hybrid`, `remote` |
| `salaryRange.start/end` | `salary.min/max` | Nullable |
| `company.name` | `company.name` | Required fallback text |
| `company.logoUrl` | `company.logoUrl` | Optional |
| `city.name`, `country.name` | `location` | Preserve partial |
| `skills[].name` | `skills[]` | Normalize names |
| `requirements` | `requirements` | Detail text when available |
| `publishedAt` | `postedAt` | ISO timestamp |

## Error Behavior

- If `salaryRange` is `null`, store salary numeric fields as `null`.
- If company rank or candidate preference is missing, ignore for normalized MVP.
- If list request fails, mark Dealls freshness degraded and keep previous rows.
- If a detail record is missing, keep the list job and mark detail coverage as missing.
- If `data.docs[]` is missing or a job has no `id`, classify the payload as a parse failure.
- Do not expose `saved`, `applied`, or user-specific flags from source captures.
