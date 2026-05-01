---
title: Glints Source Contract
description: Glints unofficial GraphQL source adapter contract, list-first payload mapping, request requirements, and fallback behavior.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Glints Source Contract

## Request

| Item | Value |
| --- | --- |
| Base URL | `https://glints.com/api/v2-alc/graphql` |
| Operation | `searchJobsV3` |
| Method | `POST` |
| Auth | No API key observed |
| Required posture | Browser-like GraphQL request |

Sanitized headers:

```http
content-type: application/json
origin: https://glints.com
referer: https://glints.com/
user-agent: Mozilla/5.0
x-glints-country-code: ID
```

Cookies are optional operational inputs and must not be published raw.

## Coverage

| Capability | Status |
| --- | --- |
| List | Available through `jobsInPage` |
| Detail | Not captured |
| Pagination | `page`, `pageSize`, `hasMore` |
| Primary identity | job `id` |

## Field Mapping

| Source field | Normalized field | Rule |
| --- | --- | --- |
| `id` | `externalJobId` | Required |
| `title` | `title` | Required |
| `type` | `employmentType` | Map enum-like value |
| `workArrangementOption` | `workType` | Map `ONSITE`, remote/hybrid variants |
| `createdAt` | `postedAt` | Use source timestamp |
| `updatedAt` | `sourceUpdatedAt` | Optional |
| `company.name` | `company.name` | Required fallback text |
| `company.logo` | `company.logoUrl` | Optional |
| `company.industry.name` | `company.industry` | Optional |
| `location.formattedName` | `location.display` | Preserve |
| `location.parents[]` | `city/province/country` | Best-effort |
| `salaries[].minAmount/maxAmount` | `salary.min/max` | Nullable |
| `salaries[].CurrencyCode` | `salary.currency` | Preserve |
| `salaries[].salaryMode` | `salary.period` | Preserve/mapped |
| `skills[].skill.name` | `skills[]` | Preserve `mustHave` when useful |

## Fallback

- Since no detail endpoint is captured, use list data as MVP source.
- Store public Glints job URL when derivable from id/slug/source data.
- Missing description/requirements should not block list visibility if minimum fields exist.

## Error Behavior

- Treat GraphQL shape changes as mapper drift.
- Quarantine records without `id`, `title`, or company text.
- Do not persist raw cookies, device ids, or experiment/session metadata into public docs.

