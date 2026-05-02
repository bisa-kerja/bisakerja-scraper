from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from modules.enrichment.repositories import (
    AIRequestLogInput,
    AIRequestLogRepository,
    AIRequestStatus,
    EnrichmentStagingRepository,
)
from modules.enrichment.schemas import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentJobInput,
    EnrichmentOutput,
    RequirementType,
)
from modules.persistence import (
    AIRequestLog,
    Base,
    JobRequirementStaging,
    JobSkillStaging,
    NormalizedJob,
)


def test_ai_request_log_saves_safe_metadata_only() -> None:
    with session_scope() as session:
        job = normalized_job("job-1")
        session.add(job)
        session.flush()
        repository = AIRequestLogRepository(session)

        log = repository.create(
            AIRequestLogInput(
                normalized_job_id=job.id,
                scrape_run_id=None,
                provider="openai-compatible",
                model="gpt-test",
                base_url="https://api.example.test/v1/private/path",
                latency_ms=42,
                status=AIRequestStatus.FAILED,
                retry_count=1,
                request=EnrichmentJobInput(
                    title="Backend Engineer",
                    description="Python API",
                    company="Bisakerja",
                    source="dealls",
                ),
                response_summary={"authorization": "Bearer secret", "statusCode": 503},
                error_message="token leaked",
            )
        )

        assert log.base_url_alias == "api.example.test"
        assert log.request_hash
        assert log.response_summary == {"authorization": "[REDACTED]", "statusCode": 503}
        assert log.error_message == "[REDACTED]"
        assert "Python API" not in log.request_hash


def test_staging_upsert_is_idempotent() -> None:
    with session_scope() as session:
        job = normalized_job("job-1")
        session.add(job)
        session.flush()
        log = AIRequestLog(
            normalized_job_id=job.id,
            provider="openai-compatible",
            model="gpt-test",
            status="success",
            retry_count=0,
            request_hash="hash",
        )
        session.add(log)
        session.flush()
        repository = EnrichmentStagingRepository(session)
        output = EnrichmentOutput(
            skills=[EnrichedSkill(name="Python", confidence=0.9)],
            requirements=[
                EnrichedRequirement(
                    type=RequirementType.SKILL,
                    value="Build Python API",
                    confidence=0.8,
                )
            ],
            confidence=0.85,
        )

        repository.upsert_output(job=job, output=output, ai_request_log_id=log.id)
        repository.upsert_output(job=job, output=output, ai_request_log_id=log.id)

        assert len(session.scalars(select(JobSkillStaging)).all()) == 1
        assert len(session.scalars(select(JobRequirementStaging)).all()) == 1


def session_scope() -> Session:
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
        normalized_payload={
            "title": "Backend Engineer",
            "company": {"name": "Bisakerja"},
            "description": "Build Python API",
            "requirements": "Python",
            "source": {"platform": "dealls"},
        },
        last_seen_at=now,
    )
