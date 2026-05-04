import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from modules.jobs import EmploymentType, SourcePlatform, WorkType

SCRAPED_AT = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)


def load_fixture(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_map_dealls_fixture_to_canonical_job() -> None:
    list_result = parse_dealls_list_payload(load_fixture("tests/fixtures/raw/dealls/sample.json"))
    detail = parse_dealls_detail_payload(load_fixture("tests/fixtures/raw/dealls/detail.json"))
    enriched = merge_dealls_list_and_detail(list_result.raw_jobs[0], detail)

    mapped = map_dealls_job(enriched, scraped_at=SCRAPED_AT)

    assert mapped.job.source.platform is SourcePlatform.DEALLS
    assert mapped.job.title == "Academy Project Development Officer"
    assert mapped.job.company.name == "BINUS Group"
    assert mapped.job.employment_types == [EmploymentType.FULL_TIME]
    assert mapped.job.work_type is WorkType.ONSITE
    assert "Frontend Engineer" in mapped.job.requirements
    assert mapped.field_provenance["salary"] == "list.salaryRange"


def test_map_glints_fixture_to_canonical_job_without_detail() -> None:
    list_result = parse_glints_list_payload(load_fixture("tests/fixtures/raw/glints/sample.json"))

    mapped = map_glints_job(list_result.raw_jobs[0], scraped_at=SCRAPED_AT)

    assert mapped.job.source.platform is SourcePlatform.GLINTS
    assert mapped.job.title == "Full Stack Developer"
    assert mapped.job.company.name == "Cv Lovina"
    assert mapped.job.location.display == "Semarang Tengah"
    assert mapped.job.work_type is WorkType.ONSITE
    assert "jQuery" in mapped.job.skills
    assert mapped.job.source.external_apply_url == mapped.job.source.source_url
    assert mapped.job.requirements is not None
    assert "Experience: 1-3 years." in mapped.job.requirements
    assert "Skills: jQuery, MySQL." in mapped.job.requirements
    assert mapped.job.presentation.source_labels["detailCoverage"] == "unavailable"
    assert mapped.job.presentation.source_labels["detailCompleteness"] == "partial"


def test_map_glints_visibility_defaults_status_to_active_for_unknown_state() -> None:
    list_result = parse_glints_list_payload(load_fixture("tests/fixtures/raw/glints/sample.json"))
    raw_job = list_result.raw_jobs[0].model_copy(
        update={"raw_payload": {**list_result.raw_jobs[0].raw_payload, "status": "UNMAPPED"}}
    )

    mapped = map_glints_job(raw_job, scraped_at=SCRAPED_AT)

    assert mapped.job.status.value == "active"


def test_map_jobstreet_detail_fixture_to_canonical_job() -> None:
    detail = load_fixture("tests/fixtures/raw/jobstreet/detail.json")["data"]["jobDetails"]
    raw_job = JobStreetRawSourceJob(
        source_platform="jobstreet",
        external_id="91788065",
        source_url="https://id.jobstreet.com/id/job/91788065",
        raw_payload={"list": {}, "detail": detail},
    )

    mapped = map_jobstreet_job(raw_job, scraped_at=SCRAPED_AT)

    assert mapped.job.source.platform is SourcePlatform.JOBSTREET
    assert mapped.job.title == "PROGRAMMER / DEVELEPOR MADYA"
    assert mapped.job.company.name == "Gamma Persada"
    assert mapped.job.location.display == "Jakarta Selatan, Jakarta Raya"
    assert mapped.job.work_type is WorkType.ONSITE
    assert "PROGRAMMER /DEVELOPER MADYA" in mapped.job.description
    assert mapped.job.presentation.posted_label == "3 hari yang lalu"


def test_map_kalibrr_fixture_to_canonical_job_with_clean_html() -> None:
    list_result = parse_kalibrr_list_payload(load_fixture("tests/fixtures/raw/kalibrr/sample.json"))
    enriched = merge_kalibrr_list_and_detail(list_result.raw_jobs[0])

    mapped = map_kalibrr_job(enriched, scraped_at=SCRAPED_AT)

    assert mapped.job.source.platform is SourcePlatform.KALIBRR
    assert mapped.job.title == "Head of Commercial Strategy & Marketing"
    assert mapped.job.company.name == "Simbadda Group"
    assert mapped.job.location.city == "North Jakarta"
    assert mapped.job.work_type is WorkType.ONSITE
    assert "<p>" not in mapped.job.description
    assert "Revenue Ownership" in mapped.job.description
    assert mapped.job.presentation.source_labels["detailCoverage"] == "embedded"
