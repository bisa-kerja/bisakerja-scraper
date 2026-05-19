from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from shared.text import clean_text

_RELATIVE_LABEL_PATTERN = re.compile(
    r"\b(\d+\s+)?(detik|menit|jam|hari|minggu|bulan|tahun|seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+"
    r"(yang\s+lalu|ago)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedPostedDate:
    posted_at: datetime | None
    posted_label: str | None = None
    reference_time: datetime | None = None


def normalize_posted_date(
    value: Any = None,
    *,
    label: Any = None,
    run_timestamp: datetime | None = None,
) -> NormalizedPostedDate:
    label_text = _optional_text(label)
    value_text = _optional_text(value)
    posted_at = parse_absolute_datetime(value_text)

    if posted_at is None and value_text and _is_relative_label(value_text):
        label_text = label_text or value_text

    return NormalizedPostedDate(
        posted_at=posted_at,
        posted_label=label_text,
        reference_time=_to_aware_utc(run_timestamp) if run_timestamp else None,
    )


def parse_absolute_datetime(value: Any) -> datetime | None:
    text = _optional_text(value)
    if not text or _is_relative_label(text):
        return None

    parsed = _parse_iso_datetime(text)
    if parsed is None:
        parsed_date = _parse_iso_date(text)
        if parsed_date is None:
            return None
        parsed = datetime.combine(parsed_date, time.min, tzinfo=UTC)
    return _to_aware_utc(parsed)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_relative_label(value: str) -> bool:
    lowered = value.lower()
    return bool(_RELATIVE_LABEL_PATTERN.search(lowered)) or lowered in {
        "baru saja",
        "just now",
        "today",
        "yesterday",
    }


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_text(value)
    return None
