from modules.jobs.completion import (
    build_source_limited_summary,
    clean_description,
    default_employment_types,
    default_work_type,
    infer_experience_level,
    normalize_location_fields,
)
from modules.jobs.schemas import EmploymentType, ExperienceLevel, WorkType


def test_normalize_location_uses_display_to_fill_region_without_city_whitelist() -> None:
    normalized = normalize_location_fields(
        city="South Jakarta",
        region=None,
        country="Indonesia",
        display="South Jakarta, DKI Jakarta, Indonesia",
        is_remote=False,
    )

    assert normalized["city"] == "South Jakarta"
    assert normalized["region"] == "DKI Jakarta"
    assert normalized["display"] == "South Jakarta, DKI Jakarta, Indonesia"


def test_normalize_location_uses_remote_indonesia_defaults() -> None:
    normalized = normalize_location_fields(
        city=None,
        region=None,
        country="Indonesia",
        display=None,
        is_remote=True,
    )

    assert normalized["city"] == "Remote"
    assert normalized["region"] == "Indonesia"


def test_defaults_cover_work_and_employment() -> None:
    assert default_work_type(WorkType.UNKNOWN) is WorkType.ONSITE
    assert default_employment_types([]) == [EmploymentType.FULL_TIME]


def test_experience_inference_from_year_markers() -> None:
    inferred = infer_experience_level(
        explicit=ExperienceLevel.UNKNOWN,
        title="Backend Engineer",
        description="Minimum 3-5 years of experience in backend systems",
        requirements=None,
    )

    assert inferred is ExperienceLevel.MID_LEVEL


def test_description_placeholder_is_rejected() -> None:
    assert clean_description("-") is None
    assert clean_description("N/A") is None


def test_source_limited_summary_is_transparent() -> None:
    summary = build_source_limited_summary(
        title="Full Stack Developer",
        company="Acme",
        location="Semarang",
        source_platform="glints",
    )

    assert "listing-level" in summary
    assert "Full Stack Developer" in summary
