from pathlib import Path

import pytest
from pydantic import ValidationError

from config.settings import AppEnvironment, Settings


def valid_env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "APP_NAME": "bisakerja-scraper",
        "APP_ENV": "test",
        "PORT": "8000",
        "API_PREFIX": "/api/v1",
        "SCRAPER_DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/scraper_test",
        "BACKEND_SYNC_ENABLED": "false",
        "RUN_DATABASE_TESTS": "false",
        "SCRAPE_SCHEDULE_CRON": "0 1 * * *",
        "NORMALIZE_SCHEDULE_CRON": "30 1 * * *",
        "ENRICH_SCHEDULE_CRON": "0 2 * * *",
        "SYNC_SCHEDULE_CRON": "0 3 * * *",
        "WORKER_CONCURRENCY": "4",
        "SCRAPER_RUN_LOCK_TTL_SECONDS": "7200",
        "HTTP_TIMEOUT_SECONDS": "20",
        "HTTP_MAX_RETRIES": "2",
        "HTTP_RESPONSE_MAX_BYTES": "5242880",
        "DEFAULT_RATE_LIMIT_PER_MINUTE": "60",
        "BACKEND_SYNC_TIMEOUT_SECONDS": "20",
        "BACKEND_SYNC_BATCH_SIZE": "100",
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


def test_settings_load_required_values() -> None:
    settings = Settings(**valid_env(), _env_file=None)

    assert settings.app_name == "bisakerja-scraper"
    assert settings.app_env is AppEnvironment.TEST
    assert settings.backend_database_url is None
    assert settings.cors_origins is None


def test_missing_required_env_fails_fast() -> None:
    env = valid_env()
    del env["SCRAPER_DATABASE_URL"]

    with pytest.raises(ValidationError, match="SCRAPER_DATABASE_URL"):
        Settings(**env, _env_file=None)


def test_empty_required_env_fails_fast() -> None:
    env = valid_env(APP_NAME="")

    with pytest.raises(ValidationError, match="APP_NAME"):
        Settings(**env, _env_file=None)


def test_backend_sync_requires_target_and_token() -> None:
    env = valid_env(BACKEND_SYNC_ENABLED="true")

    with pytest.raises(ValidationError, match="BACKEND_DATABASE_URL"):
        Settings(**env, _env_file=None)


def test_jobstreet_token_required_when_enabled() -> None:
    env = valid_env(JOBSTREET_ENABLED="true")

    with pytest.raises(ValidationError, match="JOBSTREET_BEARER_TOKEN"):
        Settings(**env, _env_file=None)


def test_env_example_is_valid() -> None:
    env_example = Path(__file__).parents[3] / ".env.example"

    settings = Settings(_env_file=env_example)

    assert settings.app_name == "bisakerja-scraper"
