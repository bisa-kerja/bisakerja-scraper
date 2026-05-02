from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.errors import FetchError
from integrations.sources.mapper_utils import SourceMapperResult
from jobs.pipeline import PipelineConfig, PipelineOrchestrator
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CompanySchema,
    LocationSchema,
    SourceMetadataSchema,
    SourcePlatform,
)
from modules.persistence import Base, JobPersistenceRepository, NormalizedJob
from modules.runs import RunStateTracker


@pytest.mark.asyncio
async def test_pipeline_runs_stages_in_order_and_persists_jobs() -> None:
    with session_scope() as session:
        orchestrator = PipelineOrchestrator(
            sources=[FakeSource("dealls", ["job-1"])],
            persistence=JobPersistenceRepository(session),
            run_tracker=RunStateTracker(session),
            config=PipelineConfig(max_concurrency_per_source=2),
            correlation_id_factory=lambda: "corr-1",
        )

        result = await orchestrator.run(run_id="run-1")

        assert result.status == "completed"
        assert result.counts.persisted == 1
        assert result.stage_events == [
            "dealls:scrape",
            "dealls:normalize",
            "dealls:enrich",
            "dealls:sync",
        ]
        assert session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))


@pytest.mark.asyncio
async def test_pipeline_allows_partial_source_failure() -> None:
    with session_scope() as session:
        orchestrator = PipelineOrchestrator(
            sources=[FakeSource("dealls", ["job-1"]), FailingSource()],
            persistence=JobPersistenceRepository(session),
            run_tracker=RunStateTracker(session),
            correlation_id_factory=lambda: "corr-1",
        )

        result = await orchestrator.run(run_id="run-1")

        assert result.status == "partial"
        assert result.counts.fetched == 1
        assert result.counts.persisted == 1
        assert len(result.source_results) == 2
        assert any(source.status == "failed" for source in result.source_results)


@dataclass
class RawJobStub:
    source_platform: str
    external_id: str
    source_url: str
    raw_payload: dict[str, Any]


class FakeSource:
    def __init__(self, source_platform: str, external_ids: list[str]) -> None:
        self.source_platform = source_platform
        self.external_ids = external_ids

    async def fetch_raw_jobs(self) -> list[RawJobStub]:
        return [
            RawJobStub(
                source_platform=self.source_platform,
                external_id=external_id,
                source_url=f"https://example.test/{external_id}",
                raw_payload={"id": external_id},
            )
            for external_id in self.external_ids
        ]

    def map_raw_job(self, raw_job: RawJobStub, *, scraped_at: datetime) -> SourceMapperResult:
        return SourceMapperResult(
            job=canonical_job(raw_job, scraped_at=scraped_at),
            field_provenance={"title": "raw.title"},
        )


class FailingSource:
    source_platform = "glints"

    async def fetch_raw_jobs(self) -> list[RawJobStub]:
        raise FetchError("source unavailable", source_platform=self.source_platform)

    def map_raw_job(self, raw_job: RawJobStub, *, scraped_at: datetime) -> SourceMapperResult:
        raise AssertionError("mapper must not run")


def canonical_job(raw_job: RawJobStub, *, scraped_at: datetime) -> CanonicalJobSchema:
    platform = SourcePlatform(raw_job.source_platform)
    return CanonicalJobSchema(
        source=SourceMetadataSchema(
            platform=platform,
            external_job_id=raw_job.external_id,
            source_url=raw_job.source_url,
            scraped_at=scraped_at,
        ),
        title="Backend Engineer",
        company=CompanySchema(name="Bisakerja"),
        location=LocationSchema(display="Jakarta"),
        last_seen_at=datetime.now(UTC),
    )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
