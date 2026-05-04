from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CompanySchema,
    LocationSchema,
    SourceMetadataSchema,
    SourcePlatform,
)
from modules.persistence import ScrapeRun


def migrated_sqlite_engine(database_path: Path) -> Engine:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    return create_engine(f"sqlite:///{database_path}")


def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine)
    with factory() as session:
        run = ScrapeRun(
            id="run-1",
            source_platform="dealls",
            stage="scrape",
            status="completed",
        )
        session.add(run)
        session.commit()
        yield session


def canonical_job(external_id: str, *, title: str = "Backend Engineer") -> CanonicalJobSchema:
    now = datetime(2026, 5, 2, 10, 0, tzinfo=UTC)
    return CanonicalJobSchema(
        source=SourceMetadataSchema(
            platform=SourcePlatform.DEALLS,
            external_job_id=external_id,
            source_url=f"https://dealls.com/jobs/{external_id}",
            scraped_at=now,
        ),
        title=title,
        company=CompanySchema(name="Bisakerja"),
        location=LocationSchema(display="Jakarta"),
        last_seen_at=now,
    )


def make_settings(**overrides: object) -> Settings:
    return Settings(**valid_env(**overrides), _env_file=None)


def valid_env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "APP_NAME": "bisakerja-scraper",
        "APP_ENV": "test",
        "PORT": "8000",
        "API_PREFIX": "/api/v1",
        "SCRAPER_DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/scraper_test",
        "BACKEND_SYNC_ENABLED": "false",
        "RUN_DATABASE_TESTS": "false",
        "SCRAPE_SCHEDULE_CRON": "0 0 * * *",
        "NORMALIZE_SCHEDULE_CRON": "0 2 * * *",
        "ENRICH_SCHEDULE_CRON": "0 4 * * *",
        "SYNC_SCHEDULE_CRON": "0 6 * * *",
        "NOTIFY_HANDOFF_SCHEDULE_CRON": "0 8 * * *",
        "WORKER_CONCURRENCY": "4",
        "SCRAPER_RUN_LOCK_TTL_SECONDS": "7200",
        "HTTP_TIMEOUT_SECONDS": "20",
        "HTTP_MAX_RETRIES": "2",
        "HTTP_RESPONSE_MAX_BYTES": "5242880",
        "DEFAULT_RATE_LIMIT_PER_MINUTE": "60",
        "SCRAPER_KEYWORDS": "developer,intern,ui/ux",
        "SCRAPER_MAX_ITEMS_PER_KEYWORD": "50",
        "SCRAPER_RECENCY_MODE": "latest",
        "SCRAPER_RECENCY_DAYS": "7",
        "BACKEND_SYNC_TIMEOUT_SECONDS": "20",
        "BACKEND_SYNC_BATCH_SIZE": "100",
        "FRESHNESS_STALE_AFTER_HOURS": "72",
        "FRESHNESS_EXPIRED_AFTER_HOURS": "336",
        "AI_ENRICHMENT_ENABLED": "false",
        "OPENAI_TIMEOUT_SECONDS": "30",
        "OPENAI_MAX_RETRIES": "2",
        "OPENAI_BATCH_SIZE": "10",
        "DEALLS_BASE_URL": "https://dealls.com",
        "DEALLS_RATE_LIMIT_PER_MINUTE": "30",
        "GLINTS_GRAPHQL_URL": "https://glints.com/graphql",
        "GLINTS_COUNTRY_CODE": "ID",
        "GLINTS_RATE_LIMIT_PER_MINUTE": "30",
        "JOBSTREET_GRAPHQL_URL": "https://id.jobstreet.com/graphql",
        "JOBSTREET_ENABLED": "false",
        "JOBSTREET_RATE_LIMIT_PER_MINUTE": "20",
        "KALIBRR_BASE_URL": "https://www.kalibrr.com",
        "KALIBRR_BUILD_ID_REFRESH_ENABLED": "true",
        "KALIBRR_RATE_LIMIT_PER_MINUTE": "30",
        "SCRAPER_INTERNAL_SERVICE_TOKEN": "test-service-token",
        "REQUEST_BODY_LIMIT": "1mb",
        "RATE_LIMIT_WINDOW_MS": "60000",
        "RATE_LIMIT_MAX": "120",
        "LOG_LEVEL": "silent",
        "REQUEST_ID_HEADER": "x-request-id",
        "ENABLE_REQUEST_LOGGING": "false",
        "HEALTH_CHECK_TIMEOUT_MS": "2",
    }
    values.update(overrides)
    return values
