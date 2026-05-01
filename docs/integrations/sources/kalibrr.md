---
title: Kalibrr Source Contract
description: Kalibrr Next.js data source adapter contract, dynamic build id handling, payload mapping, HTML handling, and error behavior.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Kalibrr Source Contract

## Request

| Item | Value |
| --- | --- |
| Base URL | `https://www.kalibrr.id` |
| Endpoint | `GET /_next/data/{buildId}/id-ID/home/{category}/{keyword}.json` |
| Auth | None observed |
| Required header | `x-nextjs-data: 1` |
| Dynamic value | `buildId` |

Sanitized headers:

```http
x-nextjs-data: 1
accept: */*
user-agent: Mozilla/5.0
referer: https://www.kalibrr.id/
```

Cookies are not part of the public contract and must be redacted if captured.

## Coverage

| Capability | Status |
| --- | --- |
| List | Available through `pageProps.jobs[]` |
| Detail | Included in each job object |
| Pagination | `filters.limit`, `filters.offset` |
| Primary identity | numeric `id` |
| Secondary identity | `slug` |

## Field Mapping

| Source field | Normalized field | Rule |
| --- | --- | --- |
| `id` | `externalJobId` | Required |
| `slug` | `sourceSlug`, source URL component | Preserve |
| `name` | `title` | Required |
| `companyName` or `company.name` | `company.name` | Required fallback text |
| `company.logoSmall` | `company.logoUrl` | Optional |
| `function` | `category` | Optional |
| `tenure` | `employmentType` | Map text |
| `isHybrid`, `isWorkFromHome` | `workType` | Remote/hybrid flags |
| `googleLocation.addressComponents` | `location` | City/region/country |
| `baseSalary`, `maximumSalary` | `salary.min/max` | Nullable |
| `salaryCurrency` | `salary.currency` | Nullable |
| `salaryInterval` | `salary.period` | Nullable |
| `activationDate`, `createdAt` | `postedAt`/`sourceUpdatedAt` | Prefer activation for freshness if defined |
| `description` | `description` | HTML; sanitize |
| `qualifications` | `requirements` | HTML; sanitize |
| `perks` | optional benefits metadata | Sanitize |

## Error Behavior

- If `_next/data` returns 404 or empty data, refresh `buildId`.
- If salary fields are null, store unknown salary.
- HTML fields must be sanitized before display, enrichment, or model input.
- Dynamic build id is operational state, not a stable contract.

## Build Id Handling

Kalibrr exposes data through Next.js `_next/data` paths that include the active build id. The scraper resolves this value from the public page data script (`__NEXT_DATA__`) and caches it for the current run.

If a `_next/data` request returns 404, the cached value is treated as stale. The scraper refreshes the public page, extracts the new build id, and retries the data request once with the refreshed path.

The build id must not be hardcoded in configuration. It belongs to source runtime state, not deployment configuration.
