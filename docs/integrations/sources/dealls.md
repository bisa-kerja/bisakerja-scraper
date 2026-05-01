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
| Detail | No separate detail endpoint captured |
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
| `publishedAt` | `postedAt` | ISO timestamp |

## Error Behavior

- If `salaryRange` is `null`, store salary numeric fields as `null`.
- If company rank or candidate preference is missing, ignore for normalized MVP.
- If list request fails, mark Dealls freshness degraded and keep previous rows.
- If `data.docs[]` is missing or a job has no `id`, classify the payload as a parse failure.
- Do not expose `saved`, `applied`, or user-specific flags from source captures.
