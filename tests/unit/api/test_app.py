from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app import create_app
from config.settings import Settings


def test_create_app_import_has_no_database_side_effect() -> None:
    settings = make_settings()
    called = False

    async def readiness_check() -> None:
        nonlocal called
        called = True

    app = create_app(settings=settings, readiness_check=readiness_check)

    assert app.state.settings is settings
    assert called is False


def test_request_id_middleware_accepts_and_returns_request_id() -> None:
    app = create_app(settings=make_settings(), readiness_check=noop_readiness)
    client = TestClient(app)

    response = client.get("/health/live", headers={"x-request-id": "req_test"})

    assert response.headers["x-request-id"] == "req_test"


def test_http_error_uses_standard_envelope() -> None:
    app = create_app(settings=make_settings(), readiness_check=noop_readiness)

    @app.get("/missing-resource")
    async def missing_resource() -> None:
        raise HTTPException(status_code=404, detail="Missing")

    client = TestClient(app)
    response = client.get("/missing-resource", headers={"x-request-id": "req_404"})

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "message": "Missing",
        "data": None,
        "error": {"code": "NOT_FOUND", "details": None, "requestId": "req_404"},
    }


def test_unhandled_error_uses_standard_envelope() -> None:
    app = create_app(settings=make_settings(), readiness_check=noop_readiness)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("private details")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"x-request-id": "req_500"})

    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["message"] == "Unexpected server error"
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert body["error"]["requestId"] == "req_500"


async def noop_readiness() -> None:
    return None


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
