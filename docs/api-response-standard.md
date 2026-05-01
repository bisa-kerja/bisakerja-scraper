---
title: Scraper API Response Standard
description: Internal scraper response envelope, pagination metadata, error mapping, request id behavior, and sensitive payload rules.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper API Response Standard

Scraper HTTP interfaces, if exposed, use the same envelope shape expected across Bisakerja services. The envelope is for internal operations and must not expose raw source credentials or unsanitized payloads.

## Envelope

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `success` | boolean | Yes | Request outcome |
| `message` | string | Yes | Safe operational summary |
| `data` | object, array, or null | Yes | Payload or `null` on error |
| `meta` | object or null | Success only | Pagination, filters, sort, run context |
| `error` | object or null | Error only | Stable machine-readable error |

Success responses omit `error`. Error responses set `data` to `null`.

## Success Example

```json
{
  "success": true,
  "message": "Ingestion run accepted",
  "data": {
    "id": "run_20260501_010000",
    "sourcePlatform": "all",
    "stage": "full",
    "status": "QUEUED"
  },
  "meta": null
}
```

## List Example

```json
{
  "success": true,
  "message": "Ingestion runs retrieved",
  "data": [
    {
      "id": "run_20260501_010000",
      "sourcePlatform": "jobstreet",
      "status": "PARTIAL"
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
      "sourcePlatform": "jobstreet"
    },
    "sort": "created_desc"
  }
}
```

## Error Shape

```json
{
  "success": false,
  "message": "Validation failed",
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "details": [
      {
        "path": "sourcePlatform",
        "message": "Unsupported source platform",
        "code": "invalid_enum"
      }
    ],
    "requestId": "req_123"
  }
}
```

## Error Catalog

| Code | Status | Use |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Invalid body, query, params, source slug, stage, pagination, sort |
| `UNAUTHENTICATED` | 401 | Missing/invalid internal credential |
| `FORBIDDEN` | 403 | Credential lacks operator permission |
| `NOT_FOUND` | 404 | Run, source, or staging record not found |
| `CONFLICT` | 409 | Run already active or duplicate unsafe operation |
| `RATE_LIMITED` | 429 | Operator/source request limit hit |
| `SOURCE_AUTH_FAILED` | 502 | Source credential rejected or expired |
| `SOURCE_SCHEMA_DRIFT` | 502 | Source response no longer matches mapper contract |
| `DOWNSTREAM_ERROR` | 502 | DB/enrichment/sync dependency returned invalid result |
| `SERVICE_UNAVAILABLE` | 503 | Required DB, queue, source, or worker unavailable |
| `INTERNAL_SERVER_ERROR` | 500 | Unexpected failure |

## Pagination Metadata

Use page pagination for internal list endpoints.

| Field | Rule |
| --- | --- |
| `page` | Starts at `1` |
| `limit` | Maximum `100` |
| `total` | Total matching records when cheap and safe |
| `totalPages` | Derived from `total` and `limit` |
| `hasNextPage`, `hasPrevPage` | Required booleans |

## Sanitization Rules

Responses must not include:

- Raw source request headers.
- Bearer tokens, cookies, session ids, visitor ids, device ids.
- Unsanitized HTML.
- Full raw source payloads.
- Stack traces.
- DB connection strings.

Allowed response data:

- Source slug.
- Safe status code class.
- Sanitized error category.
- Counts and timings.
- Redacted examples with `<redacted>` only when field name matters.

## Request ID

- Accept `x-request-id` when provided by trusted internal callers.
- Generate one when missing.
- Include `requestId` in every error response.
- Write the same id to structured logs.

## Related Docs

- [API Reference](./api-reference.md)
- [Payload Redaction Policy](./standards/payload-redaction-policy.md)
- [Security](./operations/security.md)

