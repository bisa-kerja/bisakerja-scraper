from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from modules.jobs import CanonicalJobSchema, EmploymentType, SourcePlatform, WorkType


def valid_job_payload() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "source": {
            "platform": "dealls",
            "external_job_id": "69f30ce4b9f8ed001233b47c",
            "source_slug": "academy-project-development-officer",
            "source_url": "https://dealls.com/jobs/academy-project-development-officer",
            "scraped_at": now,
        },
        "title": "Academy Project Development Officer",
        "company": {
            "name": "BINUS Group",
            "logo_url": "https://cdn.sejutacita.id/logo.jpeg",
            "industry": "Education Administration Programs",
        },
        "location": {
            "display": "Jakarta Barat, Indonesia",
            "city": "Jakarta Barat",
            "country": "Indonesia",
        },
        "salary": None,
        "employment_types": ["full_time", "full_time"],
        "work_type": "onsite",
        "skills": ["Project Management", "Project Management"],
        "posted_at": now,
        "last_seen_at": now,
        "status": "active",
        "presentation": {
            "posted_label": None,
            "salary_label": None,
            "badges": ["few_applicants"],
        },
    }


def test_canonical_job_schema_accepts_valid_nullable_payload() -> None:
    job = CanonicalJobSchema.model_validate(valid_job_payload())

    assert job.source.platform is SourcePlatform.DEALLS
    assert job.salary is None
    assert job.employment_types == [EmploymentType.FULL_TIME]
    assert job.work_type is WorkType.ONSITE
    assert job.skills == ["Project Management"]


def test_canonical_job_schema_rejects_missing_identity() -> None:
    payload = valid_job_payload()
    source = dict(payload["source"])  # type: ignore[arg-type]
    source["external_job_id"] = ""
    payload["source"] = source

    with pytest.raises(ValidationError):
        CanonicalJobSchema.model_validate(payload)


def test_canonical_job_schema_rejects_invalid_enum_and_extra_fields() -> None:
    payload = valid_job_payload()
    payload["work_type"] = "office"
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        CanonicalJobSchema.model_validate(payload)


def test_salary_schema_rejects_invalid_range() -> None:
    payload = valid_job_payload()
    payload["salary"] = {
        "min_amount": 10_000_000,
        "max_amount": 5_000_000,
        "currency": "idr",
        "period": "monthly",
    }

    with pytest.raises(ValidationError):
        CanonicalJobSchema.model_validate(payload)
