from config.database_urls import to_async_postgres_url, to_sync_postgres_url


def test_to_async_postgres_url_converts_sync_driver() -> None:
    assert (
        to_async_postgres_url("postgresql+psycopg://scraper_user:secret@db.example/scraper")
        == "postgresql+asyncpg://scraper_user:secret@db.example/scraper"
    )


def test_to_async_postgres_url_neon_drops_channel_binding_and_enforces_sslmode() -> None:
    assert (
        to_async_postgres_url(
            "postgresql://user:secret@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/neondb"
            "?channel_binding=require"
        )
        == "postgresql+asyncpg://user:secret@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
    )


def test_to_sync_postgres_url_neon_preserves_channel_binding_and_enforces_sslmode() -> None:
    assert (
        to_sync_postgres_url(
            "postgresql+asyncpg://user:secret@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/neondb"
            "?channel_binding=require"
        )
        == "postgresql+psycopg://user:secret@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/neondb?channel_binding=require&sslmode=require"
    )
