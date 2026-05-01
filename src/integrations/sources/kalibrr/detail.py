from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ParseError
from integrations.sources.kalibrr.build_id import KALIBRR_SOURCE_PLATFORM
from integrations.sources.kalibrr.list import RawSourceJob, build_kalibrr_source_url


class KalibrrDetailResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    slug: str | None = None
    source_url: str = Field(min_length=1)
    raw_payload: dict[str, Any]
    html_description: str | None = None
    html_qualifications: str | None = None


def parse_kalibrr_detail_payload(raw_job: dict[str, Any]) -> KalibrrDetailResult:
    external_id = raw_job.get("id")
    if isinstance(external_id, bool) or not isinstance(external_id, int | str):
        raise ParseError(
            "Kalibrr detail job missing required id",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    external_id_str = str(external_id)
    if not external_id_str:
        raise ParseError(
            "Kalibrr detail job missing required id",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    slug = raw_job.get("slug")
    return KalibrrDetailResult(
        external_id=external_id_str,
        slug=slug if isinstance(slug, str) and slug else None,
        source_url=build_kalibrr_source_url(raw_job),
        raw_payload=raw_job,
        html_description=_optional_text(raw_job.get("description")),
        html_qualifications=_optional_text(raw_job.get("qualifications")),
    )


def merge_kalibrr_list_and_detail(list_job: RawSourceJob) -> RawSourceJob:
    detail = parse_kalibrr_detail_payload(list_job.raw_payload)
    return RawSourceJob(
        source_platform=list_job.source_platform,
        external_id=list_job.external_id,
        source_url=detail.source_url,
        raw_payload={
            "list": list_job.raw_payload,
            "detail": detail.raw_payload,
            "detailMetadata": {
                "coverage": "embedded",
                "source": "list_job",
                "htmlFields": [
                    field
                    for field, value in {
                        "description": detail.html_description,
                        "qualifications": detail.html_qualifications,
                    }.items()
                    if value
                ],
            },
        },
    )


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
