from __future__ import annotations

import pytest
from tests.unit.config.test_settings import valid_env

from cli.pipeline import build_live_jobstreet_source
from config.settings import Settings
from core.errors import FetchError


class _FailingPublicClient:
    def __init__(self, call_counter: dict[str, int]) -> None:
        self._call_counter = call_counter

    async def __aenter__(self) -> _FailingPublicClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def request_text(self, *_args, **_kwargs) -> str:
        self._call_counter["public"] += 1
        raise FetchError(
            "blocked",
            source_platform="jobstreet",
            details={"statusCode": 403, "blocker": "cloudflare_challenge"},
            retryable=False,
        )


class _UnusedDetailClient:
    async def __aenter__(self) -> _UnusedDetailClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def request_json(
        self,
        *_args,
        **_kwargs,
    ):  # pragma: no cover - guard path returns earlier
        raise AssertionError("detail client should not be called for cloudflare guard")


@pytest.mark.asyncio
async def test_jobstreet_cloudflare_guard_short_circuits_following_keywords(monkeypatch) -> None:
    settings = Settings(
        **valid_env(
            JOBSTREET_ENABLED="true",
            JOBSTREET_BEARER_TOKEN="test-jobstreet-token",
        ),
        _env_file=None,
    )
    calls = {"public": 0}
    challenge_state: dict[str, str | bool] = {
        "blocked": False,
        "reason": "cloudflare_challenge",
    }

    monkeypatch.setattr(
        "cli.pipeline.build_jobstreet_public_http_client",
        lambda **_kwargs: _FailingPublicClient(calls),
    )
    monkeypatch.setattr(
        "cli.pipeline.build_jobstreet_http_client",
        lambda **_kwargs: _UnusedDetailClient(),
    )

    first = build_live_jobstreet_source(
        keyword="software engineer",
        limit=20,
        recency_mode="latest",
        recency_days=7,
        settings=settings,
        challenge_state=challenge_state,
    )
    jobs_first = await first.fetch_raw_jobs()
    assert jobs_first == []
    assert first.pagination_report() is not None
    assert first.pagination_report()["stopReason"] == "cloudflare_challenge_cookie_required"
    assert calls["public"] == 1
    assert challenge_state["blocked"] is True

    second = build_live_jobstreet_source(
        keyword="backend",
        limit=20,
        recency_mode="latest",
        recency_days=7,
        settings=settings,
        challenge_state=challenge_state,
    )
    jobs_second = await second.fetch_raw_jobs()
    assert jobs_second == []
    assert second.pagination_report() is not None
    assert second.pagination_report()["stopReason"] == "cloudflare_challenge_cookie_required"
    assert calls["public"] == 1
