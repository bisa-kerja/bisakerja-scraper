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
from integrations.sources.glints import parse_glints_list_payload
from integrations.sources.glints.mapper import map_glints_job
from integrations.sources.jobstreet import parse_jobstreet_list_payload
from integrations.sources.jobstreet.mapper import map_jobstreet_job
from integrations.sources.kalibrr import parse_kalibrr_list_payload
from integrations.sources.kalibrr.mapper import map_kalibrr_job


class SmokeCliInputError(ValueError):
    """Raised when CLI input should fail without traceback."""


class SmokeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - exercised via main
        raise SmokeCliInputError(message)


def main(argv: Sequence[str] | None = None) -> int:
    configure_cli_logging()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        command: Callable[[argparse.Namespace], dict[str, Any]] = args.command_handler
        result = command(args)
    except SmokeCliInputError as exc:
        result = {"check": "smoke-cli", "status": "fail", "reason": str(exc)}
    except Exception as exc:  # pragma: no cover - asserted by CLI tests
        result = {
            "check": "smoke-cli",
            "status": "fail",
            "reason": str(exc),
            "errorType": type(exc).__name__,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


def configure_cli_logging() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = SmokeArgumentParser(prog="scraper-smoke")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config")
    config_parser.add_argument("--env-file", default=None)
    config_parser.set_defaults(command_handler=run_config_check)

    health_parser = subparsers.add_parser("health")
    health_parser.add_argument("--env-file", default=None)
    health_parser.set_defaults(command_handler=run_health_check)

    dry_run_parser = subparsers.add_parser("dry-run")
    dry_run_parser.add_argument(
        "--source",
        choices=["dealls", "glints", "jobstreet", "kalibrr"],
        default="dealls",
    )
    dry_run_parser.add_argument(
        "--stage",
        choices=["scrape", "normalize", "enrich", "sync", "notify-handoff"],
        default=None,
    )
    dry_run_parser.add_argument(
        "--fixture",
        default=None,
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
    fixture_path = Path(args.fixture) if args.fixture else default_fixture_path(args.source)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    parsed_jobs, mapped_jobs = parse_and_map_source(source=args.source, payload=payload)
    base_result = {
        "check": "dry-run",
        "status": "ok",
        "source": args.source,
        "fixturePath": str(fixture_path),
        "inputJobs": len(parsed_jobs),
        "mappedJobs": len(mapped_jobs),
        "firstExternalJobId": mapped_jobs[0].source.external_job_id if mapped_jobs else None,
    }
    if args.stage is None:
        return base_result
    return {
        **base_result,
        "stage": args.stage,
        "network": "disabled",
    }


def parse_and_map_source(*, source: str, payload: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    if source == "dealls":
        result = parse_dealls_list_payload(payload)
        mapped = [map_dealls_job(raw_job).job for raw_job in result.raw_jobs[:1]]
        return result.raw_jobs, mapped
    if source == "glints":
        result = parse_glints_list_payload(payload)
        mapped = [map_glints_job(raw_job).job for raw_job in result.raw_jobs[:1]]
        return result.raw_jobs, mapped
    if source == "jobstreet":
        result = parse_jobstreet_list_payload(payload)
        mapped = [map_jobstreet_job(raw_job).job for raw_job in result.raw_jobs[:1]]
        return result.raw_jobs, mapped
    if source == "kalibrr":
        result = parse_kalibrr_list_payload(payload)
        mapped = [map_kalibrr_job(raw_job).job for raw_job in result.raw_jobs[:1]]
        return result.raw_jobs, mapped
    raise SmokeCliInputError(f"unsupported source: {source}")


def default_fixture_path(source: str) -> Path:
    return Path("tests/fixtures/raw") / source / "sample.json"


def load_settings(env_file: str | None) -> Settings:
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()


async def noop_readiness() -> None:
    return None


if __name__ == "__main__":
    raise SystemExit(main())
