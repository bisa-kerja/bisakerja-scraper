---
title: Scraper System Landscape
description: Scraper-owned view of the Bisakerja service landscape, responsibilities, and data ownership boundaries.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper System Landscape

The Bisakerja Scraper service is the ingestion layer for external job listings. It does not own user workflows, application authorization, frontend responses, or model inference decisions.

## Service Map

| Component | Primary responsibility | Scraper relationship |
| --- | --- | --- |
| Frontend UI | User-facing search, job detail, tracker, profile, and AI flows | No direct scraper dependency |
| Backend API | Auth, authorization, product workflow orchestration, frontend-safe API responses | Reads normalized job records written by scraper-owned ingestion |
| Scraper API | External source fetching, raw payload capture, normalization, enrichment handoff, sync preparation | Owner |
| Model API | Fit scoring, skill gap, recommendation, and CV analysis outputs | Receives prepared context through Backend API or documented enrichment jobs only |
| PostgreSQL | Durable user, job, and workflow state | Stores normalized job records consumed by Backend API |
| Local Scraper DB | Raw captures, staging rows, ingestion runs, retry state | Scraper-owned operational store |

## Scraper Responsibility

| Area | Ownership |
| --- | --- |
| Source adapters | Scraper API owns Dealls, Glints, JobStreet, and Kalibrr adapters |
| Raw payloads | Scraper API stores and redacts raw capture artifacts |
| Normalized jobs | Scraper API maps source data into Backend API-compatible records |
| Deduplication | Scraper API owns source-local identity and upsert preparation |
| Freshness | Scraper API owns `lastSeenAt`, status, and ingestion run metadata |
| User-facing read shape | Backend API owns response envelope and product-safe transformation |

## Data Ownership Boundary

```text
External Job Platforms
  -> Scraper API
  -> Local Scraper DB
  -> normalized job records
  -> Main Backend DB
  -> Backend API
  -> Frontend UI
```

Rules:

- The scraper treats all source data as untrusted until parsed, validated, normalized, and sanitized.
- The Backend API reads normalized job records and must not depend on raw source payload shape.
- Frontend UI must call Backend API, not Scraper API or external job sources.
- Backend API owns user identity, profile, bookmarks, application tracker, and user-specific AI request orchestration.
- Scraper API owns job source freshness and normalized job write/upsert behavior.

## Source Landscape

| Source | Transport | Current role | Source risk |
| --- | --- | --- | --- |
| Dealls | REST, semi-public | Rich list payload, no separate detail endpoint required for MVP | API drift and nullable salary/company fields |
| Glints | Unofficial GraphQL | List-first source, no captured detail endpoint | GraphQL drift and browser-header dependency |
| JobStreet | GraphQL with bearer auth | List and detail-ready source fields with rich UI metadata | Token/session requirement and UI noise |
| Kalibrr | Next.js `_next/data` | List payload includes detail HTML fields | Dynamic `buildId` and HTML sanitization |

## Platform Rule

The scraper is an adapter layer. Backend database schema and user-facing contracts are not changed by scraper source differences; source variance is absorbed in adapters, normalizers, enrichment, and sync preparation.

