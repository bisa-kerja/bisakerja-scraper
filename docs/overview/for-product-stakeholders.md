---
title: For Product Stakeholders
description: Role path for product stakeholders understanding scraper impact on job discovery and AI-assisted workflows.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# For Product Stakeholders

This path explains what scraper documentation means for product scope.

## Read In This Order

1. [Start Here](./start-here.md)
2. [Scraper Alignment](../roadmap/alignment.md)
3. [Scraper API](../services/scraper-api/index.md)
4. [Glossary](./glossary.md)

## Product Meaning

- Scraper enables job discovery by collecting jobs from Dealls, Glints, JobStreet, and Kalibrr.
- MVP may start with fewer active sources while keeping schema support for all four.
- Source data quality affects salary filters, location filters, job detail completeness, and AI job fit context.
- Some sources provide rich list data; some require fallback to public job URLs.
- Missing salary or partial detail is expected and should be represented honestly in product behavior.

## Boundary

This documentation does not define product UX, pricing, mentoring, ATS integration, or native mobile scope. It explains scraper data readiness for those workflows.

