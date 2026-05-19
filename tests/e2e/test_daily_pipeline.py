from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from integrations.backend import BackendSyncResult
from integrations.sources.mapper_utils import SourceMapperResult
from jobs.pipeline import PipelineOrchestrator
from modules.enrichment.repositories import EnrichmentSource, EnrichmentStagingRepository
from modules.enrichment.schemas import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentOutput,
    RequirementType,
)
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CanonicalJobStatus,
    CompanySchema,
    LocationSchema,
    SourceMetadataSchema,
    SourcePlatform,
)
from modules.notifications import (
    HandoffSuccess,
    NotificationHandoffRepository,
    RecommendationHandoffWorker,
)
from modules.persistence import (
    Base,
    JobPersistenceRepository,
    NormalizedJob,
    NotificationHandoffEvent,
    SyncEvent,
)
from modules.runs import RunCounts, RunStage, RunStateTracker
from modules.sync import BackendSyncWorker, SyncEventRepository

FIXTURE_ROOT = Path("tests/fixtures/raw")


@pytest.mark.asyncio
async def test_daily_pipeline_fixture_flow_is_offline_and_idempotent() -> None:
    with session_scope() as session:
        sources = [
            FixtureSource("dealls", FIXTURE_ROOT / "dealls" / "sample.json"),
            FixtureSource("glints", FIXTURE_ROOT / "glints" / "sample.json"),
            FixtureSource("jobstreet", FIXTURE_ROOT / "jobstreet" / "sample.json"),
            FixtureSource("kalibrr", FIXTURE_ROOT / "kalibrr" / "sample.json"),
        ]
        backend_client = RecordingBackendClient()
        handoff_client = RecordingHandoffClient()
        last_sync_run_id: dict[str, str] = {}

        async def enrich_hook(run_id: str, correlation_id: str) -> RunCounts:
            repository = EnrichmentStagingRepository(session)
            jobs = list(session.scalars(select(NormalizedJob)).all())
            for job in jobs:
                repository.upsert_output(
                    job=job,
                    output=fake_enrichment_output(),
                    ai_request_log_id=None,
                    source=EnrichmentSource.AI,
                )
            session.commit()
            return RunCounts(persisted=len(jobs))

        async def sync_hook(run_id: str, correlation_id: str) -> RunCounts:
            worker = BackendSyncWorker(
                session=session,
                client=backend_client,
                events=SyncEventRepository(session),
                max_attempts=3,
            )
            result = await worker.sync_eligible_jobs(
                scrape_run_id=run_id,
                limit=20,
                batch_size=2,
            )
            session.commit()
            last_sync_run_id["value"] = run_id
            return RunCounts(fetched=result.attempted, persisted=result.sent, skipped=result.failed)

        async def handoff_hook(run_id: str, correlation_id: str) -> RunCounts:
            worker = RecommendationHandoffWorker(
                session=session,
                repository=NotificationHandoffRepository(session),
                client=handoff_client,
            )
            result = await worker.handoff_synced_jobs(scrape_run_id=last_sync_run_id["value"])
            session.commit()
            return RunCounts(fetched=result.attempted, persisted=result.sent, skipped=result.failed)

        orchestrator = PipelineOrchestrator(
            sources=sources,
            persistence=JobPersistenceRepository(session),
            run_tracker=RunStateTracker(session),
            stage_hooks={
                RunStage.ENRICH.value: enrich_hook,
                RunStage.SYNC.value: sync_hook,
                RunStage.NOTIFY_HANDOFF.value: handoff_hook,
            },
            correlation_id_factory=lambda: "corr-e2e",
        )

        scrape = await orchestrator.run_scrape(run_id="run-e2e-scrape")
        normalize = await orchestrator.run_normalize(run_id="run-e2e-normalize")
        enrich = await orchestrator.run_enrich(run_id="run-e2e-enrich")
        sync = await orchestrator.run_sync(run_id="run-e2e-sync")
        notify = await orchestrator.run_notify_handoff(run_id="run-e2e-notify")

        jobs = list(session.scalars(select(NormalizedJob)).all())
        sync_events = list(session.scalars(select(SyncEvent)).all())
        handoff_events = list(session.scalars(select(NotificationHandoffEvent)).all())
        second_sync = await BackendSyncWorker(
            session=session,
            client=backend_client,
            events=SyncEventRepository(session),
        ).sync_eligible_jobs(scrape_run_id="run-e2e-sync", limit=20, batch_size=2)
        second_handoff = await RecommendationHandoffWorker(
            session=session,
            repository=NotificationHandoffRepository(session),
            client=handoff_client,
        ).handoff_synced_jobs(scrape_run_id="run-e2e-sync")

        assert scrape.status == "completed"
        assert normalize.status == "completed"
        assert enrich.counts.persisted == 4
        assert sync.counts.persisted == 4
        assert notify.counts.persisted == 4
        assert {job.source_platform for job in jobs} == {"dealls", "glints", "jobstreet", "kalibrr"}
        assert all(job.status == CanonicalJobStatus.ACTIVE.value for job in jobs)
        assert len(sync_events) == 4
        assert len(handoff_events) == 4
        assert len(backend_client.payloads) == 2
        assert len(handoff_client.payloads) == 1
        assert second_sync.attempted == 0
        assert second_handoff.attempted == 0


@dataclass(frozen=True)
class FixtureRawJob:
    source_platform: str
    external_id: str
    source_url: str
    raw_payload: dict[str, Any]


class FixtureSource:
    def __init__(self, source_platform: str, fixture_path: Path) -> None:
        self.source_platform = source_platform
        self.fixture_path = fixture_path

    async def fetch_raw_jobs(self) -> list[FixtureRawJob]:
        with self.fixture_path.open() as file:
            payload = json.load(file)
        return [
            FixtureRawJob(
                source_platform=self.source_platform,
                external_id=f"{self.source_platform}-fixture-1",
                source_url=f"https://example.test/{self.source_platform}/fixture-1",
                raw_payload=payload,
            )
        ]

    def map_raw_job(
        self, raw_job: FixtureRawJob | Any, *, scraped_at: datetime
    ) -> SourceMapperResult:
        external_id = raw_job.external_id
        platform = SourcePlatform(raw_job.source_platform)
        return SourceMapperResult(
            job=CanonicalJobSchema(
                source=SourceMetadataSchema(
                    platform=platform,
                    external_job_id=external_id,
                    source_url=raw_job.source_url,
                    scraped_at=scraped_at,
                ),
                title=f"{platform.value.title()} Backend Engineer",
                company=CompanySchema(name=f"{platform.value.title()} Company"),
                location=LocationSchema(display="Jakarta", city="Jakarta", country="Indonesia"),
                description="Build Python APIs and data pipelines.",
                requirements="Python and SQL experience.",
                skills=["Python", "SQL"],
                last_seen_at=datetime(2026, 5, 2, 10, 0, tzinfo=UTC),
                status=CanonicalJobStatus.ACTIVE,
            ),
            field_provenance={"title": "fixture"},
        )


class RecordingBackendClient:
    def __init__(self) -> None:
        self.payloads: list[list[str]] = []

    async def sync_jobs(self, jobs: list[dict[str, Any]]) -> BackendSyncResult:
        self.payloads.append(
            [
                job.get("jobListing", {}).get("externalJobId", "")
                for job in jobs
                if isinstance(job, dict)
            ]
        )
        return BackendSyncResult(
            status_code=202,
            response_summary={"statusCode": 202, "statusClass": "2xx"},
        )


class RecordingHandoffClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def send_candidates(self, payload: dict[str, Any]) -> HandoffSuccess:
        self.payloads.append(payload)
        return HandoffSuccess({"statusCode": 202, "statusClass": "2xx"})


def fake_enrichment_output() -> EnrichmentOutput:
    return EnrichmentOutput(
        skills=[EnrichedSkill(name="Python", confidence=0.9)],
        requirements=[
            EnrichedRequirement(
                type=RequirementType.SKILL,
                value="SQL experience",
                confidence=0.8,
            )
        ],
        confidence=0.85,
    )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
