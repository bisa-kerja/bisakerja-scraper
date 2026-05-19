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


def test_backend_payload_falls_back_to_normalized_requirement_when_staging_missing() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        repository.write_job(
            raw_input("run-1", "job-req-fallback"),
            canonical_job().model_copy(
                update={"requirements": "Minimal 2 tahun pengalaman backend"}
            ),
        )
        session.commit()

        job = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert job is not None
        payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
        assert payload["requirements"] == [
            {
                "type": "EXPERIENCE",
                "value": "minimum 2 years of experience backend",
                "priority": None,
                "confidence": None,
                "source": "normalized",
            }
        ]


def test_backend_payload_splits_classifies_and_filters_requirement_noise() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "requirements": (
                    "Minimal S1 Teknik Informatika. Minimal 2 tahun pengalaman backend. "
                    "Menguasai Python dan SQL. TUNJANGAN HARI RAYA. "
                    "Mengembangkan API internal."
                )
            }
        )
        repository.write_job(raw_input("run-1", "job-req-semantic"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)

        assert payload["requirements"] == [
            {
                "type": "EDUCATION",
                "value": "minimum S1 Teknik Informatika",
                "priority": None,
                "confidence": None,
                "source": "normalized",
            },
            {
                "type": "EXPERIENCE",
                "value": "minimum 2 years of experience backend",
                "priority": None,
                "confidence": None,
                "source": "normalized",
            },
            {
                "type": "SKILL",
                "value": "proficient in Python and SQL",
                "priority": None,
                "confidence": None,
                "source": "normalized",
            },
            {
                "type": "RESPONSIBILITY",
                "value": "developing API internal",
                "priority": None,
                "confidence": None,
                "source": "normalized",
            },
        ]


def test_backend_payload_strips_emoji_and_decorative_symbols_from_text_fields() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "description": "🌟 Bangun dashboard produk • kolaborasi lintas tim",
                "requirements": "🛠️ Minimal 2 tahun pengalaman • menguasai SQL",
            }
        )
        repository.write_job(raw_input("run-1", "job-text-cleanup"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        listing = payload["jobListing"]
        assert "🌟" not in (listing["description"] or "")
        assert "🛠️" not in (listing["requirementSummary"] or "")
        assert "️" not in (listing["description"] or "")
        assert "️" not in (listing["requirementSummary"] or "")
        assert "•" not in (listing["description"] or "")
        assert "•" not in (listing["requirementSummary"] or "")


def test_backend_payload_normalizes_requirement_summary_language_to_english() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "requirements": "Experience: minimum 2 years. Skills: Python, SQL.",
            }
        )
        repository.write_job(raw_input("run-1", "job-requirement-id"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        summary = payload["jobListing"]["requirementSummary"]
        assert summary is not None
        assert not summary.startswith("Kualifikasi utama:")
        assert "minimum 2 years" in summary.casefold()
        assert "<ul>" in summary or "<p>" in summary


def test_backend_payload_removes_meta_description_disclaimer_phrase() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "description": (
                    "Deskripsi peran ini disusun ulang dalam Bahasa Indonesia. "
                    "Mengembangkan layanan backend dengan fokus reliabilitas sistem."
                ),
                "requirements": "Minimal 2 tahun pengalaman backend.",
            }
        )
        repository.write_job(raw_input("run-1", "job-description-guard"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        description = payload["jobListing"]["description"] or ""
        lowered = description.casefold()
        assert "deskripsi peran ini disusun ulang" not in lowered
        assert "backend engineer" in lowered
        assert "minimum 2 years of experience backend" in lowered


def test_backend_payload_splits_composite_staged_skills_into_atomic_items() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        result = repository.write_job(raw_input("run-1", "job-skill-composite"), canonical_job())
        staging = EnrichmentStagingRepository(session)
        staging.upsert_skill(
            result.normalized_job,
            value="HTML, CSS, PHP",
            confidence=0.8,
            ai_request_log_id=None,
            source=EnrichmentSource.AI,
        )
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        skill_names = {item["name"] for item in payload["skills"]}
        assert {"HTML", "CSS", "PHP"}.issubset(skill_names)


def test_backend_payload_sanitizes_display_html_fields() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "description": (
                    '<p class="x">Bangun <strong onclick="x()">API</strong></p>'
                    "<script>alert(1)</script><img src=x onerror=1>"
                ),
                "requirements": (
                    '<p onclick="x()">Minimal 2 tahun</p><a href="javascript:x">Klik</a>'
                ),
            }
        )
        repository.write_job(raw_input("run-1", "job-html-safe"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        description = payload["jobListing"]["description"] or ""
        summary = payload["jobListing"]["requirementSummary"] or ""

        assert "<p>" in description
        assert "<strong>" in description or "Backend Engineer" in description
        assert "<script" not in description.casefold()
        assert "onclick=" not in description.casefold()
        assert "<img" not in description.casefold()
        assert "<a " not in summary.casefold()
        assert "javascript:" not in summary.casefold()


def test_backend_payload_filters_invalid_skill_tokens_from_summary_and_skills() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "requirements": None,
                "skills": ["mordor_972", "Python"],
            }
        )
        repository.write_job(raw_input("run-1", "job-skill-token"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        assert all("mordor_" not in item["name"].casefold() for item in payload["skills"])
        summary = payload["jobListing"]["requirementSummary"] or ""
        assert "mordor_" not in summary.casefold()


def test_backend_payload_rebuilds_salary_display_when_numeric_salary_exists() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "salary": SalarySchema(
                    min_amount=3_000_000,
                    max_amount=3_000_000,
                    currency="IDR",
                    display="Rp000.000 per month",
                )
            }
        )
        repository.write_job(raw_input("run-1", "job-salary-display"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        assert payload["jobListing"]["salaryDisplay"] == "IDR 3,000,000 / month"


def test_backend_payload_treats_zero_salary_as_missing() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "salary": SalarySchema(
                    min_amount=0,
                    max_amount=0,
                    currency="IDR",
                    display="Rp 0",
                )
            }
        )
        repository.write_job(raw_input("run-1", "job-salary-zero"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        assert payload["jobListing"]["salaryMin"] is None
        assert payload["jobListing"]["salaryMax"] is None
        assert payload["jobListing"]["salaryDisplay"] == "Not specified"


def test_backend_payload_enforces_minimum_relation_fallbacks() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job().model_copy(
            update={
                "title": "Sales Executive",
                "description": "Menjual produk dan membangun relasi dengan pelanggan.",
                "requirements": None,
                "skills": [],
            }
        )
        repository.write_job(raw_input("run-1", "job-minimum-coverage"), job)
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        assert len(payload["skills"]) >= 1
        assert len(payload["requirements"]) >= 1
        assert payload["jobListing"]["requirementSummary"]


def test_backend_payload_filters_low_signal_staged_requirement() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        result = repository.write_job(raw_input("run-1", "job-low-signal"), canonical_job())
        staging = EnrichmentStagingRepository(session)
        staging.upsert_requirement(
            result.normalized_job,
            requirement_type=RequirementType.OTHER,
            value="The most integrated Agrochemical company.",
            confidence=0.9,
            ai_request_log_id=None,
            source=EnrichmentSource.AI,
        )
        session.commit()

        saved = session.scalar(select(NormalizedJob).where(NormalizedJob.external_id == "job-1"))
        assert saved is not None
        payload = build_backend_job_payload(saved).model_dump(mode="json", by_alias=True)
        assert len(payload["requirements"]) >= 1
        assert all(
            "integrated agrochemical company" not in item["value"].casefold()
            for item in payload["requirements"]
        )


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
