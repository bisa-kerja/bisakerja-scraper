from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.readiness import ReadinessError
from config.settings import Settings


def test_liveness_does_not_call_readiness_check() -> None:
    called = False

    async def readiness_check() -> None:
        nonlocal called
        called = True

    client = TestClient(create_app(settings=make_settings(), readiness_check=readiness_check))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "live"}
    assert called is False


def test_readiness_succeeds_when_check_passes() -> None:
    called = False

    async def readiness_check() -> None:
        nonlocal called
        called = True

    client = TestClient(create_app(settings=make_settings(), readiness_check=readiness_check))

    response = client.get("/health/ready", headers={"x-request-id": "req_ready"})

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ready"}
    assert called is True


def test_readiness_fails_when_database_is_unavailable() -> None:
    async def readiness_check() -> None:
        raise ReadinessError("scraper-db")

    client = TestClient(create_app(settings=make_settings(), readiness_check=readiness_check))

    response = client.get("/health/ready", headers={"x-request-id": "req_down"})

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "message": "Service dependency is unavailable",
        "data": None,
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "details": {"dependency": "scraper-db"},
            "requestId": "req_down",
        },
    }


def make_settings() -> Settings:
    return Settings(**valid_env(LOG_LEVEL="silent"), _env_file=None)


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
        "NOTIFY_HANDOFF_SCHEDULE_CRON": "0 5 * * *",
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
