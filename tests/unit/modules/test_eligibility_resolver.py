from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from modules.eligibility import EligibilityDecisionReason, EligibilityResolver
from modules.persistence import (
    Base,
    NormalizationEligibilityDecision,
    NormalizedJob,
    RawJob,
    ScrapeRun,
    SyncEvent,
)


def test_eligibility_marks_new_identity_as_normalization_eligible() -> None:
    with session_scope() as session:
        raw = seed_raw_job(session, run_id="run-scrape", external_id="job-1")
        resolver = EligibilityResolver(session)

        decisions = resolver.resolve_for_raw_jobs(
            scrape_run_id="run-scrape",
            raw_jobs=[raw],
            backend_existing={},
        )

        assert len(decisions) == 1
        assert decisions[0].decision == EligibilityDecisionReason.NORMALIZATION_ELIGIBLE.value


def test_eligibility_marks_existing_backend_identity() -> None:
    with session_scope() as session:
        raw = seed_raw_job(session, run_id="run-scrape", external_id="job-1")
        resolver = EligibilityResolver(session)

        decisions = resolver.resolve_for_raw_jobs(
            scrape_run_id="run-scrape",
            raw_jobs=[raw],
            backend_existing={
                ("dealls", "job-1"): {"jobId": "backend-job-1"},
            },
        )

        assert decisions[0].decision == EligibilityDecisionReason.EXISTING_BACKEND.value
        assert decisions[0].backend_job_id == "backend-job-1"


def test_eligibility_marks_existing_normalized_unsynced() -> None:
    with session_scope() as session:
        raw = seed_raw_job(session, run_id="run-scrape", external_id="job-1")
        normalized = NormalizedJob(
            raw_job_id=raw.id,
            source_platform="dealls",
            external_id="job-1",
            title="Backend Engineer",
            company_name="Example",
            source_url="https://example.test/job-1",
            status="ACTIVE",
            normalized_payload={"title": "Backend Engineer"},
            last_seen_at=datetime.now(UTC),
        )
        session.add(normalized)
        session.flush()
        session.add(
            SyncEvent(
                scrape_run_id="run-sync",
                normalized_job_id=normalized.id,
                source_platform="dealls",
                external_id="job-1",
                status="pending",
                target="backend",
                payload_hash="payload-hash-1",
                attempt_count=0,
                attempted_at=datetime.now(UTC),
            )
        )
        session.commit()

        resolver = EligibilityResolver(session)
        decisions = resolver.resolve_for_raw_jobs(
            scrape_run_id="run-scrape",
            raw_jobs=[raw],
            backend_existing={},
        )

        assert decisions[0].decision == EligibilityDecisionReason.EXISTING_NORMALIZED_UNSYNCED.value
        assert decisions[0].normalized_job_id == normalized.id
        assert decisions[0].normalized_sync_state == "pending"


def test_eligibility_marks_missing_identity() -> None:
    with session_scope() as session:
        run = ScrapeRun(
            id="run-scrape",
            source_platform="dealls",
            stage="scrape",
            status="completed",
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        raw = RawJob(
            id="raw-missing",
            scrape_run_id=run.id,
            source_platform="dealls",
            external_id="",
            source_url="https://example.test/missing",
            raw_payload={"id": ""},
            payload_hash="hash-missing",
            scraped_at=datetime.now(UTC),
        )
        session.add(raw)
        session.commit()

        resolver = EligibilityResolver(session)
        decisions = resolver.resolve_for_raw_jobs(
            scrape_run_id="run-scrape",
            raw_jobs=[raw],
            backend_existing={},
        )

        assert decisions[0].decision == EligibilityDecisionReason.MISSING_IDENTITY.value
        persisted = session.scalar(
            select(NormalizationEligibilityDecision).where(
                NormalizationEligibilityDecision.raw_job_id == raw.id
            )
        )
        assert persisted is not None


def seed_raw_job(session: Session, *, run_id: str, external_id: str) -> RawJob:
    run = ScrapeRun(
        id=run_id,
        source_platform="dealls",
        stage="scrape",
        status="completed",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    raw = RawJob(
        id=f"raw-{external_id}",
        scrape_run_id=run.id,
        source_platform="dealls",
        external_id=external_id,
        source_url=f"https://example.test/{external_id}",
        raw_payload={"id": external_id},
        payload_hash=f"hash-{external_id}",
        scraped_at=datetime.now(UTC),
    )
    session.add(raw)
    session.commit()
    return raw


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
