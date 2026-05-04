---
title: Scraper API Contract
description: Internal contract for scraper ingestion outputs, normalized job records, sync handoff, and Backend API consumption.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Scraper API Contract

The scraper contract is a data handoff contract, not a user-facing API contract. The Backend API owns user-facing REST responses.

## Contract Shape

| Area | Required fields |
| --- | --- |
| Source platform | `sourcePlatform.slug`, `sourcePlatform.name` |
| Company | `company.name`, optional source/company metadata |
| Job listing identity | `jobListing.externalJobId`, `jobListing.sourceUrl`, `jobListing.externalApplyUrl` |
| Job listing core | `jobListing.title`, optional normalized title/category/description/requirement summary |
| Job listing enum fields | optional `jobListing.workType`, `jobListing.employmentType`, `jobListing.experienceLevel` |
| Job listing location | optional `jobListing.locationDisplay`, `jobListing.province`, `jobListing.city` |
| Job listing salary | nullable `jobListing.salaryMin`, `jobListing.salaryMax`, `jobListing.salaryCurrency`, `jobListing.salaryPeriod`, `jobListing.salaryDisplay` |
| Job listing freshness | optional `jobListing.sourcePostedAt`, optional `jobListing.sourceUpdatedAt`, required `jobListing.lastSeenAt` |
| Job listing lifecycle | required `jobListing.status` |
| Ingestion run | optional `ingestionRun.sourceRunId` |
| Requirements | `requirements[].type`, `requirements[].value`, optional priority/confidence/source |
| Skills | `skills[].name`, optional confidence/source |

## Write Contract

```text
validated staging rows
  -> resolve source platform
  -> resolve/upsert company
  -> upsert job listing by source identity
  -> replace or upsert requirements/skills
  -> update freshness/status
```

Entity resolution order is significant. Source platform identity is resolved first, company identity second, and job listing identity third. Requirements and skills are written only after the job listing has a valid downstream identity.

## Consumer Contract

Backend API may rely on:

- Stable source-local identity.
- Safe normalized text.
- Nullable salary/location fields.
- Freshness metadata.
- Existing rows remaining readable after source outages.

Backend API must not rely on:

- Raw source payloads.
- Source-specific UI fields.
- Live scraper availability for request-time search.
- Source credentials or source request metadata.

## Backend Handoff Request

The scraper sends normalized jobs to Backend API in bounded batches over an internal service-to-service endpoint.

Default request path:

```text
POST /api/v1/internal/scraper/jobs
```

Authentication uses a service credential in the `Authorization` header:

```text
Authorization: Bearer <managed-service-token>
```

Request body:

```json
{
  "jobs": [
    {
      "sourcePlatform": {
        "slug": "dealls",
        "name": "Dealls"
      },
      "company": {
        "name": "Example Company"
      },
      "ingestionRun": {
        "sourceRunId": "scrape-run-2026-05-04"
      },
      "jobListing": {
        "externalJobId": "123",
        "title": "Backend Engineer",
        "workType": "REMOTE",
        "employmentType": "FULL_TIME",
        "locationDisplay": "Jakarta",
        "salaryCurrency": "IDR",
        "sourceUrl": "https://dealls.com/jobs/backend-engineer-123",
        "externalApplyUrl": "https://dealls.com/jobs/backend-engineer-123",
        "lastSeenAt": "2026-05-02T03:00:00+00:00",
        "status": "ACTIVE"
      },
      "requirements": [],
      "skills": []
    }
  ]
}
```

Behavior rules:

- `2xx` responses mark the sync event as sent.
- `4xx` responses are treated as rejected payloads and are not retried automatically.
- `429` and `5xx` responses may be retried up to the configured limit.
- For list-only sources such as current Glints capture, `description` may stay `null` and `requirementSummary` may stay `null` or safe list-derived summary text.
- `externalApplyUrl` must be present; when source apply URL is unavailable, fallback to `sourceUrl`.
- Foreign-key, missing source platform, and company resolution mismatches are recorded as sync failures with safe response summaries.
- Service tokens, raw payloads, cookies, and request headers are never stored in sync event summaries.
- Response summaries store only safe status class, status code, message, and stable error code.

## Error Behavior

| Error | Contract behavior |
| --- | --- |
| Missing source identity | Reject/quarantine row |
| Missing title or company | Reject or hold from normal visibility |
| Missing salary | Sync with `null` salary |
| Parser drift | Quarantine payload and keep source run partial |
| Enrichment failure | Sync base normalized job when required fields are valid |
| Duplicate source job | Upsert by source identity |

## AI Enrichment Output Contract

AI enrichment output is an optional supplement to the normalized job contract. It must be derived only from safe normalized job text.

Input fields:

| Field | Rule |
| --- | --- |
| `title` | Required normalized job title |
| `description` | Optional clean text; no raw HTML, headers, tokens, cookies, or raw payloads |
| `requirements` | Optional clean text |
| `company` | Required company name |
| `source` | Required source platform |

Output fields:

| Field | Rule |
| --- | --- |
| `skills[].name` | Skill name supported by input text |
| `skills[].confidence` | Number from `0` to `1` |
| `requirements[].type` | `SKILL`, `EXPERIENCE`, `EDUCATION`, or `OTHER` |
| `requirements[].value` | Requirement text supported by input text |
| `requirements[].confidence` | Number from `0` to `1` |
| `confidence` | Overall confidence from `0` to `1` |
| `warnings[]` | Safe notes about ambiguity or missing evidence |

Invalid output handling:

- Unsupported skills or requirements are rejected as invalid enrichment output.
- Invalid enums, missing required fields, extra fields, or malformed structured output are rejected.
- Rejected enrichment output must not write unsupported facts into normalized job data.
- Base normalized job sync may continue when required non-AI fields satisfy the visibility gate.

## Sync Event State

Each normalized job handoff records an auditable sync event.

| Field | Purpose |
| --- | --- |
| `target` | Downstream system name, usually `backend` |
| `normalizedJobId` | Local normalized job record |
| `payloadHash` | Stable hash of the normalized payload sent downstream |
| `status` | `pending`, `sent`, `failed`, or `dead-letter` |
| `attemptCount` | Number of recorded send attempts |
| `responseSummary` | Safe response metadata for audit and triage |

The idempotency key is `target + normalizedJobId + payloadHash`. Retrying the same payload reuses the existing event; changing the normalized payload creates a new event.
