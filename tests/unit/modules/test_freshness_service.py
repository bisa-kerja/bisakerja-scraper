from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tests.unit.modules.test_persistence_repositories import canonical_job, raw_input

from modules.freshness import FreshnessPolicy, FreshnessService
from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import Base, JobPersistenceRepository, NormalizedJob


def test_freshness_sweep_marks_missing_jobs_stale_and_expired() -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        active = repository.write_job(raw_input("run-1", "active"), canonical_job("active"))
        stale = repository.write_job(raw_input("run-1", "stale"), canonical_job("stale"))
        expired = repository.write_job(raw_input("run-1", "expired"), canonical_job("expired"))
        stale.normalized_job.last_seen_at = now - timedelta(hours=80)
        expired.normalized_job.last_seen_at = now - timedelta(hours=400)

        summary = FreshnessService(
            session,
            policy=FreshnessPolicy(stale_after_hours=72, expired_after_hours=336),
        ).sweep_source(
            source_platform="dealls",
            seen_external_ids={active.normalized_job.external_id},
            source_run_successful=True,
            now=now,
        )

        jobs = {job.external_id: job.status for job in session.scalars(select(NormalizedJob))}
        assert jobs == {
            "active": CanonicalJobStatus.ACTIVE.value,
            "stale": CanonicalJobStatus.STALE.value,
            "expired": CanonicalJobStatus.EXPIRED.value,
        }
        assert summary.stale_count == 1
        assert summary.expired_count == 1


def test_freshness_sweep_reactivates_seen_job_and_is_idempotent() -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        result = repository.write_job(raw_input("run-1", "job-1"), canonical_job("job-1"))
        result.normalized_job.status = CanonicalJobStatus.STALE.value
        service = FreshnessService(
            session,
            policy=FreshnessPolicy(stale_after_hours=72, expired_after_hours=336),
        )

        first = service.sweep_source(
            source_platform="dealls",
            seen_external_ids={"job-1"},
            source_run_successful=True,
            now=now,
        )
        second = service.sweep_source(
            source_platform="dealls",
            seen_external_ids={"job-1"},
            source_run_successful=True,
            now=now,
        )

        job = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert job is not None
        assert job.status == CanonicalJobStatus.ACTIVE.value
        assert first.reactivated_count == 1
        assert second.reactivated_count == 0


def test_freshness_sweep_does_not_expire_after_failed_source_run() -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        result = repository.write_job(raw_input("run-1", "job-1"), canonical_job("job-1"))
        result.normalized_job.last_seen_at = now - timedelta(hours=400)

        FreshnessService(
            session,
            policy=FreshnessPolicy(stale_after_hours=72, expired_after_hours=336),
        ).sweep_source(
            source_platform="dealls",
            seen_external_ids=set(),
            source_run_successful=False,
            now=now,
        )

        job = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert job is not None
        assert job.status == CanonicalJobStatus.UNKNOWN.value


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
