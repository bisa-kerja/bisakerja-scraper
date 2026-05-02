---
title: Scraper Security Operations
description: Security baseline for scraper trust boundaries, internal auth, source credential handling, input validation, rate limits, logs, artifacts, and dependency hardening.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-02
---

# Scraper Security Operations

The scraper handles untrusted external payloads and sensitive source request material. Security controls must protect internal systems, source credentials, raw captures, and Backend API-consumable data.

## Trust Boundary Summary

| Boundary | Rule |
| --- | --- |
| External source to scraper | Treat all payloads as untrusted |
| Scraper HTTP interface | Internal callers only |
| Scraper raw store | Internal replay/debug only |
| Scraper normalized data to main DB | Validate before sync |
| Backend API to Frontend UI | Backend owns auth, authorization, and frontend-safe response shaping |

## Authentication And Authorization

If HTTP endpoints are exposed:

- Require internal service credentials for run trigger, run status, source health, and staging debug endpoints.
- Do not accept frontend user tokens as scraper credentials.
- Do not expose source credentials in any response.
- Use separate operator permission for force-run or destructive actions.
- Prefer network restriction plus service credential for internal endpoints.

## Source Credential Handling

Store these only in secret/config stores:

- Bearer tokens.
- Cookies.
- Session ids.
- Visitor ids.
- Device ids.
- Anti-abuse identifiers.

Documentation may show header names and placeholders only.

## Input Validation

Validate:

| Input | Required validation |
| --- | --- |
| Trigger body | Source slug, stage enum, limit bounds, force flag |
| Query params | Pagination, status enum, source slug, sort allowlist |
| Source response | Expected payload root, required identity, field type |
| HTML text | Sanitization before staging/display/enrichment |
| Sync payload | Required source identity, title, company, source/apply URL |

Validation failures use the standard response envelope.

## Rate Limits

| Surface | Rule |
| --- | --- |
| Internal HTTP endpoints | Rate limit by caller/token/network |
| Source requests | Per-source limits with bounded retry |
| JobStreet auth failures | Stop source until credential refresh |
| Kalibrr buildId failures | Refresh build id, then bounded retry |
| Enrichment | Batch and throttle to protect downstream providers |

## Log Redaction

Never log:

- Bearer tokens, cookies, session ids, visitor ids, device ids.
- Raw source request headers.
- Full raw source payload bodies.
- DB connection strings.
- Internal service tokens.
- Unsanitized HTML.

Allowed logs:

- Request id.
- Source platform.
- Stage.
- Status code class.
- Counts.
- Duration.
- Sanitized error category.

## Artifact Sanitization

Raw captures used in docs, fixtures, examples, or debugging bundles must remove:

- `authorization`.
- `cookie`.
- `set-cookie`.
- `x-seek-ec-sessionid`.
- `x-seek-ec-visitorid`.
- Device/session/tracking ids.
- User-specific flags tied to real source account state.

Use `<redacted>` only when the field name itself is useful.

Automated release readiness checks scan documentation, raw fixtures, raw captures, and the example environment file for common secret patterns. The scan allows header names and placeholder values, but rejects likely bearer credentials, cookie values, session identifiers, visitor identifiers, device identifiers, and database URLs with non-placeholder passwords.

## Dependency Hardening

- Pin runtime dependencies.
- Review HTTP client, parser, sanitizer, queue, and DB packages before release.
- Keep lockfile committed once implementation exists.
- Run dependency audit in CI when package workflow exists.
- Avoid abandoned packages for HTML sanitization, auth, and queue execution.

## Security Checklist

- [ ] Internal endpoints require service credential or network restriction.
- [ ] Frontend cannot call scraper endpoints.
- [ ] Source credentials live outside repo/docs.
- [ ] Raw request headers are redacted before logs/artifacts.
- [ ] HTML fields are sanitized before staging/display/enrichment.
- [ ] Mapper validates required identity/title/company/source URL.
- [ ] Rate limits exist for internal API and external sources.
- [ ] Source auth failures do not dump provider response bodies.
- [ ] Generated references contain no tokens/cookies/raw payload bodies.
- [ ] Production CORS is not wildcard if HTTP endpoints exist.

## Related Docs

- [Authentication and Trust Boundaries](../overview/authentication-and-trust-boundaries.md)
- [Payload Redaction Policy](../standards/payload-redaction-policy.md)
- [CI Quality Gates](./ci-quality-gates.md)
- [API Response Standard](../api-response-standard.md)
- [Environment Configuration](../environment.md)
