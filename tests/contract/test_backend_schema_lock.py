from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from integrations.backend.payloads import (
    BackendPayloadValidationError,
    build_backend_job_payload,
)
from integrations.sources.dealls import (
    map_dealls_job,
    merge_dealls_list_and_detail,
    parse_dealls_detail_payload,
    parse_dealls_list_payload,
)
from integrations.sources.glints import map_glints_job, parse_glints_list_payload
from integrations.sources.jobstreet import map_jobstreet_job
from integrations.sources.jobstreet.list import RawSourceJob as JobStreetRawSourceJob
from integrations.sources.kalibrr import (
    map_kalibrr_job,
    merge_kalibrr_list_and_detail,
    parse_kalibrr_list_payload,
)
from modules.enrichment.repositories import EnrichmentSource, EnrichmentStagingRepository
from modules.enrichment.schemas import RequirementType
from modules.persistence import (
    Base,
    JobPersistenceRepository,
    JobRequirementStaging,
    JobSkillStaging,
    NormalizedJob,
    RawJobInput,
)

FIXTURE_ROOT = Path("tests/fixtures/raw")
SCRAPED_AT = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)


def test_backend_payload_contract_accepts_fixture_jobs_for_all_sources() -> None:
    with session_scope() as session:
        mapped_jobs = mapped_jobs_from_fixtures()
        repository = JobPersistenceRepository(session)
        staged_jobs: list[NormalizedJob] = []
        for mapped in mapped_jobs:
            write = repository.write_job(raw_input_from_mapped(mapped), mapped.job)
            staged_jobs.append(write.normalized_job)

        staging = EnrichmentStagingRepository(session)
        staging.upsert_skill(
            staged_jobs[0],
            value="Python",
            confidence=0.9,
            ai_request_log_id=None,
            source=EnrichmentSource.AI,
        )
        staging.upsert_requirement(
            staged_jobs[0],
            requirement_type=RequirementType.EXPERIENCE,
            value="3 years experience",
            confidence=0.8,
            ai_request_log_id=None,
            source=EnrichmentSource.AI,
        )
        session.commit()

        payloads = [
            build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
            for job in session.scalars(select(NormalizedJob)).all()
        ]

    assert {item["sourcePlatform"]["slug"] for item in payloads} == {
        "dealls",
        "glints",
        "jobstreet",
        "kalibrr",
    }
    for payload in payloads:
        listing = payload["jobListing"]
        assert listing["externalJobId"]
        assert listing["sourceUrl"]
        assert listing["externalApplyUrl"]
        assert listing["lastSeenAt"]
        assert listing["status"] in {"ACTIVE", "STALE", "EXPIRED", "CLOSED", "HIDDEN"}

    dealls = next(item for item in payloads if item["sourcePlatform"]["slug"] == "dealls")
    assert dealls["requirements"][0]["type"] == "EXPERIENCE"
    assert dealls["skills"][0]["name"] == "Python"

    jobstreet = next(item for item in payloads if item["sourcePlatform"]["slug"] == "jobstreet")
    assert jobstreet["jobListing"]["salaryPeriod"] in {None, "MONTHLY", "YEARLY"}


def test_backend_payload_contract_rejects_missing_external_job_id() -> None:
    job = normalized_job_for_contract(external_id="")

    with pytest.raises(BackendPayloadValidationError, match="contract validation"):
        build_backend_job_payload(job)


def test_backend_payload_contract_rejects_empty_source_and_apply_url() -> None:
    job = normalized_job_for_contract(
        source_url="",
        apply_url="",
        normalized_payload={
            "source": {"source_url": "", "external_apply_url": ""},
            "company": {"name": "Bisakerja"},
        },
    )

    with pytest.raises(BackendPayloadValidationError, match="contract validation"):
        build_backend_job_payload(job)


def test_backend_payload_contract_rejects_invalid_salary_range() -> None:
    job = normalized_job_for_contract(
        normalized_payload={
            "source": {"source_url": "https://dealls.com/jobs/job-1"},
            "company": {"name": "Bisakerja"},
            "salary": {"min_amount": 100, "max_amount": 10, "currency": "IDR"},
        },
    )

    with pytest.raises(BackendPayloadValidationError) as exc_info:
        build_backend_job_payload(job)

    assert any("salaryMin" in str(item) for item in exc_info.value.details)


def test_backend_payload_contract_rejects_backend_text_limit_drift() -> None:
    job = normalized_job_for_contract(external_id="x" * 256)

    with pytest.raises(BackendPayloadValidationError) as exc_info:
        build_backend_job_payload(job)

    assert any("external_job_id" in str(item) for item in exc_info.value.details)


def test_backend_payload_contract_rejects_orphan_skill_relation() -> None:
    job = normalized_job_for_contract()
    job.skills_staging = [
        JobSkillStaging(
            normalized_job_id="another-job-id",
            source="ai",
            normalized_value="Python",
            confidence=0.9,
        )
    ]

    with pytest.raises(BackendPayloadValidationError, match="orphan JobSkill"):
        build_backend_job_payload(job)


def test_backend_payload_contract_rejects_orphan_requirement_relation() -> None:
    job = normalized_job_for_contract()
    job.requirements_staging = [
        JobRequirementStaging(
            normalized_job_id="another-job-id",
            source="ai",
            requirement_type="EXPERIENCE",
            normalized_value="3 years",
            confidence=0.8,
        )
    ]

    with pytest.raises(BackendPayloadValidationError, match="orphan JobRequirement"):
        build_backend_job_payload(job)


def test_backend_payload_contract_rejects_invalid_requirement_enum() -> None:
    job = normalized_job_for_contract()
    job.requirements_staging = [
        JobRequirementStaging(
            normalized_job_id=job.id,
            source="ai",
            requirement_type="LOCATION",
            normalized_value="Jakarta",
            confidence=0.5,
        )
    ]

    with pytest.raises(BackendPayloadValidationError, match="invalid requirement type"):
        build_backend_job_payload(job)


def test_backend_payload_contract_applies_completion_defaults_for_high_value_fields() -> None:
    job = normalized_job_for_contract(
        source_platform="glints",
        source_url="https://glints.com/id/opportunities/jobs/glints-1",
        apply_url=None,
        normalized_payload={
            "source": {
                "source_url": "https://glints.com/id/opportunities/jobs/glints-1",
                "external_apply_url": "",
            },
            "company": {"name": "Glints Company"},
            "location": {
                "city": "South Jakarta",
                "display": "South Jakarta, DKI Jakarta, Indonesia",
                "country": "Indonesia",
            },
            "salary": {"currency": "", "period": None, "display": "-"},
            "work_type": "unknown",
            "employment_types": [],
            "experience_level": "unknown",
            "description": "-",
            "requirements": "-",
        },
    )

    payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
    listing = payload["jobListing"]
    assert listing["workType"] == "ONSITE"
    assert listing["employmentType"] == "FULL_TIME"
    assert listing["experienceLevel"] == "ENTRY_LEVEL"
    assert listing["province"] == "DKI Jakarta"
    assert listing["city"] == "South Jakarta"
    assert listing["salaryCurrency"] == "IDR"
    assert listing["salaryPeriod"] == "MONTHLY"
    assert listing["salaryDisplay"] == "Tidak dicantumkan"
    assert listing["externalApplyUrl"] == listing["sourceUrl"]
    assert "level listing" in listing["description"]


def test_backend_payload_contract_builds_salary_display_from_numeric_salary() -> None:
    job = normalized_job_for_contract(
        normalized_payload={
            "source": {"source_url": "https://dealls.com/jobs/job-2"},
            "company": {"name": "Bisakerja"},
            "salary": {
                "min_amount": 6000000,
                "max_amount": 7500000,
                "currency": "IDR",
                "period": "monthly",
                "display": "Tidak dicantumkan",
            },
        },
    )

    payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
    listing = payload["jobListing"]
    assert listing["salaryMin"] == 6000000
    assert listing["salaryMax"] == 7500000
    assert listing["salaryDisplay"] == "Rp 6.000.000 - Rp 7.500.000 per bulan"


def mapped_jobs_from_fixtures() -> list[Any]:
    dealls_list = parse_dealls_list_payload(load_fixture("dealls/sample.json"))
    dealls_detail = parse_dealls_detail_payload(load_fixture("dealls/detail.json"))
    dealls = map_dealls_job(
        merge_dealls_list_and_detail(dealls_list.raw_jobs[0], dealls_detail),
        scraped_at=SCRAPED_AT,
    )

    glints_list = parse_glints_list_payload(load_fixture("glints/sample.json"))
    glints = map_glints_job(glints_list.raw_jobs[0], scraped_at=SCRAPED_AT)

    jobstreet_detail = load_fixture("jobstreet/detail.json")["data"]["jobDetails"]
    jobstreet = map_jobstreet_job(
        JobStreetRawSourceJob(
            source_platform="jobstreet",
            external_id="91788065",
            source_url="https://id.jobstreet.com/id/job/91788065",
            raw_payload={"list": {}, "detail": jobstreet_detail},
        ),
        scraped_at=SCRAPED_AT,
    )

    kalibrr_list = parse_kalibrr_list_payload(load_fixture("kalibrr/sample.json"))
    kalibrr = map_kalibrr_job(
        merge_kalibrr_list_and_detail(kalibrr_list.raw_jobs[0]),
        scraped_at=SCRAPED_AT,
    )
    return [dealls, glints, jobstreet, kalibrr]


def raw_input_from_mapped(mapped) -> RawJobInput:  # noqa: ANN001
    source = mapped.job.source
    return RawJobInput(
        scrape_run_id=f"run-{source.platform.value}",
        source_platform=source.platform.value,
        external_id=source.external_job_id,
        source_url=source.source_url,
        raw_payload={"id": source.external_job_id},
        scraped_at=SCRAPED_AT,
    )


def normalized_job_for_contract(
    *,
    source_platform: str = "dealls",
    external_id: str = "job-1",
    source_url: str = "https://dealls.com/jobs/job-1",
    apply_url: str | None = None,
    normalized_payload: dict[str, Any] | None = None,
) -> NormalizedJob:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    return NormalizedJob(
        id="normalized-job-1",
        source_platform=source_platform,
        external_id=external_id,
        title="Backend Engineer",
        company_name="Bisakerja",
        source_url=source_url,
        apply_url=apply_url,
        status="active",
        normalized_payload=normalized_payload
        or {
            "source": {"source_url": source_url},
            "company": {"name": "Bisakerja"},
        },
        last_seen_at=now,
        posted_at=now,
    )


def load_fixture(path: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / path).read_text(encoding="utf-8"))


def session_scope() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
