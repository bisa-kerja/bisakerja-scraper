---
title: Glints Source Contract
description: Glints unofficial GraphQL source adapter contract, list-first payload mapping, request requirements, and fallback behavior.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
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

## List Adapter Behavior

The Glints list adapter sends a POST JSON GraphQL request to `/api/v2-alc/graphql` with `op=searchJobsV3`. The request body contains:

- `operationName = searchJobsV3`.
- `variables.data.CountryCode`, `sortBy`, `includeExternalJobs`, `pageSize`, and `page`.
- `variables.data.SearchTerm` only when a search term is provided.
- A static query document that asks only for list-visible job, company, location, salary, category, and skill fields.

The request builder must not include cookies, bearer tokens, device ids, trace ids, experiment ids, or raw browser session metadata.

The parser reads jobs from `data.searchJobsV3.jobsInPage` and pagination continuation from `data.searchJobsV3.hasMore`. Any GraphQL `errors` payload is treated as mapper drift unless a future contract documents partial-data handling.

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
| `minYearsOfExperience`, `maxYearsOfExperience`, `hierarchicalJobCategory.name`, `skills[]` | `requirementSummary` | Build safe partial summary only from explicit list fields |

## Fallback

- Since no detail endpoint is captured, use list data as MVP source.
- Store public Glints job URL as `https://glints.com/id/opportunities/jobs/{id}` when no slug is captured.
- Use the same public URL as `externalApplyUrl` when no source apply URL is available.
- Treat list visibility as active lifecycle unless source explicitly marks stale/closed/expired.
- Mark detail coverage as `unavailable`.
- Mark detail completeness as `partial`.
- Record field provenance for list-derived values such as title, company, location, salary, skills, and public URL.
- `description` must remain `null` when detail text is unavailable.
- `requirements` may be `null` or a safe summary built from explicit list fields (experience, category, skills).
- Missing description/requirements should not block list visibility if minimum fields exist.

## Error Behavior

- Treat GraphQL shape changes as mapper drift.
- Quarantine records without `id`, `title`, or company text.
- Do not persist raw cookies, device ids, or experiment/session metadata into public docs.
