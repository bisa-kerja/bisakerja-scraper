---
title: Future Docs Expansion
description: Future roadmap for scraper documentation growth after the MVP documentation baseline.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Future Docs Expansion

This roadmap tracks documentation areas that should grow after the MVP scraper docs baseline is stable.

## Expansion Priorities

| Priority | Area | Trigger | Output |
| --- | --- | --- | --- |
| 1 | Generated API references | FastAPI routes or OpenAPI schema become stable | `docs/generated/routes.md`, `docs/generated/openapi.json` |
| 2 | Contract fixture docs | Raw fixture tests become part of CI | Fixture catalog and mapper test matrix |
| 3 | Source drift playbooks | Repeated external source changes occur | Per-source drift triage runbook |
| 4 | Release snapshots | Contract behavior differs by release | Versioned central docs bundle |
| 5 | Audience bundles | Repeated onboarding questions by role | Maintained reader collections |

## Future Source Coverage

New job sources may be added only when the docs can capture:

- List and detail endpoint coverage.
- Required request headers or auth strategy.
- Stable identity key.
- Field mapping and nullability.
- Rate limit and retry behavior.
- Sanitized payload examples.

## Future Generated Docs

Generated references should be introduced when manual docs become less reliable than source-driven output.

Candidates:

- FastAPI route inventory.
- OpenAPI schema.
- Normalized schema catalog.
- Adapter capability matrix.
- Sync readiness report.

## Future Governance

Governance should expand only where it reduces drift.

Useful additions:

- Automated stale-page report.
- Central sync manifest checker.
- Per-release docs snapshot diff.
- Owner and reviewer dashboard.

## Non-Goals

- Do not create platform-wide docs from this repository.
- Do not duplicate Backend API behavior.
- Do not publish raw external source payloads without sanitization.
- Do not create versioned docs for every wording change.

## Related Docs

- [Versioning and Audience Strategy](../standards/versioning-and-audience-strategy.md)
- [Documentation Health Metrics](../standards/documentation-health-metrics.md)
- [Raw Payload Contract](../references/raw-payload-contract.md)

