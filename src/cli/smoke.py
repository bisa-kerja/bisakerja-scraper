from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from api.app import create_app
from config.settings import Settings
from integrations.sources.dealls import parse_dealls_list_payload
from integrations.sources.dealls.mapper import map_dealls_job


def main(argv: Sequence[str] | None = None) -> int:
    configure_cli_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    command: Callable[[argparse.Namespace], dict[str, Any]] = args.command_handler
    result = command(args)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


def configure_cli_logging() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper-smoke")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config")
    config_parser.add_argument("--env-file", default=None)
    config_parser.set_defaults(command_handler=run_config_check)

    health_parser = subparsers.add_parser("health")
    health_parser.add_argument("--env-file", default=None)
    health_parser.set_defaults(command_handler=run_health_check)

    dry_run_parser = subparsers.add_parser("dry-run")
    dry_run_parser.add_argument("--source", choices=["dealls"], default="dealls")
    dry_run_parser.add_argument(
        "--fixture",
        default="tests/fixtures/raw/dealls/sample.json",
    )
    dry_run_parser.set_defaults(command_handler=run_dry_run)

    return parser


def run_config_check(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    return {
        "check": "config",
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env.value,
        "backendSyncEnabled": settings.backend_sync_enabled,
    }


def run_health_check(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    app = create_app(
        settings=settings,
        readiness_check=noop_readiness,
        job_session_factory=None,
    )
    response = TestClient(app).get("/health/live")
    body = response.json()
    return {
        "check": "health",
        "status": "ok" if response.status_code == 200 and body.get("success") is True else "fail",
        "httpStatus": response.status_code,
        "serviceStatus": body.get("data", {}).get("status"),
    }


def run_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    fixture_path = Path(args.fixture)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if args.source == "dealls":
        result = parse_dealls_list_payload(payload)
        mapped = [map_dealls_job(raw_job).job for raw_job in result.raw_jobs[:1]]
        return {
            "check": "dry-run",
            "status": "ok",
            "source": "dealls",
            "inputJobs": len(result.raw_jobs),
            "mappedJobs": len(mapped),
            "firstExternalJobId": mapped[0].source.external_job_id if mapped else None,
        }
    raise ValueError(f"unsupported source: {args.source}")


def load_settings(env_file: str | None) -> Settings:
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()


async def noop_readiness() -> None:
    return None


if __name__ == "__main__":
    raise SystemExit(main())
