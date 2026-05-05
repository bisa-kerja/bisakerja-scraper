from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from modules.enrichment.schemas import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentJobInput,
    EnrichmentOutput,
    RequirementType,
)
from modules.enrichment.service import EnrichmentService, EnrichmentServiceConfig
from modules.persistence import AIRequestLog, Base, JobSkillStaging, NormalizedJob


class RetryableError(RuntimeError):
    code = "OPENAI_RATE_LIMIT"
    retryable = True


class FakeClient:
    model = "gpt-test"
    max_retries = 0

    def __init__(self, outputs: list[EnrichmentOutput | Exception]) -> None:
        self.outputs = outputs
        self.calls: list[EnrichmentJobInput] = []

    async def enrich_job(self, job: EnrichmentJobInput) -> EnrichmentOutput:
        self.calls.append(job)
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_enrichment_batch_uses_default_ten_limit_and_writes_staging() -> None:
    with session_scope() as session:
        for index in range(12):
            session.add(normalized_job(f"job-{index}", description="Build Python API"))
        session.flush()
        output = EnrichmentOutput(
            skills=[EnrichedSkill(name="Python", confidence=0.9)],
            requirements=[
                EnrichedRequirement(
                    type=RequirementType.SKILL,
                    value="Python",
                    confidence=0.9,
                )
            ],
            confidence=0.9,
        )
        service = EnrichmentService(
            session=session,
            client=FakeClient([output] * 10),
            config=EnrichmentServiceConfig(model="gpt-test"),
        )

        result = await service.enrich_pending_batch(scrape_run_id=None)

        assert result.processed == 10
        assert result.succeeded == 10
        assert len(session.scalars(select(JobSkillStaging)).all()) == 10


@pytest.mark.asyncio
async def test_enrichment_partial_failure_continues_batch() -> None:
    with session_scope() as session:
        session.add_all(
            [
                normalized_job("job-1", description="Build Python API"),
                normalized_job("job-2", description="Build Python API"),
            ]
        )
        session.flush()
        output = EnrichmentOutput(
            skills=[EnrichedSkill(name="Python", confidence=0.9)],
            requirements=[],
            confidence=0.9,
        )
        service = EnrichmentService(
            session=session,
            client=FakeClient([RuntimeError("bad response"), output]),
            config=EnrichmentServiceConfig(model="gpt-test", batch_size=2),
        )

        result = await service.enrich_pending_batch(scrape_run_id=None)

        assert result.processed == 2
        assert result.succeeded == 1
        assert result.failed == 1
        assert len(session.scalars(select(AIRequestLog)).all()) == 2
        assert len(session.scalars(select(JobSkillStaging)).all()) == 1


@pytest.mark.asyncio
async def test_enrichment_retries_retryable_error() -> None:
    with session_scope() as session:
        session.add(normalized_job("job-1", description="Build Python API"))
        session.flush()
        output = EnrichmentOutput(
            skills=[EnrichedSkill(name="Python", confidence=0.9)],
            requirements=[],
            confidence=0.9,
        )
        client = FakeClient([RetryableError("rate limit"), output])
        service = EnrichmentService(
            session=session,
            client=client,
            config=EnrichmentServiceConfig(model="gpt-test", batch_size=1, max_attempts=2),
        )

        result = await service.enrich_pending_batch(scrape_run_id=None)

        assert result.succeeded == 1
        assert len(client.calls) == 2
        log = session.scalar(select(AIRequestLog))
        assert log is not None
        assert log.retry_count == 1


@pytest.mark.asyncio
async def test_enrichment_rerun_is_idempotent() -> None:
    with session_scope() as session:
        session.add(normalized_job("job-1", description="Build Python API"))
        session.flush()
        output = EnrichmentOutput(
            skills=[EnrichedSkill(name="Python", confidence=0.9)],
            requirements=[],
            confidence=0.9,
        )
        service = EnrichmentService(
            session=session,
            client=FakeClient([output, output]),
            config=EnrichmentServiceConfig(model="gpt-test", batch_size=1),
        )

        first = await service.enrich_pending_batch(scrape_run_id=None)
        second = await service.enrich_pending_batch(scrape_run_id=None)

        assert first.succeeded == 1
        assert second.processed == 0
        assert len(session.scalars(select(JobSkillStaging)).all()) == 1


@pytest.mark.asyncio
async def test_enrichment_invalid_input_is_failed_per_item_without_crashing_batch() -> None:
    with session_scope() as session:
        session.add_all(
            [
                normalized_job("bad-job", description="raw_payload token=abc123"),
                normalized_job("good-job", description="Build Python API"),
            ]
        )
        session.flush()
        output = EnrichmentOutput(
            skills=[EnrichedSkill(name="Python", confidence=0.9)],
            requirements=[],
            confidence=0.9,
        )
        client = FakeClient([output])
        service = EnrichmentService(
            session=session,
            client=client,
            config=EnrichmentServiceConfig(model="gpt-test", batch_size=2),
        )

        result = await service.enrich_pending_batch(scrape_run_id="run-enrich")

        assert result.processed == 2
        assert result.succeeded == 1
        assert result.failed == 1
        assert len(client.calls) == 1
        assert len(session.scalars(select(AIRequestLog)).all()) == 2


def session_scope() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def normalized_job(job_id: str, *, description: str) -> NormalizedJob:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    return NormalizedJob(
        id=job_id,
        source_platform="dealls",
        external_id=f"external-{job_id}",
        title="Backend Engineer",
        company_name="Bisakerja",
        source_url=f"https://example.com/{job_id}",
        status="active",
        normalized_payload={
            "company": {"name": "Bisakerja"},
            "description": description,
            "requirements": "Python",
            "source": {"platform": "dealls"},
        },
        last_seen_at=now,
    )
