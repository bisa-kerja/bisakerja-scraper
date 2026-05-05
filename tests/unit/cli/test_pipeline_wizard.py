from __future__ import annotations

import argparse

import pytest

from cli.pipeline import (
    CliInputError,
    build_run_command_tokens,
    positive_int,
    recency_days,
    resolve_wizard_mode,
)


def test_resolve_wizard_mode_from_mode_flag() -> None:
    args = argparse.Namespace(mode="status", dry_run=False, execute=False)
    assert resolve_wizard_mode(args) == "status"


def test_resolve_wizard_mode_from_dry_run_flag() -> None:
    args = argparse.Namespace(mode=None, dry_run=True, execute=False)
    assert resolve_wizard_mode(args) == "dry-run"


def test_resolve_wizard_mode_rejects_conflicting_flags() -> None:
    args = argparse.Namespace(mode="dry-run", dry_run=True, execute=False)
    with pytest.raises(CliInputError):
        resolve_wizard_mode(args)


def test_positive_int_validator() -> None:
    assert positive_int("1") == 1
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int("101")


def test_recency_days_validator() -> None:
    assert recency_days("7") == 7
    with pytest.raises(argparse.ArgumentTypeError):
        recency_days("0")
    with pytest.raises(argparse.ArgumentTypeError):
        recency_days("366")


def test_build_run_command_tokens_contains_required_flags() -> None:
    args = argparse.Namespace(
        stage="scrape",
        source="dealls",
        limit=1,
        keyword=["developer"],
        keywords=None,
        latest=True,
        recency_days=7,
        env_file=".env.example",
        fixture_root="tests/fixtures/raw",
        run_id="wizard-run-1",
        execute=False,
    )
    tokens = build_run_command_tokens(args)

    assert tokens[:4] == ["python", "-m", "cli.pipeline", "run"]
    assert "--dry-run" in tokens
    assert "--execute" not in tokens
    assert "--stage" in tokens
    assert "--source" in tokens
    assert "--env-file" in tokens
