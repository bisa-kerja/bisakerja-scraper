---
title: Payload Redaction Policy
description: Redaction rules for source captures, public documentation examples, logs, fixtures, and scraper debugging artifacts.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Payload Redaction Policy

Raw source captures are useful for mapper validation, but published docs and shared artifacts must not leak credentials or user/session data.

## Always Redact

| Data | Examples |
| --- | --- |
| Auth credentials | `authorization`, bearer tokens, API keys |
| Cookies | `cookie`, `set-cookie`, session cookies |
| Session identifiers | `x-seek-ec-sessionid`, visitor ids, device ids |
| Tracking identifiers | request ids, experiment ids, analytics ids when user/session-specific |
| User-specific source state | `saved`, `applied`, account-specific eligibility state when tied to a real session |

## Allowed In Docs

- Header names without real values.
- Placeholder values like `<redacted>` or `<token>`.
- Public base URLs and endpoint paths.
- Non-sensitive query parameter names.
- Sanitized example payload fields needed for mapping.

## Redaction Pattern

```http
authorization: Bearer <redacted>
cookie: <redacted>
x-seek-ec-sessionid: <redacted>
```

Do not preserve token length, cookie fragments, or stable session prefixes.

## Storage Rules

- Internal raw payload storage may keep response bodies needed for replay.
- Request headers should be stored only after secret fields are removed or encrypted by an approved mechanism.
- Logs should contain source platform, status code, count, timing, and sanitized error class.
- Documentation examples must be manually or automatically checked for secret patterns before publishing.

## Fixture Sanitization

Raw captures used for automated tests must be generated through a sanitizer before being committed.

Required sanitizer behavior:

- Redact bearer credentials.
- Redact `cookie` and `set-cookie` values.
- Redact CSRF, session, visitor, and device identifiers.
- Redact sensitive JSON keys recursively.
- Keep only a small representative sample of arrays.
- Preserve valid JSON when the source capture contains a JSON response body.

Fixture directories use one folder per source under `tests/fixtures/raw/<source>/`. Generated fixtures are safe for parser and contract tests, but they are not a substitute for protected internal raw captures.

## Review Checklist

- No bearer token values.
- No cookie values.
- No session or visitor id values.
- No raw user-specific source state.
- No untrusted HTML shown as executable/rendered content.
- All example credentials are placeholders.
