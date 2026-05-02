---
title: Documentation Release Checklist
description: Final quality sweep checklist, validation record, and backlog report for scraper documentation release readiness.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-02
---

# Documentation Release Checklist

Use this checklist before treating scraper docs as release-ready or before publishing a central docs sync bundle.

## Release Scope

| Area | Required state |
| --- | --- |
| Overview | Start here, system landscape, data flow, service interactions, glossary present |
| Integrations | Dealls, Glints, JobStreet, Kalibrr source contracts present |
| References | Raw payload contract, field mapping, domain entities present |
| Modules | Ingestion, parsing-normalization, deduplication, persistence, freshness present |
| Operations | Security, observability, testing, deployment, sync, release checklist present |
| Standards | Metadata, naming, redaction, contribution, review, lifecycle, health, versioning present |
| Generated | Generated reference landing page present and labeled |
| Roadmap | Alignment and future expansion present |

## Quality Sweep

| Check | Expected result | Status |
| --- | --- | --- |
| Required target files | Release-scope files exist | Pass by local validation |
| Metadata | Active or draft pages have required frontmatter | Pass by local validation |
| Link integrity | Local markdown links resolve | Pass by local validation |
| Secret safety | No raw bearer, cookie, session, visitor, or device tokens | Pass by local validation |
| Scope ownership | Scraper docs do not replace Backend API or central docs ownership | Pass by review |
| Terminology | Backend API, Scraper API, Model API, Frontend UI names stay consistent | Pass by review |
| Source matrix | Source list/detail, auth/header, nullability, identity captured | Pass by review |
| Lifecycle | Pages include owner, reviewers, status, and review date | Pass by local validation |
| Sync readiness | Central path rules and generated reference rules documented | Pass by review |

## Validation Record

| Date | Check | Result |
| --- | --- | --- |
| 2026-05-01 | Release-scope files, required metadata, local links, secret-pattern scan | Pass: 63 docs checked |
| 2026-05-02 | Release readiness checker for docs, fixtures, raw captures, and env example | Pass: automated local validation |
| 2026-05-02 | Scraper validation suite | Pass: format, lint, unit, contract, integration, smoke, full tests, and smoke CLI |

## Root Context Alignment

| Source | Required alignment |
| --- | --- |
| `bisakerja-product-idea.md` | Docs keep MVP focus on job aggregation, decision support, AI job fit, and skill gap support |
| `bisakerja-feature-flow.md` | Scraper docs support job list/detail, bookmarks, tracker, AI CV analyzer, and notification handoff as downstream needs |
| `bisakerja-project-plan.md` | Docs reflect capstone scope, team ownership, and four job sources |
| `scraper-flow.md` | Docs preserve `scrape -> normalize -> enrich -> sync -> notify` baseline |
| `dealls.md`, `glints.md`, `jobstreet.md`, `kalibrr.md` | Source contract docs reflect captured endpoint and auth/header reality |
| `raw-response-*.txt` | Raw payload docs describe fields without publishing unsanitized credentials |

## Release Gate

Release-ready means:

- No missing release-scope files.
- No active or draft doc without required metadata.
- No broken local docs links.
- No suspected raw secret in docs.
- No unresolved scope conflict with Backend API or central docs.
- No generated reference presented as hand-authored truth.
- Any known gap has owner and next action.

## Gap And Backlog

| Gap | Impact | Owner | Next action |
| --- | --- | --- | --- |
| Generated route and OpenAPI artifacts are not committed yet | Consumers cannot inspect machine-derived route/schema docs from this repo | `data-ingestion-owner` | Generate after FastAPI routes are implementation-stable |
| Sync readiness artifact is not generated yet | Central sync cannot use a committed machine-readable readiness report | `platform-docs-maintainer` | Add generated readiness report when sync tooling exists |
| Most docs remain `draft` | Pages are reference-derived, not fully implementation-verified | `data-ingestion-owner` | Promote page status after implementation and owner review |
| PostgreSQL-specific CI coverage is not enabled yet | SQLite integration checks do not cover every PostgreSQL-specific behavior | `data-ingestion-owner` | Add a dedicated non-production PostgreSQL job when credentials and runtime are available |

## Related Docs

- [Documentation Health Metrics](../standards/documentation-health-metrics.md)
- [Review Process](../standards/review-process.md)
- [Documentation Sync](./documentation-sync.md)
- [Verification Matrix](./verification-matrix.md)
- [CI Quality Gates](./ci-quality-gates.md)
- [Release Readiness](./release-readiness.md)
