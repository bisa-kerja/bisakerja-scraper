---
title: Scraper API Contract
description: Internal contract for scraper ingestion outputs, normalized job records, sync handoff, and Backend API consumption.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-05
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

The scraper `BACKEND_SYNC_SERVICE_TOKEN` value must equal the Backend API `SCRAPER_API_SERVICE_TOKEN` value.

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
- Current Backend API success response is `200` with a standard success envelope.
- `4xx` responses are treated as rejected payloads and are not retried automatically.
- `429` and `5xx` responses may be retried up to the configured limit.
- Sync batches must contain `1` to `25` jobs.
- Large sync runs are split into repeated requests. For example, `205` jobs with `BACKEND_SYNC_BATCH_SIZE=25` sends nine Backend API requests with `25` x 8 and `5` jobs.
- Retryable chunk failures may trigger adaptive chunk downsizing so a large failing chunk can be retried as smaller chunks in the same run.
- Sync diagnostics track chunk attempt counts, chunk failure counts, status class distribution, and chunk latency percentiles (`p50` and `p95`).
- Completed sync runs with `sent=0` must include an explicit safe reason classifier.
- For list-only sources such as current Glints capture, `description` may stay `null` and `requirementSummary` may stay `null` or safe list-derived summary text.
- `externalApplyUrl` must be present; when source apply URL is unavailable, fallback to `sourceUrl`.
- Foreign-key, missing source platform, and company resolution mismatches are recorded as sync failures with safe response summaries.
- Service tokens, raw payloads, cookies, and request headers are never stored in sync event summaries.
- Response summaries store only safe status class, status code, message, and stable error code.

Success response summary stored by the scraper:

```json
{
  "statusCode": 200,
  "statusClass": "2xx",
  "success": true,
  "message": "Scraper jobs synced successfully",
  "endpointPath": "/api/v1/internal/scraper/jobs"
}
```

## Notification Handoff Request

After successful sync, the scraper sends synced jobs to Backend API notification handling.

Default request path:

```text
POST /api/v1/internal/notification-events
```

Authentication uses the same service credential:

```text
Authorization: Bearer <managed-service-token>
```

Request body:

```json
{
  "runId": "scrape-run-2026-05-05",
  "candidates": [
    {
      "eventId": "scrape-run-2026-05-05:glints:123",
      "syncEventId": "sync-event-id",
      "sourcePlatform": "glints",
      "externalJobId": "123",
      "title": "Backend Engineer",
      "companyName": "Example Company",
      "sourceUrl": "https://glints.example/job/123",
      "location": {
        "display": "Jakarta"
      },
      "salary": null,
      "status": "active",
      "lastSeenAt": "2026-05-05T03:00:00+00:00"
    }
  ]
}
```

Behavior rules:

- Current Backend API success response is `200` with a standard success envelope.
- Notification candidate batches may contain up to `1000` candidates.
- Large notification handoff runs are split into repeated candidate requests so one request never exceeds the Backend API limit.
- Non-`2xx` responses mark handoff events failed or dead-letter based on attempt count.
- Response summaries store status code, status class, stable error code, message, and endpoint path only.

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

Content expectation for consistency:

| Field | Expectation |
| --- | --- |
| `description` | Human-readable prose that follows `AI_OUTPUT_LANGUAGE` (default `english`), informative, and not a vague one-liner |
| `requirementSummary` (downstream `jobListing.requirementSummary`) | Readable summary of core qualifications, consistent with `AI_OUTPUT_LANGUAGE` |
| `requirements` | Factual, clean requirement text ready for downstream parsing |
| `skills` | Skill spesifik berbasis evidence dan tanpa duplikasi |

Output fields:

| Field | Rule |
| --- | --- |
| `skills[].name` | Skill name supported by input text |
| `skills[].confidence` | Number from `0` to `1` |
| `requirements[].type` | `SKILL`, `EXPERIENCE`, `EDUCATION`, or `OTHER` |
| `requirements[].value` | Requirement text supported by input text and written in natural language per `AI_OUTPUT_LANGUAGE` |
| `requirements[].confidence` | Number from `0` to `1` |
| `confidence` | Overall confidence from `0` to `1` |
| `warnings[]` | Safe notes about ambiguity or missing evidence, written per `AI_OUTPUT_LANGUAGE` |

Invalid output handling:

- Unsupported skills or requirements are rejected as invalid enrichment output.
- Invalid enums, missing required fields, extra fields, or malformed structured output are rejected.
- Rejected enrichment output must not write unsupported facts into normalized job data.
- Base normalized job sync may continue when required non-AI fields satisfy the visibility gate.
- When requirement/skill evidence exists but output is empty, the result is treated as low-quality and should be retried or replaced by safe deterministic fallback.
- For sync completeness, backend payload fallback enforces at least one requirement relation and one skill relation per job using conservative deterministic derivation when upstream evidence is sparse.

## Sync Event State

Each normalized job handoff records an auditable sync event.

| Field | Purpose |
| --- | --- |
| `target` | Downstream system name, usually `backend` |
| `normalizedJobId` | Local normalized job record |
| `payloadHash` | Stable hash of the serialized backend payload sent downstream |
| `status` | `pending`, `sent`, `failed`, or `dead-letter` |
| `attemptCount` | Number of recorded send attempts |
| `responseSummary` | Safe response metadata for audit and triage |

The idempotency key is `target + normalizedJobId + payloadHash`. Retrying the same serialized backend payload reuses the existing event; changing normalized data or backend serialization creates a new event.
