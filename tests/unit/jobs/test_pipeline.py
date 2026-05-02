from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.errors import FetchError, NormalizeError
from integrations.sources.mapper_utils import SourceMapperResult
from jobs.pipeline import PipelineConfig, PipelineOrchestrator
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CompanySchema,
    LocationSchema,
    SourceMetadataSchema,
    SourcePlatform,
)
from modules.persistence import (
    Base,
    JobPersistenceRepository,
    NormalizationQuarantine,
    NormalizedJob,
    RawJobInput,
)
from modules.quarantine import QuarantineRepository
from modules.runs import RunCounts, RunStateTracker


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


@pytest.mark.asyncio
async def test_stage_enrich_does_not_scrape_again() -> None:
    with session_scope() as session:
        source = FakeSource("dealls", ["job-1"])
        hook_calls: list[tuple[str, str]] = []

        async def enrich_hook(run_id: str, correlation_id: str) -> RunCounts:
            hook_calls.append((run_id, correlation_id))
            return RunCounts(persisted=2)

        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=JobPersistenceRepository(session),
            run_tracker=RunStateTracker(session),
            stage_hooks={"enrich": enrich_hook},
            correlation_id_factory=lambda: "corr-1",
        )

        result = await orchestrator.run_enrich(run_id="run-enrich")

        assert result.status == "completed"
        assert result.counts.persisted == 2
        assert source.fetch_count == 0
        assert hook_calls == [("run-enrich", "corr-1")]


@pytest.mark.asyncio
async def test_normalize_stage_quarantines_malformed_raw_job() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        raw = repository.upsert_raw_job(raw_input("run-scrape", "bad-1"))[0]
        session.commit()
        source = MalformedSource()
        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=repository,
            run_tracker=RunStateTracker(session),
            quarantine=QuarantineRepository(session),
            correlation_id_factory=lambda: "corr-1",
        )

        result = await orchestrator.run_normalize(run_id="run-normalize")

        quarantine = session.scalar(
            select(NormalizationQuarantine).where(NormalizationQuarantine.raw_job_id == raw.id)
        )
        assert result.status == "partial"
        assert result.counts.skipped == 1
        assert quarantine is not None
        assert quarantine.error_category == "NORMALIZE_ERROR"
        assert session.scalars(select(NormalizedJob)).all() == []


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
        self.fetch_count = 0

    async def fetch_raw_jobs(self) -> list[RawJobStub]:
        self.fetch_count += 1
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


class MalformedSource(FakeSource):
    def __init__(self) -> None:
        super().__init__("dealls", [])

    def map_raw_job(self, raw_job: RawJobStub, *, scraped_at: datetime) -> SourceMapperResult:
        raise NormalizeError(
            "missing source identity",
            source_platform=self.source_platform,
            external_id=raw_job.external_id,
            details={"source_field_path": "id"},
        )


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


def raw_input(run_id: str, external_id: str) -> RawJobInput:
    return RawJobInput(
        scrape_run_id=run_id,
        source_platform="dealls",
        external_id=external_id,
        source_url=f"https://dealls.com/jobs/{external_id}",
        raw_payload={"id": external_id, "title": "Backend Engineer"},
        scraped_at=datetime.now(UTC),
    )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
