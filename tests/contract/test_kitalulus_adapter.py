from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.sources.kitalulus.detail import (
    build_kitalulus_detail_request_body,
    parse_kitalulus_detail_payload,
)
from integrations.sources.kitalulus.list import (
    KitalulusListQuery,
    build_kitalulus_list_request_body,
    parse_kitalulus_list_payload,
)
from integrations.sources.kitalulus.mapper import map_kitalulus_job


def test_kitalulus_list_parser_maps_identity_and_request_body() -> None:
    query = KitalulusListQuery(keyword="developer", page=1, limit=1)
    body = build_kitalulus_list_request_body(query)
    assert body["operationName"] == "Vacancies"
    assert body["variables"]["keyword"] == "developer"
    assert body["variables"]["pagination"] == {"page": 1, "limit": 1}
    assert body["variables"]["filters"][0] == {"key": "sortBy", "value": ["updatedAt"]}

    result = parse_kitalulus_list_payload({"data": {"vacanciesV4": list_payload()}}, query=query)

    assert result.pagination.total_count == 1
    assert result.raw_jobs[0].source_platform == "kitalulus"
    assert result.raw_jobs[0].external_id == "InSGT9JJPXt"
    assert result.raw_jobs[0].source_url.endswith("/fullstack-laravel-developer-scpy")


def test_kitalulus_detail_parser_maps_slug() -> None:
    body = build_kitalulus_detail_request_body("fullstack-laravel-developer-scpy")
    assert body["operationName"] == "VacancyBySlug"
    assert body["variables"] == {"slug": "fullstack-laravel-developer-scpy"}

    detail = parse_kitalulus_detail_payload({"data": {"vacancyBySlug": detail_payload()}})

    assert detail.external_id == "InSGT9JJPXt"
    assert detail.slug == "fullstack-laravel-developer-scpy"


def test_kitalulus_mapper_excludes_benefits_from_requirements() -> None:
    raw = parse_kitalulus_list_payload({"data": {"vacanciesV4": list_payload()}}).raw_jobs[0]
    detail = detail_payload()
    mapped = map_kitalulus_job(
        raw.model_copy(
            update={
                "raw_payload": {
                    "list": raw.raw_payload,
                    "detail": detail,
                    "detailMetadata": {
                        "coverage": "available",
                        "detailCompleteness": "complete",
                        "attempted": True,
                    },
                }
            }
        ),
        scraped_at=datetime(2026, 5, 6, tzinfo=UTC),
    ).job

    assert mapped.source.platform.value == "kitalulus"
    assert mapped.title == "FULLSTACK LARAVEL DEVELOPER"
    assert mapped.company.name == "PT DRW Corpora Indonesia"
    assert mapped.location.city == "Kabupaten Bantul"
    assert mapped.salary is None
    assert mapped.employment_types[0].value == "contract"
    assert mapped.work_type.value == "onsite"
    assert mapped.experience_level.value == "junior"
    assert "Laravel" in (mapped.requirements or "")
    assert "BPJS" not in (mapped.requirements or "")
    assert "MySQL" in mapped.skills


def test_kitalulus_list_parser_rejects_missing_slug() -> None:
    payload = list_payload()
    payload["list"][0]["slug"] = ""

    with pytest.raises(Exception, match="slug"):
        parse_kitalulus_list_payload({"data": {"vacanciesV4": payload}})


def list_payload() -> dict:
    return {
        "hasNextPage": False,
        "hasPrevPage": False,
        "elements": 1,
        "page": 1,
        "list": [
            {
                "id": "InSGT9JJPXt",
                "slug": "fullstack-laravel-developer-scpy",
                "code": "J1761967443343",
                "positionName": "FULLSTACK LARAVEL DEVELOPER",
                "isHighlighted": False,
                "educationLevelStr": "Minimal D3/D4",
                "salaryLowerBound": 0,
                "salaryUpperBound": 0,
                "updatedAtStr": "Terakhir diperbarui pada 17 Apr 2026",
                "genderStr": "Semua jenis kelamin",
                "maxAge": 40,
                "minExperience": 1,
                "typeStr": "Kontrak",
                "company": {"name": "PT DRW Corpora Indonesia", "code": "JC1706598624927"},
                "province": {"name": "DI Yogyakarta"},
                "city": {"name": "Kabupaten Bantul"},
                "jobRole": {"displayName": "Database Developer"},
            }
        ],
    }


def detail_payload() -> dict:
    return {
        "id": "InSGT9JJPXt",
        "slug": "fullstack-laravel-developer-scpy",
        "positionName": "FULLSTACK LARAVEL DEVELOPER",
        "educationLevelStr": "Minimal D3/D4",
        "salaryLowerBound": 0,
        "salaryUpperBound": 0,
        "updatedAt": 1776416740000000,
        "updatedAtStr": "Terakhir diperbarui pada 17 Apr 2026",
        "minExperience": 1,
        "minExperienceStr": "1",
        "typeStr": "Kontrak",
        "locationSiteStr": "Kerja dari kantor (WFO)",
        "formattedDescription": (
            "<p>Kualifikasi :</p><ul><li>Min D3/S1 Teknik Informatika</li>"
            "<li>Menguasai PHP, Laravel, MySQL/MariaDB dan REST API</li></ul>"
        ),
        "skillTags": ["MySQL", "Kerja Tim"],
        "isClosed": False,
        "isPublished": True,
        "googleType": "CONTRACTOR",
        "benefits": [{"id": "Qv455hyZiZ", "copy": "BPJS"}],
        "company": {
            "id": "axEinCCMRO",
            "slug": "pt-drw-corpora-indonesia-1bhw",
            "name": "PT DRW Corpora Indonesia",
            "code": "JC1706598624927",
            "logoUrl": "https://img.kitalulus.com/logo.png?token=redacted",
            "companyIndustry": {"id": "industry-1", "name": "Teknologi"},
        },
        "province": {"id": "690GGlCj7j", "name": "DI Yogyakarta"},
        "city": {"id": "B3werri19L", "name": "Kabupaten Bantul"},
        "jobRole": {"displayName": "Database Developer"},
    }
