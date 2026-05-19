from modules.jobs.salary import normalize_salary
from modules.jobs.schemas import SalaryPeriod


def test_normalize_salary_accepts_null_salary() -> None:
    normalized = normalize_salary()

    assert normalized.salary is None
    assert normalized.original_label is None


def test_normalize_salary_preserves_structured_range_and_label() -> None:
    normalized = normalize_salary(
        min_amount=5_000_000,
        max_amount=8_000_000,
        currency="idr",
        period="monthly",
        label="Rp 5.000.000 - 8.000.000 / bulan",
    )

    assert normalized.salary is not None
    assert normalized.salary.min_amount == 5_000_000
    assert normalized.salary.max_amount == 8_000_000
    assert normalized.salary.currency == "IDR"
    assert normalized.salary.period is SalaryPeriod.MONTHLY
    assert normalized.salary.display == "Rp 5.000.000 - 8.000.000 / bulan"
    assert normalized.original_label == "Rp 5.000.000 - 8.000.000 / bulan"


def test_normalize_salary_parses_indonesian_range_label() -> None:
    normalized = normalize_salary(label="Rp 5 - 8 juta per bulan")

    assert normalized.salary is not None
    assert normalized.salary.min_amount == 5_000_000
    assert normalized.salary.max_amount == 8_000_000
    assert normalized.salary.currency == "IDR"
    assert normalized.salary.period is SalaryPeriod.MONTHLY
    assert normalized.salary.display == "Rp 5 - 8 juta per bulan"


def test_normalize_salary_keeps_unparsed_label() -> None:
    normalized = normalize_salary(label="Competitive salary")

    assert normalized.salary is not None
    assert normalized.salary.min_amount is None
    assert normalized.salary.max_amount is None
    assert normalized.salary.currency is None
    assert normalized.salary.display == "Competitive salary"


def test_normalize_salary_orders_reversed_range() -> None:
    normalized = normalize_salary(min_amount=8_000_000, max_amount=5_000_000, currency="IDR")

    assert normalized.salary is not None
    assert normalized.salary.min_amount == 5_000_000
    assert normalized.salary.max_amount == 8_000_000
