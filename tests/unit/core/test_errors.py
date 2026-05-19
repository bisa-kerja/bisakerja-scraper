from core.errors import FetchError, NormalizeError


def test_scraper_error_log_fields_are_safe_and_structured() -> None:
    error = FetchError(
        "source timeout",
        source_platform="dealls",
        external_id="job-1",
        details={"statusClass": "5xx"},
    )

    assert error.to_log_fields() == {
        "errorCategory": "FETCH_ERROR",
        "stage": "fetch",
        "sourcePlatform": "dealls",
        "externalJobId": "job-1",
        "retryable": True,
        "details": {"statusClass": "5xx"},
    }


def test_non_retriable_stage_error() -> None:
    assert NormalizeError("invalid identity").retryable is False
