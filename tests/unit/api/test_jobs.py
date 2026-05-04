from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import create_app
from config.settings import Settings
from modules.persistence import Base, NormalizedJob


def test_list_jobs_filters_and_paginates() -> None:
    client = make_client(
        [
            normalized_job("job-1", title="Backend Engineer", location="Jakarta"),
            normalized_job("job-2", title="Frontend Engineer", location="Bandung"),
            normalized_job("job-3", title="Data Analyst", source_platform="glints"),
        ]
    )

    response = client.get(
        "/api/v1/jobs",
        params={"sourcePlatform": "dealls", "keyword": "engineer", "page": 1, "limit": 1},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert [job["id"] for job in body["data"]] == ["job-2"]
    assert body["meta"]["pagination"] == {
        "page": 1,
        "limit": 1,
        "total": 2,
        "totalPages": 2,
        "hasNextPage": True,
        "hasPrevPage": False,
    }


def test_list_jobs_filters_location_and_freshness() -> None:
    client = make_client(
        [
            normalized_job("job-1", location="Jakarta", status="active"),
            normalized_job("job-2", location="Bandung", status="expired"),
        ]
    )

    response = client.get(
        "/api/v1/jobs",
        params={"location": "jakarta", "freshness": "active"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert [job["id"] for job in response.json()["data"]] == ["job-1"]


def test_get_job_detail_returns_standard_envelope() -> None:
    client = make_client([normalized_job("job-1")])

    response = client.get("/api/v1/jobs/job-1", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["externalJobId"] == "external-job-1"


def test_get_job_detail_returns_404_for_missing_job() -> None:
    client = make_client([])

    response = client.get("/api/v1/jobs/missing", headers=auth_headers())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_jobs_endpoint_requires_internal_token() -> None:
    client = make_client([normalized_job("job-1")])

    response = client.get("/api/v1/jobs")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def make_client(jobs: list[NormalizedJob]) -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        session.add_all(jobs)
        session.commit()

    def app_session_factory() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app = create_app(
        settings=make_settings(),
        readiness_check=noop_readiness,
        job_session_factory=app_session_factory,
    )
    return TestClient(app)


def normalized_job(
    job_id: str,
    *,
    title: str = "Backend Engineer",
    source_platform: str = "dealls",
    location: str = "Jakarta",
    status: str = "active",
) -> NormalizedJob:
    suffix = job_id.split("-")[-1]
    now = datetime(2026, 5, 2, 10, int(suffix), tzinfo=UTC)
    return NormalizedJob(
        id=job_id,
        source_platform=source_platform,
        external_id=f"external-{job_id}",
        title=title,
        company_name="Bisakerja",
        source_url=f"https://example.com/{job_id}",
        status=status,
        normalized_payload={
            "title": title,
            "company": {"name": "Bisakerja"},
            "location": {"display": location},
        },
        last_seen_at=now + timedelta(minutes=int(suffix)),
    )


def auth_headers() -> dict[str, str]:
    return {"authorization": "Bearer test-service-token"}


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
