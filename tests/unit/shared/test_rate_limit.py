import pytest

from core.errors import FetchError
from shared.http import SourceRateLimitConfig, SourceRateLimiter, is_retriable_status


@pytest.mark.asyncio
async def test_source_limiter_circuit_isolated_per_source() -> None:
    source_a = SourceRateLimiter(
        SourceRateLimitConfig(
            source_platform="dealls",
            requests_per_minute=60,
            circuit_breaker_failure_threshold=1,
        )
    )
    source_b = SourceRateLimiter(
        SourceRateLimitConfig(
            source_platform="glints",
            requests_per_minute=60,
            circuit_breaker_failure_threshold=1,
        )
    )

    source_a.record_failure()

    with pytest.raises(FetchError) as exc_info:
        await source_a.wait_before_request()

    await source_b.wait_before_request()
    assert exc_info.value.source_platform == "dealls"
    assert source_a.circuit_open is True
    assert source_b.circuit_open is False


def test_backoff_delay_is_exponential_and_capped() -> None:
    limiter = SourceRateLimiter(
        SourceRateLimitConfig(
            source_platform="kalibrr",
            requests_per_minute=60,
            initial_backoff_seconds=0.5,
            max_backoff_seconds=2.0,
        )
    )

    assert limiter.backoff_delay(0) == 0
    assert limiter.backoff_delay(1) == 0.5
    assert limiter.backoff_delay(2) == 1.0
    assert limiter.backoff_delay(3) == 2.0
    assert limiter.backoff_delay(4) == 2.0


def test_retry_classifier_matches_transient_status_policy() -> None:
    assert is_retriable_status(429) is True
    assert is_retriable_status(503) is True
    assert is_retriable_status(408) is True
    assert is_retriable_status(400) is False
    assert is_retriable_status(401) is False
    assert is_retriable_status(404) is False


@pytest.mark.asyncio
async def test_source_limiter_circuit_recovers_after_cooldown() -> None:
    now = 0.0

    async def sleeper(_seconds: float) -> None:
        return None

    limiter = SourceRateLimiter(
        SourceRateLimitConfig(
            source_platform="dealls",
            requests_per_minute=60,
            circuit_breaker_failure_threshold=1,
            circuit_breaker_cooldown_seconds=5.0,
        ),
        sleeper=sleeper,
        monotonic=lambda: now,
    )

    limiter.record_failure()

    with pytest.raises(FetchError):
        await limiter.wait_before_request()

    now = 5.0
    await limiter.wait_before_request()
    assert limiter.circuit_open is False
    assert limiter.failure_count == 0
