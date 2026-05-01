---
title: JobStreet Source Contract
description: JobStreet GraphQL source adapter contract, bearer-auth request requirements, payload mapping, and error behavior.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# JobStreet Source Contract

## Request

| Item | Value |
| --- | --- |
| Endpoint | `https://id.jobstreet.com/graphql` |
| Operation | `JobSearchV6` |
| Method | `POST` |
| Auth | Bearer token required |
| Required posture | Configured bearer auth plus browser-like headers |

Sanitized headers:

```http
authorization: Bearer <redacted>
content-type: application/json
origin: https://id.jobstreet.com
referer: https://id.jobstreet.com/
user-agent: Mozilla/5.0
```

Session cookies and SEEK session/visitor ids are sensitive and must be redacted.

## Coverage

| Capability | Status |
| --- | --- |
| List | Available through `jobSearchV6.data` |
| Detail | Detail-ready list fields and source URL path assumptions; separate detail fetch not frozen here |
| Pagination | `page`, `pageSize`, `totalCount` |
| Primary identity | job `id` |

## Field Mapping

| Source field | Normalized field | Rule |
| --- | --- | --- |
| `id` | `externalJobId` | Required |
| `title` | `title` | Required |
| `teaser` | `description` candidate | Sanitize |
| `companyName` | `company.name` | Required fallback text |
| `branding.serpLogoUrl` | `company.logoUrl` | Optional |
| `locations[].label` | `location.display` | Preserve |
| `salaryLabel` | `salary.display` | Empty string becomes `null`; parse numeric only when reliable |
| `listingDate.dateTimeUtc` | `postedAt` | Prefer over relative label |
| `listingDate.label` | `postedLabel` | Display-only |
| `classifications[]` | `category` | Optional |
| `workTypes[]` | `employmentType` | Map text |
| `workArrangements.displayText` | `workType` | Nullable |
| `bulletPoints[]` | `requirements` candidate | Sanitize |
| `tags[]` | optional display metadata | Do not treat as canonical status |

## Error Behavior

- Missing or expired bearer auth stops JobStreet run until credential refresh.
- Empty `salaryLabel` must not become `0`.
- Facets, suggestions, cookies, request ids, and visitor/session ids are source noise.
- If source auth fails, keep previous rows and mark JobStreet freshness degraded.

