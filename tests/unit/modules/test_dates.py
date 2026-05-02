from datetime import UTC, datetime

from modules.jobs.dates import normalize_posted_date, parse_absolute_datetime


def test_parse_absolute_datetime_normalizes_z_suffix_to_utc() -> None:
    parsed = parse_absolute_datetime("2026-05-01T10:30:00Z")

    assert parsed == datetime(2026, 5, 1, 10, 30, tzinfo=UTC)


def test_parse_absolute_datetime_converts_offset_to_utc() -> None:
    parsed = parse_absolute_datetime("2026-05-01T17:30:00+07:00")

    assert parsed == datetime(2026, 5, 1, 10, 30, tzinfo=UTC)


def test_parse_absolute_datetime_accepts_date_only() -> None:
    parsed = parse_absolute_datetime("2026-05-01")

    assert parsed == datetime(2026, 5, 1, 0, 0, tzinfo=UTC)


def test_normalize_posted_date_preserves_relative_label_without_fake_timestamp() -> None:
    run_timestamp = datetime(2026, 5, 2, 1, 0, tzinfo=UTC)

    normalized = normalize_posted_date("3 hari yang lalu", run_timestamp=run_timestamp)

    assert normalized.posted_at is None
    assert normalized.posted_label == "3 hari yang lalu"
    assert normalized.reference_time == run_timestamp


def test_normalize_posted_date_prefers_absolute_value_and_keeps_label() -> None:
    normalized = normalize_posted_date(
        "2026-05-01T10:30:00Z",
        label="3 hari yang lalu",
        run_timestamp=datetime(2026, 5, 2, 1, 0),
    )

    assert normalized.posted_at == datetime(2026, 5, 1, 10, 30, tzinfo=UTC)
    assert normalized.posted_label == "3 hari yang lalu"
    assert normalized.reference_time == datetime(2026, 5, 2, 1, 0, tzinfo=UTC)


def test_parse_absolute_datetime_rejects_invalid_value() -> None:
    assert parse_absolute_datetime("not a date") is None
