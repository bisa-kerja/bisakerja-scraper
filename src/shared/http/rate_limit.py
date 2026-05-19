from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from core.errors import FetchError

RETRIABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class SourceRateLimitConfig:
    source_platform: str
    requests_per_minute: int
    initial_backoff_seconds: float = 0.2
    max_backoff_seconds: float = 30.0
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.source_platform:
            raise ValueError("source_platform must be non-empty")
        if self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be greater than zero")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be greater than or equal to zero")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be greater than or equal to initial backoff")
        if self.circuit_breaker_failure_threshold <= 0:
            raise ValueError("circuit_breaker_failure_threshold must be greater than zero")
        if self.circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("circuit_breaker_cooldown_seconds must be greater than zero")


class SourceRateLimiter:
    def __init__(
        self,
        config: SourceRateLimitConfig,
        *,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._next_available_at = 0.0
        self._failure_count = 0
        self._circuit_open = False
        self._circuit_opened_at: float | None = None

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def circuit_open(self) -> bool:
        return self._circuit_open

    async def wait_before_request(self) -> None:
        async with self._lock:
            now = self._monotonic()
            if self._circuit_open:
                opened_at = self._circuit_opened_at
                if (
                    opened_at is not None
                    and now - opened_at >= self.config.circuit_breaker_cooldown_seconds
                ):
                    # Enter half-open by resetting counters and allowing one new request.
                    self._failure_count = 0
                    self._circuit_open = False
                    self._circuit_opened_at = None
                else:
                    retry_after = max(
                        self.config.circuit_breaker_cooldown_seconds
                        - (0 if opened_at is None else now - opened_at),
                        0.0,
                    )
                    raise FetchError(
                        "source circuit breaker is open",
                        source_platform=self.config.source_platform,
                        details={
                            "failureCount": self._failure_count,
                            "retryAfterSeconds": round(retry_after, 3),
                        },
                        retryable=True,
                    )
            wait_seconds = max(self._next_available_at - now, 0.0)
            scheduled_at = max(now, self._next_available_at)
            self._next_available_at = scheduled_at + (60.0 / self.config.requests_per_minute)

        if wait_seconds > 0:
            await self._sleeper(wait_seconds)

    async def backoff_after_failure(self, failure_count: int | None = None) -> None:
        delay = self.backoff_delay(failure_count or self._failure_count)
        if delay > 0:
            await self._sleeper(delay)

    def record_success(self) -> None:
        self._failure_count = 0
        self._circuit_open = False
        self._circuit_opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.config.circuit_breaker_failure_threshold:
            self._circuit_open = True
            self._circuit_opened_at = self._monotonic()

    def backoff_delay(self, failure_count: int) -> float:
        if failure_count <= 0:
            return 0.0
        delay = self.config.initial_backoff_seconds * (2 ** (failure_count - 1))
        return min(delay, self.config.max_backoff_seconds)


def is_retriable_status(status_code: int) -> bool:
    return status_code in RETRIABLE_STATUS_CODES
