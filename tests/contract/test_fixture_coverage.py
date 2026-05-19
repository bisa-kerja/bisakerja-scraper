import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.errors import ParseError
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

SCRAPED_AT = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)
FIXTURE_ROOT = Path("tests/fixtures/raw")
SECRET_PATTERN = re.compile(
    r"Bearer\s+(?!<redacted>)|sessionid=(?!<redacted>)|visitorid=(?!<redacted>)|"
    r"authorization[^\n]*:\s*(?!<redacted>)|cookie[^\n]*:\s*(?!<redacted>)",
    re.IGNORECASE,
)

FIXTURE_COVERAGE = {
    "dealls": {
        "list_fixture": "dealls/sample.json",
        "detail_fixture": "dealls/detail.json",
        "mapper": "map_dealls_job",
        "malformed_path": "missing docs/detail result",
    },
    "glints": {
        "list_fixture": "glints/sample.json",
        "detail_fixture": "list fallback",
        "mapper": "map_glints_job",
        "malformed_path": "graphql errors",
    },
    "jobstreet": {
        "list_fixture": "jobstreet/sample.json",
        "detail_fixture": "jobstreet/detail.json",
        "mapper": "map_jobstreet_job",
        "malformed_path": "graphql errors",
    },
    "kalibrr": {
        "list_fixture": "kalibrr/sample.json",
        "detail_fixture": "embedded list job",
        "mapper": "map_kalibrr_job",
        "malformed_path": "missing jobs",
    },
}


def load_fixture(path: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / path).read_text(encoding="utf-8"))


def test_fixture_coverage_report_has_required_paths() -> None:
    assert set(FIXTURE_COVERAGE) == {"dealls", "glints", "jobstreet", "kalibrr"}
    for source, coverage in FIXTURE_COVERAGE.items():
        assert coverage["list_fixture"]
        assert coverage["detail_fixture"]
        assert coverage["mapper"]
        assert coverage["malformed_path"], source


def test_raw_contract_fixtures_are_sanitized_json() -> None:
    fixture_paths = sorted(FIXTURE_ROOT.glob("*/*.json"))

    assert fixture_paths
    for path in fixture_paths:
        text = path.read_text(encoding="utf-8")
        assert not SECRET_PATTERN.search(text), path
        assert isinstance(json.loads(text), dict), path


def test_all_source_fixtures_map_to_canonical_jobs() -> None:
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

    mapped = [dealls, glints, jobstreet, kalibrr]
    assert {item.job.source.platform.value for item in mapped} == {
        "dealls",
        "glints",
        "jobstreet",
        "kalibrr",
    }
    for item in mapped:
        assert item.job.source.external_job_id
        assert item.job.title
        assert item.job.company.name
        assert item.job.last_seen_at == SCRAPED_AT


def test_kalibrr_malformed_payload_is_classified() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_kalibrr_list_payload({"pageProps": {"count": 0}})

    assert exc_info.value.stage.value == "parse"
    assert exc_info.value.source_platform == "kalibrr"
