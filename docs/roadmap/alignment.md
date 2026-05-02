---
title: Scraper Alignment
description: Scope lock, audit matrix, MVP boundary, and source-contract reality for Bisakerja Scraper documentation.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Alignment

This page locks the initial documentation boundary for the Bisakerja Scraper service.

## Scope Boundary

| Area | Central-summary | Service-owned detail |
| --- | --- | --- |
| Product vision | Link/summary only | Not owned here |
| User journeys | Link/summary only | Not owned here |
| Backend API auth, bookmarks, tracker, AI workflow | Link/summary only | Not owned here |
| Scraper architecture | Summary in central docs | Owned here |
| Source adapters | Summary in central docs | Owned here |
| Raw payload storage | Summary in central docs | Owned here |
| Normalization and dedup | Summary in central docs | Owned here |
| Daily scraper pipeline | Summary in central docs | Owned here |
| Payload redaction and source credential handling | Summary in central docs | Owned here |

## MVP Boundary

| In MVP | Future or external |
| --- | --- |
| Aggregate jobs from 1-2 initial sources while keeping four-source schema support | Cross-source duplicate merge |
| Preserve all four source slugs: `dealls`, `glints`, `jobstreet`, `kalibrr` | Direct ATS integration |
| Normalize list/detail fields into Backend API-compatible job records | Auto-apply |
| Use source-local identity: `sourcePlatform + externalJobId/slug/id` | Employer dashboard |
| Store raw payloads for replay/debug with secret redaction | Native mobile support |
| Daily batch pipeline: scrape, normalize, enrich, sync, notify handoff | Advanced analytics platform |

## Source Contract Reality

| Source | Transport | Auth reality | List coverage | Detail coverage | Stable identity | Key handling |
| --- | --- | --- | --- | --- | --- | --- |
| Dealls | REST `GET /v1/explore-job/job` | Semi-public, browser-like headers recommended | Available, rich list fields | No separate detail endpoint found; list is rich enough for MVP | `id` plus `slug` | `salaryRange` can be `null`; company rank can be `null`; preserve skills and company fields when present |
| Glints | Unofficial GraphQL `searchJobsV3` | No API key seen; browser headers required; cookies optional and must not be documented raw | Available | Detail endpoint not visible in capture | GraphQL job `id` | Treat as list-first source; fallback detail URL; expect API drift |
| JobStreet | GraphQL `JobSearchV6` | Bearer auth and session cookies observed; must be configured securely and redacted | Available | Detail data available through captured GraphQL shape and source URL path assumptions | numeric `id` | `salaryLabel` can be empty; relative labels need parsed timestamp source; response has UI noise |
| Kalibrr | Next.js `_next/data/{buildId}` JSON | Public-like, requires `x-nextjs-data: 1`; browser headers recommended | Available | Detail fields included in `jobs[]` payload | numeric `id` plus `slug` | Dynamic `buildId`; `description` and `qualifications` are HTML; salary fields can be null |

## Field Handling Rules

| Field class | Rule |
| --- | --- |
| Salary | Store `null` for unknown min/max; do not infer precise value from vague or empty labels |
| HTML text | Sanitize `description`, `qualifications`, and requirement HTML before display or model use |
| Relative dates | Preserve source timestamp when present; treat labels like `3 hari yang lalu` as display-only unless parsed with capture time |
| UI/noise fields | Ignore facets, suggestions, tracking ids, cookies, flags not needed by normalized schema |
| Source identity | Use source platform plus external id, slug, or numeric id; never rely on title/company alone |
| Secrets | Redact bearer tokens, cookies, session ids, tracking ids, and user identifiers from public docs |

## Root Context Audit

| Source file | Used for |
| --- | --- |
| `bisakerja-product-idea.md` | Product MVP, target users, AI-first job decision context |
| `bisakerja-feature-flow.md` | User journey, job search/detail, bookmark, tracker, AI CV analyzer, notification touchpoints |
| `bisakerja-project-plan.md` | Capstone scope, team ownership, MVP/future boundary |
| `scraper-flow.md` | Daily pipeline, FastAPI scraper boundary, staging DB, enrichment, sync |
| `example-folder-structure.md` | Existing scraper module structure and adapter/pipeline/repository patterns |
| `dealls.md` | Dealls REST contract and field expectations |
| `glints.md` | Glints GraphQL list contract and detail limitation |
| `jobstreet.md` | JobStreet GraphQL auth, list contract, UI-oriented fields |
| `kalibrr.md` | Kalibrr Next.js data contract, dynamic build id, HTML detail fields |
| `raw-response-dealls.txt` | Real header/query/payload evidence for Dealls |
| `raw-response-glints.txt` | Real header/query/payload evidence for Glints |
| `raw-response-jobstreet.txt` | Real header/query/payload evidence for JobStreet, including redaction requirement |
| `raw-response-kalibrr.txt` | Real header/query/payload evidence for Kalibrr |

## Coverage Plan

| Area | Current coverage | Planned coverage |
| --- | --- | --- |
| Overview | Start Here, role paths, glossary | Data flow, async workflows |
| Services | Scraper API landing page | Synced/implementation pages when service docs exist |
| Operations | Operations landing page | Runbooks, schedules, failure recovery |
| Standards | Metadata, naming, redaction, contribution, review, lifecycle, health, archival, versioning | Structural change control and release governance |
| References | Reference landing page | Source mappings, raw payload contract |
| Roadmap | Alignment and future expansion | Generated references, contract fixtures, source drift playbooks |

## Verification Notes

- Root context files are covered in the audit matrix.
- Source-contract matrix distinguishes list and detail reality per source.
- Boundary stays scraper-only and does not create central platform documentation.
- Final release readiness includes metadata, links, scope, lifecycle, health, sync, and root-context checks.
