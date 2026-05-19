from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from modules.jobs.schemas import SalaryPeriod, SalarySchema
from shared.text import clean_text

_NUMBER_PATTERN = re.compile(
    r"(?P<number>\d+(?:[.,]\d{3})*(?:[.,]\d+)?)\s*(?P<unit>jt|juta|m|million|rb|ribu|k)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedSalary:
    salary: SalarySchema | None
    original_label: str | None = None


def normalize_salary(
    *,
    min_amount: Any = None,
    max_amount: Any = None,
    currency: Any = None,
    period: Any = None,
    label: Any = None,
    default_currency: str | None = None,
    default_period: SalaryPeriod | str | None = None,
) -> NormalizedSalary:
    display = _optional_text(label)
    parsed = _parse_salary_label(display)
    min_value = _optional_int(min_amount)
    max_value = _optional_int(max_amount)
    currency_value = (
        _normalize_currency(currency) or parsed.currency or _normalize_currency(default_currency)
    )
    period_value = _normalize_period(period) or parsed.period or _normalize_period(default_period)

    if min_value is None:
        min_value = parsed.min_amount
    if max_value is None:
        max_value = parsed.max_amount

    if min_value is not None and max_value is not None and min_value > max_value:
        min_value, max_value = max_value, min_value

    if not any(
        [min_value is not None, max_value is not None, currency_value, period_value, display]
    ):
        return NormalizedSalary(salary=None, original_label=None)

    salary = SalarySchema(
        min_amount=min_value,
        max_amount=max_value,
        currency=currency_value,
        period=period_value,
        display=display,
    )
    return NormalizedSalary(salary=salary, original_label=display)


@dataclass(frozen=True)
class _ParsedLabel:
    min_amount: int | None = None
    max_amount: int | None = None
    currency: str | None = None
    period: SalaryPeriod | None = None


def _parse_salary_label(label: str | None) -> _ParsedLabel:
    if not label:
        return _ParsedLabel()

    amounts = _parse_amounts(label)
    min_amount = amounts[0] if amounts else None
    max_amount = amounts[1] if len(amounts) > 1 else None
    return _ParsedLabel(
        min_amount=min_amount,
        max_amount=max_amount,
        currency=_currency_from_label(label),
        period=_period_from_label(label),
    )


def _parse_amounts(label: str) -> list[int]:
    matches = list(_NUMBER_PATTERN.finditer(label))
    if not matches:
        return []

    inherited_multiplier = _label_multiplier(label)
    amounts: list[int] = []
    for match in matches[:2]:
        number = _parse_decimal_number(match.group("number"))
        if number is None:
            continue
        multiplier = _unit_multiplier(match.group("unit")) or inherited_multiplier
        amounts.append(int(number * multiplier))
    return amounts


def _parse_decimal_number(value: str) -> Decimal | None:
    normalized = value.strip()
    if not normalized:
        return None
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    elif normalized.count(".") > 1:
        normalized = normalized.replace(".", "")
    else:
        parts = normalized.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            normalized = "".join(parts)
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _label_multiplier(label: str) -> Decimal:
    lowered = label.lower()
    if any(unit in lowered for unit in ("jt", "juta", "million")):
        return Decimal(1_000_000)
    if any(unit in lowered for unit in ("rb", "ribu")):
        return Decimal(1_000)
    return Decimal(1)


def _unit_multiplier(unit: str | None) -> Decimal | None:
    if not unit:
        return None
    normalized = unit.lower()
    if normalized in {"jt", "juta", "m", "million"}:
        return Decimal(1_000_000)
    if normalized in {"rb", "ribu", "k"}:
        return Decimal(1_000)
    return None


def _normalize_currency(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    normalized = text.upper()
    if normalized in {"RP", "RUPIAH"}:
        return "IDR"
    if normalized in {"$", "US$", "USD"}:
        return "USD"
    if len(normalized) == 3 and normalized.isalpha():
        return normalized
    return None


def _currency_from_label(label: str) -> str | None:
    lowered = label.lower()
    if "rp" in lowered or "idr" in lowered or "rupiah" in lowered:
        return "IDR"
    if "usd" in lowered or "$" in label:
        return "USD"
    if "sgd" in lowered:
        return "SGD"
    return None


def _normalize_period(value: Any) -> SalaryPeriod | None:
    if isinstance(value, SalaryPeriod):
        return value
    text = _optional_text(value)
    if not text:
        return None
    normalized = text.lower().replace("_", " ").replace("-", " ")
    if normalized in {"month", "monthly", "bulan", "per bulan", "mo"}:
        return SalaryPeriod.MONTHLY
    if normalized in {"year", "yearly", "tahun", "per tahun", "yr"}:
        return SalaryPeriod.YEARLY
    if normalized in {"day", "daily", "hari", "per hari"}:
        return SalaryPeriod.DAILY
    if normalized in {"hour", "hourly", "jam", "per jam"}:
        return SalaryPeriod.HOURLY
    return SalaryPeriod.UNKNOWN


def _period_from_label(label: str) -> SalaryPeriod | None:
    lowered = label.lower()
    if any(token in lowered for token in ("/bulan", "per bulan", "monthly", "month")):
        return SalaryPeriod.MONTHLY
    if any(token in lowered for token in ("/tahun", "per tahun", "yearly", "year")):
        return SalaryPeriod.YEARLY
    if any(token in lowered for token in ("/hari", "per hari", "daily", "day")):
        return SalaryPeriod.DAILY
    if any(token in lowered for token in ("/jam", "per jam", "hourly", "hour")):
        return SalaryPeriod.HOURLY
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, str):
        decimal_value = _parse_decimal_number(value)
        return int(decimal_value) if decimal_value is not None else None
    return None


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_text(value)
    return None
