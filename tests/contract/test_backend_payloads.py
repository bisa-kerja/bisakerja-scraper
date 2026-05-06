from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from integrations.backend.payloads import (
    BackendPayloadValidationError,
    build_backend_job_payload,
    build_backend_jobs_body,
)
from modules.enrichment.repositories import EnrichmentSource, EnrichmentStagingRepository
from modules.enrichment.schemas import RequirementType
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CanonicalJobStatus,
    CompanySchema,
    EmploymentType,
    LocationSchema,
    SalarySchema,
    SourceMetadataSchema,
    SourcePlatform,
    WorkType,
)
from modules.persistence import Base, JobPersistenceRepository, NormalizedJob
from tests.unit.modules.test_persistence_repositories import raw_input


def test_backend_payload_maps_company_listing_skills_and_requirements() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        result = repository.write_job(raw_input("run-1", "job-1"), canonical_job())
        staging = EnrichmentStagingRepository(session)
        staging.upsert_skill(
            result.normalized_job,
            value="Python",
            confidence=0.9,
            ai_request_log_id=None,
            source=EnrichmentSource.AI,
        )
        staging.upsert_requirement(
            result.normalized_job,
            requirement_type=RequirementType.EXPERIENCE,
            value="2 years experience",
            confidence=0.8,
            ai_request_log_id=None,
            source=EnrichmentSource.AI,
        )
        session.commit()

        job = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert job is not None
        payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)

        assert payload["sourcePlatform"] == {"slug": "dealls", "name": "Dealls"}
        assert payload["jobListing"]["externalJobId"] == "job-1"
        assert payload["company"]["name"] == "Bisakerja"
        assert payload["jobListing"]["employmentType"] == "FULL_TIME"
        assert payload["jobListing"]["workType"] == "REMOTE"
        assert payload["jobListing"]["status"] == "ACTIVE"
        assert payload["jobListing"]["salaryCurrency"] == "IDR"
        assert "salary_currency" not in payload["jobListing"]
        assert payload["skills"] == [{"name": "Python", "confidence": 0.9, "source": "ai"}]
        assert payload["requirements"] == [
            {
                "type": "EXPERIENCE",
                "value": "2 years experience",
                "priority": None,
                "confidence": 0.8,
                "source": "ai",
            }
        ]


def test_backend_jobs_body_uses_documented_batch_shape() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job(),
        )

        body = build_backend_jobs_body([result.normalized_job])

        assert set(body) == {"jobs"}
        assert body["jobs"][0]["jobListing"]["externalJobId"] == "job-1"


def test_backend_jobs_body_rejects_batches_larger_than_backend_limit() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job(),
        )

        with pytest.raises(BackendPayloadValidationError, match="batch limit"):
            build_backend_jobs_body([result.normalized_job] * 101)


def canonical_job() -> CanonicalJobSchema:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    return CanonicalJobSchema(
        source=SourceMetadataSchema(
            platform=SourcePlatform.DEALLS,
            external_job_id="job-1",
            source_url="https://dealls.com/jobs/job-1",
            external_apply_url="https://dealls.com/apply/job-1",
            scraped_at=now,
        ),
        title="Backend Engineer",
        description="Build APIs",
        company=CompanySchema(name="Bisakerja", source_company_id="company-1"),
        location=LocationSchema(display="Jakarta", city="Jakarta", country="ID", is_remote=True),
        salary=SalarySchema(min_amount=10, max_amount=20, currency="IDR"),
        employment_types=[EmploymentType.FULL_TIME],
        work_type=WorkType.REMOTE,
        last_seen_at=now,
        status=CanonicalJobStatus.ACTIVE,
    )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
