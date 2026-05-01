from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integrations.sources.glints.list import RawSourceJob


class GlintsDetailFallbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_platform: Literal["glints"] = "glints"
    external_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    detail_coverage: Literal["unavailable"] = "unavailable"
    raw_payload: dict[str, Any]
    field_provenance: dict[str, str]


def build_glints_detail_fallback(raw_job: RawSourceJob) -> GlintsDetailFallbackResult:
    return GlintsDetailFallbackResult(
        external_id=raw_job.external_id,
        source_url=raw_job.source_url,
        raw_payload=raw_job.raw_payload,
        field_provenance={
            "external_id": "list.id",
            "title": "list.title",
            "company": "list.company",
            "location": "list.location",
            "salary": "list.salaries",
            "skills": "list.skills",
            "source_url": "derived_from_list_id",
            "description": "unavailable",
            "requirements": "unavailable",
        },
    )
