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
from modules.jobs import AINormalizationBatchItemResult, AINormalizationBatchPromptInput
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CanonicalJobStatus,
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
    RawJob,
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


@pytest.mark.asyncio
async def test_normalize_stage_uses_ai_normalization_when_client_available() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        repository.upsert_raw_job(raw_input("run-scrape", "ai-1"))
        session.commit()
        source = FakeSource("dealls", [])
        client = FakeAINormalizationClient(title="AI Normalized Title")
        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=repository,
            run_tracker=RunStateTracker(session),
            correlation_id_factory=lambda: "corr-1",
            ai_normalization_client=client,
        )

        result = await orchestrator.run_normalize(run_id="run-normalize")

        normalized = session.scalar(
            select(NormalizedJob).where(NormalizedJob.external_id == "ai-1")
        )
        assert result.status == "completed"
        assert normalized is not None
        assert normalized.title == "AI Normalized Title"
        assert client.calls == 1


@pytest.mark.asyncio
async def test_normalize_stage_falls_back_to_mapper_on_ai_failure_when_fail_open() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        repository.upsert_raw_job(raw_input("run-scrape", "ai-fallback-1"))[0]
        session.commit()
        source = FakeSource("dealls", [])
        client = FailingAINormalizationClient()
        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=repository,
            run_tracker=RunStateTracker(session),
            correlation_id_factory=lambda: "corr-1",
            ai_normalization_client=client,
        )

        result = await orchestrator.run_normalize(run_id="run-normalize")

        normalized = session.scalar(
            select(NormalizedJob).where(NormalizedJob.external_id == "ai-fallback-1")
        )
        assert result.status == "completed"
        assert normalized is not None
        assert normalized.title == "Backend Engineer"


@pytest.mark.asyncio
async def test_normalize_stage_quarantines_on_ai_failure_when_fail_closed() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        raw = repository.upsert_raw_job(raw_input("run-scrape", "ai-fail-closed-1"))[0]
        session.commit()
        source = FakeSource("dealls", [])
        client = FailingAINormalizationClient()
        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=repository,
            run_tracker=RunStateTracker(session),
            quarantine=QuarantineRepository(session),
            config=PipelineConfig(ai_normalization_fail_open=False),
            correlation_id_factory=lambda: "corr-1",
            ai_normalization_client=client,
        )

        result = await orchestrator.run_normalize(run_id="run-normalize")

        quarantine = session.scalar(
            select(NormalizationQuarantine).where(NormalizationQuarantine.raw_job_id == raw.id)
        )
        assert result.status == "partial"
        assert result.counts.skipped == 1
        assert quarantine is not None
        assert quarantine.error_category == "NORMALIZE_ERROR"
        assert quarantine.retryable is True
        assert session.scalars(select(NormalizedJob)).all() == []


@pytest.mark.asyncio
async def test_normalize_stage_uses_batch_ai_and_partial_item_failure() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        raw_a = repository.upsert_raw_job(raw_input("run-scrape", "ai-batch-1"))[0]
        repository.upsert_raw_job(raw_input("run-scrape", "ai-batch-2"))[0]
        raw_c = repository.upsert_raw_job(raw_input("run-scrape", "ai-batch-3"))[0]
        session.commit()
        source = FakeSource("dealls", [])
        client = FakeBatchAINormalizationClient(failed_external_ids={"ai-batch-3"})
        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=repository,
            run_tracker=RunStateTracker(session),
            quarantine=QuarantineRepository(session),
            config=PipelineConfig(
                ai_normalization_fail_open=False,
                ai_normalization_batch_size=2,
            ),
            correlation_id_factory=lambda: "corr-1",
            ai_normalization_client=client,
        )

        result = await orchestrator.run_normalize(run_id="run-normalize")

        quarantine = session.scalar(
            select(NormalizationQuarantine).where(NormalizationQuarantine.raw_job_id == raw_c.id)
        )
        normalized_rows = session.scalars(select(NormalizedJob)).all()
        assert result.status == "partial"
        assert result.counts.normalized == 2
        assert result.counts.skipped == 1
        assert client.batch_calls == 2
        assert len(normalized_rows) == 2
        assert quarantine is not None
        assert quarantine.raw_job_id == raw_c.id
        assert raw_a.id != raw_c.id


@pytest.mark.asyncio
async def test_normalize_stage_batch_delay_is_applied_between_batches(monkeypatch) -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        repository.upsert_raw_job(raw_input("run-scrape", "ai-delay-1"))
        repository.upsert_raw_job(raw_input("run-scrape", "ai-delay-2"))
        repository.upsert_raw_job(raw_input("run-scrape", "ai-delay-3"))
        session.commit()
        source = FakeSource("dealls", [])
        client = FakeBatchAINormalizationClient(failed_external_ids=set())
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr("jobs.pipeline.asyncio.sleep", fake_sleep)
        orchestrator = PipelineOrchestrator(
            sources=[source],
            persistence=repository,
            run_tracker=RunStateTracker(session),
            config=PipelineConfig(
                ai_normalization_batch_size=2,
                ai_normalization_inter_batch_delay_ms=500,
            ),
            correlation_id_factory=lambda: "corr-1",
            ai_normalization_client=client,
        )

        result = await orchestrator.run_normalize(run_id="run-normalize")

        assert result.status == "completed"
        assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_scrape_stage_tracks_keyword_metadata_without_changing_identity() -> None:
    with session_scope() as session:
        orchestrator = PipelineOrchestrator(
            sources=[
                KeywordSource("dealls", "developer", ["job-1"]),
                KeywordSource("dealls", "intern", ["job-1"]),
            ],
            persistence=JobPersistenceRepository(session),
            run_tracker=RunStateTracker(session),
            correlation_id_factory=lambda: "corr-1",
        )

        result = await orchestrator.run_scrape(run_id="run-scrape")

        raw_jobs = session.scalars(select(RawJob)).all()
        assert result.status == "completed"
        assert result.counts.fetched == 2
        assert len(raw_jobs) == 1
        assert raw_jobs[0].source_platform == "dealls"
        assert raw_jobs[0].external_id == "job-1"
        assert raw_jobs[0].metadata_json["keyword"] in {"developer", "intern"}
        assert raw_jobs[0].metadata_json["recencyMode"] == "latest"
        assert raw_jobs[0].metadata_json["requestedLimit"] == 50
        assert {source.keyword for source in result.source_results} == {"developer", "intern"}


@dataclass
class RawJobStub:
    source_platform: str
    external_id: str
    source_url: str
    raw_payload: dict[str, Any]
    keyword: str | None = None
    requested_limit: int | None = None
    recency_mode: str | None = None
    recency_days: int | None = None
    source_timestamp: datetime | None = None


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


class KeywordSource(FakeSource):
    def __init__(self, source_platform: str, keyword: str, external_ids: list[str]) -> None:
        super().__init__(source_platform, external_ids)
        self.keyword = keyword
        self.requested_limit = 50
        self.recency_mode = "latest"
        self.recency_days = 7

    async def fetch_raw_jobs(self) -> list[RawJobStub]:
        self.fetch_count += 1
        now = datetime.now(UTC)
        return [
            RawJobStub(
                source_platform=self.source_platform,
                external_id=external_id,
                source_url=f"https://example.test/{external_id}",
                raw_payload={"id": external_id},
                keyword=self.keyword,
                requested_limit=self.requested_limit,
                recency_mode=self.recency_mode,
                recency_days=self.recency_days,
                source_timestamp=now,
            )
            for external_id in self.external_ids
        ]


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


class FakeAINormalizationClient:
    def __init__(self, *, title: str) -> None:
        self.title = title
        self.calls = 0

    async def normalize_job(self, prompt_input):  # noqa: ANN001, ANN201
        self.calls += 1
        return CanonicalJobSchema(
            source=SourceMetadataSchema(
                platform=SourcePlatform.DEALLS,
                external_job_id="ai-1",
                source_url="https://dealls.com/jobs/ai-1",
                external_apply_url="https://dealls.com/jobs/ai-1",
                scraped_at=datetime.now(UTC),
            ),
            title=self.title,
            company=CompanySchema(name="Bisakerja AI"),
            location=LocationSchema(display="Jakarta"),
            last_seen_at=datetime.now(UTC),
            status=CanonicalJobStatus.ACTIVE,
        )


class FailingAINormalizationClient:
    async def normalize_job(self, prompt_input):  # noqa: ANN001, ANN201
        raise NormalizeError(
            "provider timeout",
            source_platform="dealls",
            external_id="ai-error",
            retryable=True,
            details={"source_field_path": "raw_payload"},
        )


class FakeBatchAINormalizationClient:
    def __init__(self, *, failed_external_ids: set[str]) -> None:
        self.failed_external_ids = failed_external_ids
        self.batch_calls = 0

    async def normalize_jobs(
        self,
        prompt_input: AINormalizationBatchPromptInput,
    ) -> list[AINormalizationBatchItemResult]:
        self.batch_calls += 1
        results: list[AINormalizationBatchItemResult] = []
        for item in prompt_input.items:
            external_id = str(item.raw_payload_subset.get("externalId"))
            if external_id in self.failed_external_ids:
                results.append(
                    AINormalizationBatchItemResult(
                        item_id=item.item_id,
                        normalized_job=None,
                        error_code="INSUFFICIENT_EVIDENCE",
                        error_message="detail payload missing",
                    )
                )
                continue
            raw_url = item.raw_payload_subset.get("sourceUrl")
            source_url = (
                raw_url if isinstance(raw_url, str) else f"https://dealls.com/{external_id}"
            )
            results.append(
                AINormalizationBatchItemResult(
                    item_id=item.item_id,
                    normalized_job=CanonicalJobSchema(
                        source=SourceMetadataSchema(
                            platform=SourcePlatform.DEALLS,
                            external_job_id=external_id,
                            source_url=source_url,
                            external_apply_url=source_url,
                            scraped_at=datetime.now(UTC),
                        ),
                        title=f"AI Batch {external_id}",
                        company=CompanySchema(name="Bisakerja AI"),
                        location=LocationSchema(display="Jakarta"),
                        last_seen_at=datetime.now(UTC),
                        status=CanonicalJobStatus.ACTIVE,
                    ),
                )
            )
        return results


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
