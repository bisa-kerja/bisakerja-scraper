---
title: Scraper API Reference
description: Internal scraper interface reference for health, ingestion control, run status, normalized handoff, query semantics, and generated contract strategy.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Scraper API Reference

This page defines scraper-owned interfaces. They are internal operations surfaces and data handoff contracts, not frontend-facing product APIs.

## Interface Boundary

| Consumer | Allowed use | Not allowed |
| --- | --- | --- |
| Scheduler/worker | Trigger configured ingestion stages | Send user identity or frontend tokens |
| Scraper operator | Check run status and source health | Read raw secrets or unsanitized request headers |
| Backend API | Consume normalized job records and optional freshness summary | Read raw source payloads or source credentials |
| Frontend UI | None in MVP | Direct Scraper API calls |

## Base Path And Versioning

If HTTP endpoints are exposed, mount them under:

```text
/api/v1
```

Rules:

- `v1` is the MVP internal contract.
- Additive fields may be added when existing meanings do not change.
- Breaking changes require a migration note and generated reference refresh.
- Health endpoints may live outside `/api/v1` if infrastructure needs stable unauthenticated checks.

## Endpoint Inventory

| Method | Path | Auth class | Purpose | Status |
| --- | --- | --- | --- | --- |
| `GET` | `/health/live` | Infrastructure/public | Process liveness | Available |
| `GET` | `/health/ready` | Infrastructure-restricted | DB/config readiness | Available |
| `POST` | `/api/v1/runs` | Internal service credential | Trigger an ingestion run | Planned |
| `GET` | `/api/v1/runs` | Internal service credential | List ingestion runs | Planned |
| `GET` | `/api/v1/runs/:runId` | Internal service credential | Inspect one run | Planned |
| `GET` | `/api/v1/sources` | Internal service credential | Source freshness/config summary | Planned |
| `GET` | `/api/v1/jobs` | Internal service credential | List normalized local job records | Available |
| `GET` | `/api/v1/jobs/:jobId` | Internal service credential | Inspect one normalized local job record | Available |
| `GET` | `/api/v1/jobs/staging` | Internal service credential | Debug normalized staging records | Optional |

The stable product job search API remains owned by Backend API.

Manual operator execution is currently exposed through the repository CLI, not HTTP:

```bash
PYTHONPATH=src uv run python -m cli.pipeline run --stage full --source all --limit 1 --dry-run --env-file .env.example
PYTHONPATH=src uv run python -m cli.pipeline status --run-id <run-id> --env-file .env
```

The CLI output is safe operational JSON. It does not expose service tokens, bearer tokens, database passwords, cookies, raw headers, or raw payload bodies.

## Internal Jobs Query Contract

`GET /api/v1/jobs` returns normalized local jobs from the scraper operational store. It is intended for internal diagnostics and service-to-service inspection only. Product search and public job detail remain owned by Backend API.

Supported query fields:

| Query | Default | Constraint |
| --- | --- | --- |
| `page` | `1` | Minimum `1` |
| `limit` | `20` | Minimum `1`, maximum `100` |
| `sourcePlatform` | none | `dealls`, `glints`, `jobstreet`, `kalibrr`, or `kitalulus` |
| `freshness` | none | `active`, `inactive`, `expired`, or `unknown` |
| `location` | none | Case-insensitive local payload search |
| `keyword` | none | Case-insensitive title, company, and local payload search |

Successful list response:

```json
{
  "success": true,
  "message": "Jobs retrieved",
  "data": [
    {
      "id": "job_123",
      "sourcePlatform": "dealls",
      "externalJobId": "123",
      "title": "Backend Engineer",
      "companyName": "Example Company",
      "sourceUrl": "https://example.com/jobs/123",
      "applyUrl": "https://example.com/jobs/123/apply",
      "status": "active",
      "lastSeenAt": "2026-05-02T03:00:00+00:00",
      "postedAt": null,
      "payload": {
        "title": "Backend Engineer"
      }
    }
  ],
  "meta": {
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 1,
      "totalPages": 1,
      "hasNextPage": false,
      "hasPrevPage": false
    },
    "filters": {
      "sourcePlatform": "dealls",
      "freshness": "active",
      "location": null,
      "keyword": null
    },
    "sort": "last_seen_desc"
  }
}
```

`GET /api/v1/jobs/:jobId` returns the same safe normalized record shape for one job. Missing jobs return `404 NOT_FOUND`.

## Health Contract

`GET /health/live` confirms the process can serve HTTP traffic. It does not open a database connection or call external job sources.

Successful response:

```json
{
  "success": true,
  "message": "Service is live",
  "data": {
    "status": "live"
  },
  "meta": null
}
```

`GET /health/ready` confirms required runtime dependencies are usable before traffic or scheduled work is considered safe. The readiness check performs a lightweight scraper database query.

Successful response:

```json
{
  "success": true,
  "message": "Service is ready",
  "data": {
    "status": "ready"
  },
  "meta": null
}
```

Unavailable dependency response:

```json
{
  "success": false,
  "message": "Service dependency is unavailable",
  "data": null,
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "details": {
      "dependency": "scraper-db"
    },
    "requestId": "req_123"
  }
}
```

Every health response includes the configured request id header. Callers may provide the request id; otherwise the app generates one.

## Trigger Run Contract

`POST /api/v1/runs` starts a controlled scraper pipeline run.

Implementation status: planned only. The current app exposes health and internal jobs routes, but does not yet implement `POST /api/v1/runs` or `GET /api/v1/runs`. Use `cli.pipeline` for manual operator runs until the HTTP route is available.

Allowed body fields:

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `sourcePlatform` | string | No | One of `dealls`, `glints`, `jobstreet`, `kalibrr`, `kitalulus`; omitted means all configured sources |
| `stage` | string | No | `scrape`, `normalize`, `enrich`, `sync`, or `full`; default should be explicit in config |
| `limit` | number | No | Bounded positive integer for controlled manual runs |
| `force` | boolean | No | Requires operator permission; never default true |

Success returns an ingestion run id and accepted stage plan.

## Run Status Contract

Run status responses should expose safe operational state only.

| Field | Meaning |
| --- | --- |
| `id` | Internal ingestion run id |
| `sourcePlatform` | Source slug or `all` |
| `stage` | Current stage |
| `status` | `QUEUED`, `RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`, `CANCELLED` |
| `counts` | Safe totals such as fetched, normalized, quarantined, synced |
| `startedAt`, `finishedAt` | ISO timestamps |
| `errorSummary` | Sanitized error class/message, no raw payload |

## Query Semantics

List endpoints use page pagination.

| Query | Default | Constraint |
| --- | --- | --- |
| `page` | `1` | Minimum `1` |
| `limit` | `20` | Minimum `1`, maximum `100` |
| `sourcePlatform` | none | Source slug allowlist |
| `status` | none | Endpoint-specific enum allowlist |
| `sort` | `created_desc` | Stable documented values only |

Unsupported filters or sort values return `422 VALIDATION_ERROR`.

## Field Policy

| Field class | Rule |
| --- | --- |
| Canonical fields | Prefer structured fields such as `salaryMin`, `salaryMax`, `postedAt`, `lastSeenAt`, `employmentType` |
| UI labels | Keep `salaryLabel`, relative posted labels, and source tags as derived/display-only fields |
| Raw source content | Internal only; never expose through public responses |
| HTML content | Store raw only internally; expose sanitized text or explicitly allowed safe HTML |
| Noise fields | Drop tracking, experiment, UI state, session, and account-specific fields |

## Generated Reference Strategy

Generated artifacts should live under `docs/generated/`.

| Artifact | Purpose | Rule |
| --- | --- | --- |
| `docs/generated/index.md` | Human-readable generated reference entry | Always present |
| `docs/generated/routes.md` | Route inventory from FastAPI app when implementation exists | Generated, not hand-maintained |
| `docs/generated/openapi.json` | Machine-readable OpenAPI when implementation exists | Generated from app source |

Generated files must be labeled as generated and regenerated after route/schema changes.

## Related Docs

- [API Response Standard](./api-response-standard.md)
- [Scraper API Contract](./integrations/scraper-api-contract.md)
- [Raw Payload Contract](./references/raw-payload-contract.md)
- [Authentication and Trust Boundaries](./overview/authentication-and-trust-boundaries.md)
