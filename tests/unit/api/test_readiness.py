from __future__ import annotations

import pytest

from api.readiness import DatabaseReadinessChecker, ReadinessError, to_async_url


def test_to_async_url_normalizes_sync_postgres_driver() -> None:
    assert (
        to_async_url("postgresql+psycopg://scraper_user:secret@db.example/scraper")
        == "postgresql+asyncpg://scraper_user:secret@db.example/scraper"
    )


def test_to_async_url_drops_neon_channel_binding_for_asyncpg() -> None:
    assert (
        to_async_url(
            "postgresql://scraper_user:secret@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/neondb"
            "?channel_binding=require&sslmode=require"
        )
        == "postgresql+asyncpg://scraper_user:secret@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
    )


@pytest.mark.asyncio
async def test_database_readiness_checker_wraps_engine_creation_failure(monkeypatch) -> None:
    def fake_create_async_engine(*args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("engine creation failed")

    monkeypatch.setattr("api.readiness.create_async_engine", fake_create_async_engine)

    checker = DatabaseReadinessChecker(
        database_url="postgresql+psycopg://scraper_user:secret@db.example/scraper",
        timeout_seconds=1,
    )

    with pytest.raises(ReadinessError, match="dependency unavailable"):
        await checker()


@pytest.mark.asyncio
async def test_database_readiness_checker_uses_async_url(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeConnection:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def execute(self, statement) -> None:  # noqa: ANN001
            return None

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

        async def dispose(self) -> None:
            return None

    def fake_create_async_engine(url: str, **kwargs):  # noqa: ANN003, ANN201
        captured["url"] = url
        return FakeEngine()

    monkeypatch.setattr("api.readiness.create_async_engine", fake_create_async_engine)

    checker = DatabaseReadinessChecker(
        database_url="postgresql+psycopg://scraper_user:secret@db.example/scraper",
        timeout_seconds=1,
    )
    await checker()

    assert captured["url"] == "postgresql+asyncpg://scraper_user:secret@db.example/scraper"
