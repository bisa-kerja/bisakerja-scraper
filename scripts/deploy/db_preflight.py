from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

REQUIRED_KEYS = ("APP_ENV", "SCRAPER_DATABASE_URL")
AUTH_PATTERNS = (
    "password authentication failed",
    "invalidpassword",
    "authentication failed",
)
NETWORK_PATTERNS = (
    "network is unreachable",
    "could not translate host name",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "connection timed out",
    "connection refused",
    "timeout expired",
)


@dataclass(frozen=True)
class PreflightResult:
    name: str
    status: str
    category: str | None
    message: str
    url: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "category": self.category,
            "message": self.message,
            "url": self.url,
        }


def main() -> int:
    parser = argparse.ArgumentParser(prog="deploy-db-preflight")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--from-env", action="store_true")
    parser.add_argument("--include-backend", action="store_true")
    args = parser.parse_args()

    if args.from_env:
        results = run_preflight_values(dict(os.environ), include_backend=args.include_backend)
    elif args.env_file:
        results = run_preflight(Path(args.env_file), include_backend=args.include_backend)
    else:
        parser.error("--env-file or --from-env is required")
    ok = all(result.status == "ok" for result in results)
    print(
        json.dumps(
            {
                "check": "deployment-db-preflight",
                "status": "ok" if ok else "fail",
                "databases": [result.model_dump() for result in results],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if ok else 1


def run_preflight(env_file: Path, *, include_backend: bool = False) -> list[PreflightResult]:
    return run_preflight_values(parse_env_file(env_file), include_backend=include_backend)


def run_preflight_values(
    values: dict[str, str],
    *,
    include_backend: bool = False,
) -> list[PreflightResult]:
    results: list[PreflightResult] = []
    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        return [
            PreflightResult(
                name="config",
                status="fail",
                category="missing_env",
                message=f"missing required env: {', '.join(missing)}",
            )
        ]

    results.append(check_database("scraper", values["SCRAPER_DATABASE_URL"]))
    backend_url = values.get("BACKEND_DATABASE_URL")
    backend_enabled = parse_bool(values.get("BACKEND_SYNC_ENABLED"))
    if include_backend or backend_enabled:
        if not backend_url:
            results.append(
                PreflightResult(
                    name="backend",
                    status="fail",
                    category="missing_env",
                    message="BACKEND_DATABASE_URL is required when backend sync is enabled",
                )
            )
        else:
            results.append(check_database("backend", backend_url))
    return results


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = unquote_env_value(value.strip())
    return values


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def check_database(name: str, database_url: str) -> PreflightResult:
    redacted_url = safe_url(database_url)
    try:
        sync_url = to_sync_url(database_url)
        engine = create_engine(sync_url, poolclass=NullPool, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    except Exception as exc:
        return PreflightResult(
            name=name,
            status="fail",
            category=classify_error(exc),
            message=safe_error_message(exc),
            url=redacted_url,
        )
    return PreflightResult(
        name=name,
        status="ok",
        category=None,
        message="connection ok",
        url=redacted_url,
    )


def to_sync_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        return database_url
    normalized = url
    if normalized.drivername in {
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg_async",
    }:
        normalized = normalized.set(drivername="postgresql+psycopg")
    if is_neon_host(normalized):
        normalized = normalize_neon_query(normalized)
    return normalized.render_as_string(hide_password=False)


def is_neon_host(url: URL) -> bool:
    host = url.host or ""
    return host.endswith(".neon.tech")


def normalize_neon_query(url: URL) -> URL:
    lowered_map = {key.lower(): key for key in url.query}
    if "sslmode" in lowered_map:
        return url
    query = dict(url.query)
    query["sslmode"] = "require"
    return url.set(query=query)


def safe_url(database_url: str) -> str:
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<invalid-url>"


def classify_error(exc: Exception) -> str:
    text_value = normalized_error_text(exc)
    if isinstance(exc, SQLAlchemyError) and "no module named" in text_value:
        return "driver_error"
    if any(pattern in text_value for pattern in AUTH_PATTERNS):
        return "auth_failed"
    if any(pattern in text_value for pattern in NETWORK_PATTERNS):
        return "network_failed"
    if "could not parse sqlalchemy url" in text_value or "invalid" in text_value:
        return "invalid_config"
    return "connection_failed"


def safe_error_message(exc: Exception) -> str:
    text_value = normalized_error_text(exc)
    auth_failed = any(pattern in text_value for pattern in AUTH_PATTERNS)
    if "network is unreachable" in text_value and auth_failed:
        return "database authentication failed; IPv6 reachability is secondary in this trace"
    if auth_failed:
        return "database authentication failed; rotate or redeploy the database secret"
    if "network is unreachable" in text_value:
        return "database network is unreachable from deploy host"
    if "could not translate host name" in text_value:
        return "database hostname cannot be resolved"
    if "name or service not known" in text_value:
        return "database hostname cannot be resolved"
    if "nodename nor servname" in text_value:
        return "database hostname cannot be resolved"
    if "temporary failure in name resolution" in text_value:
        return "database hostname cannot be resolved"
    return f"database connectivity check failed: {exc.__class__.__name__}"


def normalized_error_text(exc: Exception) -> str:
    return str(exc).lower()


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
