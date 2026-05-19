from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from modules.enrichment.worker import run_enrichment_stage_job
from modules.persistence import Base
from modules.queue import (
    QueueFailure,
    QueueJobInput,
    StageJobRepository,
    StageJobStatus,
    StageJobType,
)
from modules.queue.worker import process_next_stage_job


def test_queue_job_retries_then_dead_letters() -> None:
    with session_scope() as session:
        repository = StageJobRepository(session)
        job = repository.enqueue(
            QueueJobInput(
                job_type=StageJobType.ENRICH_BATCH,
                correlation_id="corr-1",
                payload={"batchSize": 10},
                max_attempts=2,
            )
        )

        claimed = repository.claim_next(job_type=StageJobType.ENRICH_BATCH)
        assert claimed is not None
        repository.fail(claimed, QueueFailure(category="timeout", message="provider timeout"))
        assert job.status == StageJobStatus.FAILED.value
        assert job.attempt_count == 1

        claimed_again = repository.claim_next(job_type=StageJobType.ENRICH_BATCH)
        assert claimed_again is not None
        repository.fail(claimed_again, QueueFailure(category="timeout", message="provider timeout"))

        assert job.status == StageJobStatus.DEAD_LETTER.value
        assert job.attempt_count == 2
        assert job.completed_at is not None
        assert job.correlation_id == "corr-1"


def test_queue_respects_available_at() -> None:
    with session_scope() as session:
        repository = StageJobRepository(session)
        now = datetime(2026, 5, 2, tzinfo=UTC)
        repository.enqueue(
            QueueJobInput(
                job_type=StageJobType.SYNC_BATCH,
                correlation_id="corr-1",
                available_at=now + timedelta(minutes=5),
            )
        )

        assert repository.claim_next(job_type=StageJobType.SYNC_BATCH, now=now) is None
        assert repository.claim_next(
            job_type=StageJobType.SYNC_BATCH,
            now=now + timedelta(minutes=6),
        )


@pytest.mark.asyncio
async def test_worker_entrypoint_completes_successful_job() -> None:
    with session_scope() as session:
        repository = StageJobRepository(session)
        repository.enqueue(
            QueueJobInput(job_type=StageJobType.NOTIFY_HANDOFF, correlation_id="corr-1")
        )
        handled: list[str] = []

        async def handler(job) -> None:  # noqa: ANN001
            handled.append(job.correlation_id)

        job = await process_next_stage_job(
            repository=repository,
            job_type=StageJobType.NOTIFY_HANDOFF,
            handlers={StageJobType.NOTIFY_HANDOFF: handler},
        )

        assert job is not None
        assert job.status == StageJobStatus.COMPLETED.value
        assert handled == ["corr-1"]


@pytest.mark.asyncio
async def test_enrichment_stage_failure_increments_attempt_once() -> None:
    with session_scope() as session:
        repository = StageJobRepository(session)
        repository.enqueue(
            QueueJobInput(
                job_type=StageJobType.ENRICH_BATCH,
                correlation_id="corr-2",
                scrape_run_id="run-1",
            )
        )

        class FailingWorker:
            async def run_batch(self, *, scrape_run_id: str | None = None):  # noqa: ANN201
                raise RuntimeError(f"boom:{scrape_run_id}")

        async def handler(job) -> None:  # noqa: ANN001
            await run_enrichment_stage_job(
                queue=repository,
                worker=FailingWorker(),
                job_id=job.id,
            )

        job = await process_next_stage_job(
            repository=repository,
            job_type=StageJobType.ENRICH_BATCH,
            handlers={StageJobType.ENRICH_BATCH: handler},
        )

        assert job is not None
        assert job.status == StageJobStatus.FAILED.value
        assert job.attempt_count == 1


def session_scope() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
