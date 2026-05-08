from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tests.unit.modules.test_persistence_repositories import canonical_job, raw_input

from integrations.backend import BackendSyncClientError, BackendSyncResult, BackendSyncServerError
from integrations.backend.payloads import build_backend_job_payload
from modules.persistence import (
    Base,
    JobPersistenceRepository,
    NormalizedJob,
    SyncEvent,
    stable_payload_hash,
)
from modules.sync import (
    BackendSyncWorker,
    SyncEventRepository,
    SyncEventStatus,
    SyncFailure,
    SyncSuccess,
)


@pytest.mark.asyncio
async def test_sync_worker_records_4xx_as_non_retryable_failure() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job("job-1"),
        )
        result.normalized_job.status = "active"
        worker = BackendSyncWorker(
            session=session,
            client=RejectingClient(),
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        event = session.scalar(select(SyncEvent).where(SyncEvent.external_id == "job-1"))
        assert sync_result.failed == 1
        assert event is not None
        assert event.status == SyncEventStatus.DEAD_LETTER.value
        assert event.error_category == "backend_rejected_payload"
        assert event.attempt_count == 1


@pytest.mark.asyncio
async def test_sync_worker_records_404_as_retryable_endpoint_failure() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job("job-1"),
        )
        result.normalized_job.status = "active"
        worker = BackendSyncWorker(
            session=session,
            client=MissingEndpointClient(),
            events=SyncEventRepository(session),
            max_attempts=3,
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        event = session.scalar(select(SyncEvent).where(SyncEvent.external_id == "job-1"))
        assert sync_result.failed == 1
        assert event is not None
        assert event.status == SyncEventStatus.FAILED.value
        assert event.error_category == "backend_endpoint_not_found"
        assert event.attempt_count == 1
        assert event.response_summary == {
            "statusCode": 404,
            "statusClass": "4xx",
            "endpointPath": "/api/v1/internal/scraper/jobs",
        }


@pytest.mark.asyncio
async def test_sync_worker_only_sends_eligible_jobs() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        eligible = repository.write_job(raw_input("run-1", "eligible"), canonical_job("eligible"))
        skipped = repository.write_job(raw_input("run-1", "skipped"), canonical_job("skipped"))
        eligible.normalized_job.status = "active"
        skipped.normalized_job.status = "unknown"
        client = RecordingClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        assert sync_result.sent == 1
        assert client.external_ids == ["eligible"]


@pytest.mark.asyncio
async def test_sync_worker_filters_candidates_by_selected_sources() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        dealls = repository.write_job(raw_input("run-1", "dealls-job"), canonical_job("dealls-job"))
        glints = repository.write_job(raw_input("run-1", "glints-job"), canonical_job("glints-job"))
        for result in (dealls, glints):
            result.normalized_job.status = "active"
        glints.normalized_job.source_platform = "glints"

        client = RecordingClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(
            scrape_run_id="run-1",
            limit=10,
            source_platforms=("dealls",),
        )

        assert sync_result.sent == 1
        assert client.external_ids == ["dealls-job"]


@pytest.mark.asyncio
async def test_sync_worker_filters_candidates_by_scrape_run_id() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        run_one = repository.write_job(raw_input("run-1", "job-run-1"), canonical_job("job-run-1"))
        run_two = repository.write_job(raw_input("run-2", "job-run-2"), canonical_job("job-run-2"))
        run_one.normalized_job.status = "active"
        run_two.normalized_job.status = "active"

        client = RecordingClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(
            scrape_run_id="run-2",
            limit=10,
        )

        assert sync_result.sent == 1
        assert client.external_ids == ["job-run-2"]


@pytest.mark.asyncio
async def test_sync_worker_maps_stage_run_id_to_scrape_scope() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        scoped = repository.write_job(
            raw_input("run-42-scrape", "job-run-42"),
            canonical_job("job-run-42"),
        )
        scoped.normalized_job.status = "active"

        client = RecordingClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(
            scrape_run_id="run-42-sync",
            limit=10,
        )

        assert sync_result.sent == 1
        assert client.external_ids == ["job-run-42"]


@pytest.mark.asyncio
async def test_sync_worker_isolates_failed_chunk_and_continues() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        for external_id in ("job-1", "job-2", "job-3"):
            result = repository.write_job(
                raw_input("run-1", external_id),
                canonical_job(external_id),
            )
            result.normalized_job.status = "active"
        client = FailsFirstChunkClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
            max_attempts=3,
        )

        sync_result = await worker.sync_eligible_jobs(
            scrape_run_id="run-1",
            limit=10,
            batch_size=2,
        )

        events = list(session.scalars(select(SyncEvent).order_by(SyncEvent.external_id)).all())
        assert sync_result.chunks_attempted == 4
        assert sync_result.chunks_failed == 1
        assert sync_result.sent == 3
        assert sync_result.failed == 0
        assert sync_result.adaptive_batch_reductions == 1
        assert sync_result.status_class_counts["5xx"] == 1
        assert client.calls == [["job-3", "job-2"], ["job-3"], ["job-2"], ["job-1"]]
        assert [event.status for event in events] == [
            SyncEventStatus.SENT.value,
            SyncEventStatus.SENT.value,
            SyncEventStatus.SENT.value,
        ]
        assert all(event.metadata_json["chunkPayloadHash"] for event in events)


@pytest.mark.asyncio
async def test_sync_worker_sends_large_candidate_set_in_backend_safe_chunks() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        for index in range(205):
            external_id = f"job-{index:03d}"
            result = repository.write_job(
                raw_input("run-1", external_id),
                canonical_job(external_id),
            )
            result.normalized_job.status = "active"
        client = RecordingBatchClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(
            scrape_run_id="run-1",
            limit=205,
            batch_size=100,
        )

        assert sync_result.attempted == 205
        assert sync_result.sent == 205
        assert sync_result.failed == 0
        assert sync_result.chunks_attempted == 3
        assert client.batch_sizes == [100, 100, 5]
        assert len(client.external_ids) == 205


@pytest.mark.asyncio
async def test_sync_worker_resume_skips_sent_and_dead_letter_events() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        sent = repository.write_job(raw_input("run-1", "sent"), canonical_job("sent"))
        retryable = repository.write_job(raw_input("run-1", "retry"), canonical_job("retry"))
        dead = repository.write_job(raw_input("run-1", "dead"), canonical_job("dead"))
        for result in (sent, retryable, dead):
            result.normalized_job.status = "active"
        events = SyncEventRepository(session)
        sent_event = events.prepare_event(
            sent.normalized_job,
            scrape_run_id="run-1",
            payload_hash=backend_payload_hash(sent.normalized_job),
        )
        events.record_success(sent_event, SyncSuccess({"statusCode": 202}))
        retry_event = events.prepare_event(
            retryable.normalized_job,
            scrape_run_id="run-1",
            payload_hash=backend_payload_hash(retryable.normalized_job),
        )
        events.record_failure(
            retry_event,
            SyncFailure(category="backend_5xx", message="retry"),
            max_attempts=3,
        )
        dead_event = events.prepare_event(
            dead.normalized_job,
            scrape_run_id="run-1",
            payload_hash=backend_payload_hash(dead.normalized_job),
        )
        events.record_failure(
            dead_event,
            SyncFailure(category="backend_5xx", message="dead"),
            max_attempts=1,
        )
        client = RecordingClient()
        worker = BackendSyncWorker(session=session, client=client, events=events)

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        assert sync_result.attempted == 1
        assert sync_result.sent == 1
        assert client.external_ids == ["retry"]
        assert (
            retry_event.id
            == session.scalar(select(SyncEvent).where(SyncEvent.external_id == "retry")).id
        )


@pytest.mark.asyncio
async def test_sync_worker_retries_after_backend_payload_serializer_changes() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        result = repository.write_job(raw_input("run-1", "job-1"), canonical_job("job-1"))
        result.normalized_job.status = "active"
        events = SyncEventRepository(session)
        old_event = events.prepare_event(result.normalized_job, scrape_run_id="run-1")
        events.record_failure(
            old_event,
            SyncFailure(category="backend_rejected_payload", message="old serializer"),
            max_attempts=1,
        )
        client = RecordingClient()
        worker = BackendSyncWorker(session=session, client=client, events=events)

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        sync_events = list(session.scalars(select(SyncEvent)).all())
        assert sync_result.sent == 1
        assert len(sync_events) == 2
        assert sorted(event.status for event in sync_events) == [
            SyncEventStatus.DEAD_LETTER.value,
            SyncEventStatus.SENT.value,
        ]
        assert client.external_ids == ["job-1"]


@pytest.mark.asyncio
async def test_sync_worker_sets_zero_sent_reason_for_no_candidates() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job("job-1"),
        )
        result.normalized_job.status = "unknown"
        worker = BackendSyncWorker(
            session=session,
            client=RecordingClient(),
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        assert sync_result.attempted == 0
        assert sync_result.sent == 0
        assert sync_result.zero_sent_reason == "no eligible jobs for sync"


@pytest.mark.asyncio
async def test_sync_worker_sets_zero_sent_reason_for_all_failures() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job("job-1"),
        )
        result.normalized_job.status = "active"
        worker = BackendSyncWorker(
            session=session,
            client=RejectingClient(),
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        assert sync_result.attempted == 1
        assert sync_result.sent == 0
        assert sync_result.failed == 1
        assert sync_result.zero_sent_reason == "all candidate jobs failed sync attempts"


class RejectingClient:
    async def sync_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        raise BackendSyncClientError("validation failed", status_code=400)


class MissingEndpointClient:
    async def sync_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        raise BackendSyncClientError(
            "backend sync rejected payload",
            status_code=404,
            response_summary={
                "statusCode": 404,
                "statusClass": "4xx",
                "endpointPath": "/api/v1/internal/scraper/jobs",
            },
        )


class RecordingClient:
    def __init__(self) -> None:
        self.external_ids: list[str] = []

    async def sync_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        self.external_ids.extend(item["jobListing"]["externalJobId"] for item in jobs)
        return BackendSyncResult(
            status_code=202,
            response_summary={"statusCode": 202, "statusClass": "2xx"},
        )


class RecordingBatchClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.batch_sizes: list[int] = []

    async def sync_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        self.batch_sizes.append(len(jobs))
        return await super().sync_jobs(jobs)


class FailsFirstChunkClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def sync_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        external_ids = [item["jobListing"]["externalJobId"] for item in jobs]
        self.calls.append(external_ids)
        if len(self.calls) == 1:
            raise BackendSyncServerError("backend unavailable", status_code=503)
        return BackendSyncResult(
            status_code=202,
            response_summary={"statusCode": 202, "statusClass": "2xx"},
        )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def backend_payload_hash(job: NormalizedJob) -> str:
    payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
    return stable_payload_hash(payload)
