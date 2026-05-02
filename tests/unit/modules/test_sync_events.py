from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from modules.persistence import Base, NormalizedJob, SyncEvent
from modules.sync import SyncEventRepository, SyncEventStatus, SyncFailure, SyncSuccess


def test_prepare_event_reuses_same_payload_event() -> None:
    with session_scope() as session:
        job = normalized_job("job-1")
        session.add(job)
        session.commit()
        repository = SyncEventRepository(session)

        first = repository.prepare_event(job, scrape_run_id="run-1")
        second = repository.prepare_event(job, scrape_run_id="run-2")

        assert first.id == second.id
        assert second.scrape_run_id == "run-2"
        assert len(session.scalars(select(SyncEvent)).all()) == 1


def test_prepare_event_creates_new_event_when_payload_changes() -> None:
    with session_scope() as session:
        job = normalized_job("job-1")
        session.add(job)
        session.commit()
        repository = SyncEventRepository(session)

        first = repository.prepare_event(job, scrape_run_id="run-1")
        job.normalized_payload = {"title": "Changed"}
        second = repository.prepare_event(job, scrape_run_id="run-1")

        assert first.id != second.id
        assert len(session.scalars(select(SyncEvent)).all()) == 2


def test_record_success_marks_event_sent() -> None:
    with session_scope() as session:
        job = normalized_job("job-1")
        session.add(job)
        session.commit()
        repository = SyncEventRepository(session)
        event = repository.prepare_event(job, scrape_run_id="run-1")

        repository.record_success(event, SyncSuccess(response_summary={"statusCode": 200}))

        assert event.status == SyncEventStatus.SENT.value
        assert event.attempt_count == 1
        assert event.completed_at is not None
        assert event.response_summary == {"statusCode": 200}


def test_record_failure_moves_to_dead_letter_after_limit() -> None:
    with session_scope() as session:
        job = normalized_job("job-1")
        session.add(job)
        session.commit()
        repository = SyncEventRepository(session)
        event = repository.prepare_event(job, scrape_run_id="run-1")

        repository.record_failure(
            event,
            SyncFailure(
                category="backend_5xx",
                message="backend unavailable",
                response_summary={"statusCode": 503},
            ),
            max_attempts=2,
        )
        repository.record_failure(
            event,
            SyncFailure(category="backend_5xx", message="backend unavailable"),
            max_attempts=2,
        )

        assert event.status == SyncEventStatus.DEAD_LETTER.value
        assert event.attempt_count == 2
        assert event.error_message == "backend unavailable"
        assert event.completed_at is not None
        assert len(session.scalars(select(SyncEvent)).all()) == 1


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def normalized_job(job_id: str) -> NormalizedJob:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    return NormalizedJob(
        id=job_id,
        source_platform="dealls",
        external_id=f"external-{job_id}",
        title="Backend Engineer",
        company_name="Bisakerja",
        source_url=f"https://example.com/{job_id}",
        status="active",
        normalized_payload={"title": "Backend Engineer"},
        last_seen_at=now,
    )
