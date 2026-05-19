from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from cli.pipeline import CliInputError, PipelineArgumentParser, cli_fail_result
from config.database_urls import to_sync_postgres_url
from config.settings import Settings

SOURCE_CHOICES = ("all", "dealls", "glints", "jobstreet", "kalibrr", "kitalulus")
STATUS_CHOICES = ("all", "active", "stale", "expired")
FORMAT_CHOICES = ("multi-csv", "single-csv")

DATASET_VERSION = "1.0.0"
DATASET_SCHEMA_VERSION = "1.0.0"
TRAIN_SPLIT = 0.80
VALIDATION_SPLIT = 0.10
DEFAULT_TIMEZONE = "Asia/Jakarta"
DEFAULT_SINGLE_FILE_MAX_FLAT_CHARS = 20_000
DEFAULT_SINGLE_FILE_NAME = "job_listings_single_dataset.csv"

DISPLAY_HTML_TAG_PATTERN = re.compile(r"<\s*/?\s*([a-zA-Z0-9]+)([^>]*)>")
DISPLAY_HTML_ALLOWLIST = {"p", "ul", "ol", "li", "strong", "em", "br"}
DISPLAY_HTML_UNSAFE_TOKEN_PATTERN = re.compile(
    r"(?:<\s*/?\s*(?:script|style|iframe|object|embed|svg)\b|\bon[a-z]+\s*=|javascript\s*:)",
    re.IGNORECASE,
)
REQUIREMENT_SUMMARY_PREFIX_PATTERN = re.compile(
    r"^\s*(?:<p>\s*)?(kualifikasi utama|kualifikasi|persyaratan)\s*:\s*",
    re.IGNORECASE,
)
HTML_TAG_STRIPPER = re.compile(r"<[^>]+>")
TRACKING_KEY_PATTERN = re.compile(r"(trace|tracking|queryid|query_id|solid|sol_id)", re.IGNORECASE)

TASKS_SUPPORTED = (
    "job_search_ranking",
    "job_fit_scoring",
    "skill_gap_analysis",
    "career_strategy_recommendation",
    "cv_analyzer_job_context",
    "application_intelligence",
    "eda_trend_analysis",
    "xai_explanation",
)
TASKS_UNSUPPORTED = (
    "user_profile_embedding",
    "cv_raw_text_scoring",
    "personalized_outcome_prediction",
)

JOB_LISTINGS_COLUMNS = [
    "job_id",
    "source_platform_id",
    "source_platform_slug",
    "source_platform_name",
    "source_platform_base_url",
    "source_platform_is_active",
    "company_id",
    "company_name",
    "company_slug",
    "company_logo_url",
    "company_website_url",
    "ingestion_run_id",
    "external_job_id",
    "dataset_exported_at",
    "dataset_version",
    "dataset_row_hash",
    "dataset_schema_version",
    "title",
    "normalized_title",
    "category",
    "description",
    "requirement_summary",
    "work_type",
    "employment_type",
    "experience_level",
    "location_display",
    "province",
    "city",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_display",
    "source_url",
    "external_apply_url",
    "source_posted_at",
    "source_updated_at",
    "last_seen_at",
    "expired_at",
    "status",
    "created_at",
    "updated_at",
    "is_stale",
    "has_salary_range",
    "salary_midpoint",
    "salary_range_width",
    "location_key",
    "search_blob_preview",
    "detail_readiness_score",
    "description_length_chars",
    "description_paragraph_count",
    "requirement_summary_length_chars",
    "requirement_summary_has_prefix_legacy",
    "has_safe_display_html",
    "has_unsafe_html_signal",
    "language_signal",
    "is_mixed_language_signal",
    "normalization_completeness_score",
    "requirements_count_total",
    "requirements_count_skill",
    "requirements_count_experience",
    "requirements_count_education",
    "requirements_count_responsibility",
    "requirements_count_other",
    "requirements_priority_high_count",
    "requirements_priority_medium_count",
    "requirements_priority_low_count",
    "requirements_first_value",
    "requirements_concat",
    "skills_count_total",
    "skills_unique_slug_count",
    "skills_confidence_avg",
    "skills_confidence_min",
    "skills_confidence_max",
    "skills_top_10_names",
    "skills_top_10_slugs",
    "skills_categories_concat",
    "bookmark_count_total",
    "bookmark_last_created_at",
    "application_count_total",
    "application_count_applied",
    "application_count_interview",
    "application_count_rejected",
    "application_count_accepted",
    "application_last_status",
    "application_last_applied_at",
    "application_last_updated_at",
    "fit_score_run_count",
    "fit_score_latest",
    "fit_score_latest_readiness_level",
    "fit_score_latest_decision",
    "fit_score_latest_model_name",
    "fit_score_latest_analyzed_at",
    "skill_gap_run_count",
    "skill_gap_latest_gap_count",
    "skill_gap_latest_model_name",
    "skill_gap_latest_analyzed_at",
    "cv_analysis_run_count",
    "cv_analysis_latest_language",
    "cv_analysis_latest_input_mode",
    "cv_analysis_latest_compare_source",
    "cv_analysis_latest_model_name",
    "cv_analysis_latest_analyzed_at",
    "ai_request_count_total",
    "ai_request_count_succeeded",
    "ai_request_count_failed",
    "ai_request_latest_kind",
    "ai_request_latest_status",
    "ai_request_latest_model_name",
    "ai_request_latest_created_at",
    "ai_request_error_code_top",
    "filter_keyword_ready",
    "filter_location_ready",
    "filter_work_type_ready",
    "filter_employment_type_ready",
    "filter_experience_ready",
    "filter_salary_ready",
    "filter_category_ready",
    "fit_input_has_requirements",
    "fit_input_has_skills",
    "fit_input_has_experience_signal",
    "fit_input_quality_score",
    "skill_gap_input_coverage_score",
    "skill_gap_requirements_vs_skills_ratio",
    "tracker_signal_available",
    "tracker_conversion_state",
]

JOB_REQUIREMENTS_COLUMNS = [
    "job_id",
    "requirement_id",
    "requirement_type",
    "requirement_value",
    "requirement_priority",
    "requirement_sort_order",
    "requirement_created_at",
    "source_platform_slug",
    "company_name",
    "job_title",
    "job_status",
    "job_last_seen_at",
]

JOB_SKILLS_COLUMNS = [
    "job_id",
    "job_skill_id",
    "skill_id",
    "skill_name",
    "skill_slug",
    "skill_category",
    "skill_confidence",
    "job_skill_created_at",
    "source_platform_slug",
    "company_name",
    "job_title",
    "job_status",
    "job_last_seen_at",
]

JOB_USER_SIGNALS_COLUMNS = [
    "job_id",
    "source_platform_slug",
    "job_title",
    "company_name",
    "job_status",
    "bookmark_count_total",
    "bookmark_last_created_at",
    "application_count_total",
    "application_count_applied",
    "application_count_interview",
    "application_count_rejected",
    "application_count_accepted",
    "application_last_status",
    "application_last_applied_at",
    "application_last_updated_at",
    "fit_score_run_count",
    "fit_score_latest",
    "fit_score_latest_readiness_level",
    "fit_score_latest_decision",
    "fit_score_latest_model_name",
    "fit_score_latest_analyzed_at",
    "skill_gap_run_count",
    "skill_gap_latest_gap_count",
    "skill_gap_latest_model_name",
    "skill_gap_latest_analyzed_at",
    "cv_analysis_run_count",
    "cv_analysis_latest_language",
    "cv_analysis_latest_input_mode",
    "cv_analysis_latest_compare_source",
    "cv_analysis_latest_model_name",
    "cv_analysis_latest_analyzed_at",
    "ai_request_count_total",
    "ai_request_count_succeeded",
    "ai_request_count_failed",
    "ai_request_latest_kind",
    "ai_request_latest_status",
    "ai_request_latest_model_name",
    "ai_request_latest_created_at",
    "ai_request_error_code_top",
]

MODEL_COLUMNS = [
    "job_id",
    "external_job_id",
    "source_platform_slug",
    "company_id",
    "company_name",
    "dataset_version",
    "dataset_schema_version",
    "dataset_exported_at",
    "model_split",
    "split_group_key",
    "is_holdout_source",
    "is_low_confidence_label",
    "label_confidence_score",
    "supported_model_tasks_json",
    "unsupported_model_tasks_json",
    "model_task_readiness_json",
    "model_task_blockers_json",
    "model_input_title",
    "model_input_normalized_title",
    "model_input_company_context",
    "model_input_location_context",
    "model_input_salary_context",
    "model_input_description_plaintext",
    "model_input_requirement_summary_plaintext",
    "model_input_requirements_text",
    "model_input_skills_text",
    "model_input_full_context",
    "model_input_short_context",
    "model_input_cv_compare_context",
    "model_input_career_copilot_context",
    "label_work_type",
    "label_employment_type",
    "label_experience_level",
    "label_category",
    "label_role_family",
    "label_seniority_bucket",
    "label_salary_bucket",
    "label_location_city",
    "label_location_province",
    "label_is_remote_friendly",
    "label_is_entry_level_friendly",
    "label_is_tech_or_digital_role",
    "label_job_search_rank_bucket",
    "label_recommendation_candidate_tier",
    "skills_json",
    "skill_slugs_json",
    "skill_names_json",
    "skill_categories_json",
    "skill_count",
    "skill_confidence_avg",
    "skill_source_quality",
    "primary_skill_slug",
    "primary_skill_category",
    "required_skill_keywords_json",
    "optional_skill_keywords_json",
    "skill_embedding_text",
    "requirements_json",
    "requirements_skill_json",
    "requirements_experience_json",
    "requirements_education_json",
    "requirements_responsibility_json",
    "requirements_other_json",
    "requirements_count_total",
    "requirements_type_distribution_json",
    "requirements_priority_distribution_json",
    "requirement_classification_quality_score",
    "requirement_keywords_json",
    "ats_keywords_json",
    "important_requirement_highlights_json",
    "fit_context_skills_required_json",
    "fit_context_experience_requirements_json",
    "fit_context_education_requirements_json",
    "fit_context_responsibilities_json",
    "fit_context_preferences_json",
    "skill_gap_target_skills_json",
    "skill_gap_core_skills_json",
    "skill_gap_optional_skills_json",
    "readiness_signal_level",
    "candidate_matching_weight_json",
    "job_fit_feature_vector_json",
    "preference_match_feature_vector_json",
    "experience_match_feature_vector_json",
    "skill_match_feature_vector_json",
    "skill_gap_feature_vector_json",
    "weak_label_apply_priority",
    "weak_label_job_quality_tier",
    "weak_label_market_salary_signal",
    "weak_label_freshness_signal",
    "weak_label_search_relevance_keywords_json",
    "weak_label_role_keywords_json",
    "weak_label_readiness_level",
    "weak_label_success_probability_bucket",
    "weak_label_actionable_next_steps_json",
    "text_quality_score",
    "normalization_completeness_score",
    "model_input_token_estimate",
    "has_minimum_model_context",
    "missing_model_context_fields_json",
    "source_posted_at",
    "last_seen_at",
    "status",
    "ai_request_latest_model_name",
    "ai_request_count_failed",
    "xai_skill_evidence_json",
    "xai_experience_evidence_json",
    "xai_preference_evidence_json",
    "xai_requirement_evidence_json",
    "xai_salary_location_evidence_json",
    "evaluation_expected_outputs_json",
    "evaluation_rubric_json",
]


@dataclass(frozen=True)
class DatasetExportOptions:
    env_file: str | None
    output_dir: Path
    output_format: str
    source: str
    status: str
    include_ai_signals: bool
    include_user_signals: bool
    include_model_dataset: bool
    limit: int | None
    updated_since_utc: datetime | None
    timezone: ZoneInfo
    single_file_max_flat_chars: int


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CliInputError as exc:
        result = cli_fail_result(check="dataset-cli", reason=str(exc), command="parse")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    except SystemExit as exc:
        if exc.code == 0:
            raise
        result = cli_fail_result(
            check="dataset-cli",
            reason="argument parsing failed",
            command="parse",
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    try:
        result = args.command_handler(args)
    except CliInputError as exc:
        result = cli_fail_result(check="dataset-jobs-csv", reason=str(exc), command=args.command)
    except Exception as exc:  # pragma: no cover
        result = cli_fail_result(
            check="dataset-jobs-csv",
            reason=str(exc),
            command=args.command,
            error_type=type(exc).__name__,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = PipelineArgumentParser(prog="dataset-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    jobs_csv = subparsers.add_parser("jobs-csv")
    jobs_csv.add_argument("--env-file", default=None)
    jobs_csv.add_argument("--output-dir", required=True)
    jobs_csv.add_argument("--format", choices=FORMAT_CHOICES, default="multi-csv")
    jobs_csv.add_argument("--source", choices=SOURCE_CHOICES, default="all")
    jobs_csv.add_argument("--status", choices=STATUS_CHOICES, default="all")
    jobs_csv.add_argument(
        "--include-ai-signals",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    jobs_csv.add_argument(
        "--include-user-signals",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    jobs_csv.add_argument(
        "--include-model-dataset",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    jobs_csv.add_argument("--limit", type=positive_limit, default=None)
    jobs_csv.add_argument("--updated-since", default=None)
    jobs_csv.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    jobs_csv.add_argument(
        "--single-file-max-flat-chars",
        type=positive_flatten_limit,
        default=DEFAULT_SINGLE_FILE_MAX_FLAT_CHARS,
    )
    jobs_csv.set_defaults(command_handler=run_jobs_csv)
    return parser


def run_jobs_csv(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    backend_url = settings.backend_database_url
    if not backend_url:
        raise CliInputError("BACKEND_DATABASE_URL is required for jobs-csv export")

    output_dir = Path(args.output_dir).expanduser().resolve()
    ensure_writable_directory(output_dir)
    timezone = resolve_timezone(args.timezone)
    updated_since_utc = (
        parse_updated_since(args.updated_since, timezone) if args.updated_since else None
    )

    options = DatasetExportOptions(
        env_file=args.env_file,
        output_dir=output_dir,
        output_format=args.format,
        source=args.source,
        status=args.status,
        include_ai_signals=bool(args.include_ai_signals),
        include_user_signals=bool(args.include_user_signals),
        include_model_dataset=bool(args.include_model_dataset),
        limit=args.limit,
        updated_since_utc=updated_since_utc,
        timezone=timezone,
        single_file_max_flat_chars=args.single_file_max_flat_chars,
    )
    exported_at = datetime.now(UTC)
    engine = create_engine(to_sync_postgres_url(backend_url), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            data = collect_export_payload(
                connection, options=options, exported_at=exported_at, settings=settings
            )
    except SQLAlchemyError as exc:
        raise CliInputError(f"dataset export query failed: {exc}") from exc
    finally:
        engine.dispose()

    files_written = write_dataset_files(options=options, payload=data)
    return {
        "check": "dataset-jobs-csv",
        "status": "ok",
        "mode": options.output_format,
        "outputDir": str(options.output_dir),
        "rowCounts": data["counts"],
        "files": files_written,
        "filters": {
            "source": options.source,
            "status": options.status,
            "limit": options.limit,
            "updatedSinceUtc": iso_utc(options.updated_since_utc),
            "includeAiSignals": options.include_ai_signals,
            "includeUserSignals": options.include_user_signals,
            "includeModelDataset": options.include_model_dataset,
            "timezone": str(options.timezone),
        },
    }


def positive_limit(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def positive_flatten_limit(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    if parsed > 500_000:
        raise argparse.ArgumentTypeError("must be less than or equal to 500000")
    return parsed


def load_settings(env_file: str | None) -> Settings:
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()


def resolve_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except Exception as exc:  # pragma: no cover
        raise CliInputError(f"invalid timezone: {value}") from exc


def parse_updated_since(value: str, timezone: ZoneInfo) -> datetime:
    raw = value.strip()
    if not raw:
        raise CliInputError("--updated-since must not be empty")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CliInputError("--updated-since must be ISO 8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def ensure_writable_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CliInputError(f"cannot create output directory: {path}") from exc
    probe = path / ".write_probe.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise CliInputError(f"output directory is not writable: {path}") from exc


def collect_export_payload(
    connection: Connection,
    *,
    options: DatasetExportOptions,
    exported_at: datetime,
    settings: Settings,
) -> dict[str, Any]:
    jobs = fetch_jobs(connection, options=options)
    if not jobs:
        empty_payload = {
            "job_rows": [],
            "requirements_rows": [],
            "skills_rows": [],
            "signals_rows": [],
            "model_rows": [],
            "dictionary_rows": [],
            "counts": {
                "jobListings": 0,
                "jobRequirements": 0,
                "jobSkills": 0,
                "jobUserSignals": 0,
                "jobModelDataset": 0,
            },
        }
        empty_payload["dictionary_rows"] = build_dictionary_rows(empty_payload)
        return empty_payload

    job_ids = [str(row["job_id"]) for row in jobs]
    requirements = fetch_requirements(connection, job_ids=job_ids)
    skills = fetch_skills(connection, job_ids=job_ids)
    signals = fetch_signals(
        connection,
        job_ids=job_ids,
        include_ai_signals=options.include_ai_signals,
        include_user_signals=options.include_user_signals,
    )
    requirements_by_job = group_rows(requirements, "job_id")
    skills_by_job = group_rows(skills, "job_id")
    signals_by_job = {row["job_id"]: row for row in signals}

    job_rows: list[dict[str, Any]] = []
    requirements_rows: list[dict[str, Any]] = []
    skills_rows: list[dict[str, Any]] = []
    signals_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []

    for base in jobs:
        job_id = str(base["job_id"])
        req_rows = requirements_by_job.get(job_id, [])
        skill_rows = skills_by_job.get(job_id, [])
        signal = default_signal_row(job_id)
        signal.update(signals_by_job.get(job_id, {}))
        aggregates = build_aggregates(
            base=base,
            requirements=req_rows,
            skills=skill_rows,
            signal=signal,
            settings=settings,
        )
        job_row = build_job_listing_row(
            base=base,
            aggregates=aggregates,
            signal=signal,
            exported_at=exported_at,
        )
        job_rows.append(job_row)
        requirements_rows.extend(build_requirement_rows(base=base, requirements=req_rows))
        skills_rows.extend(build_skill_rows(base=base, skills=skill_rows))
        signals_rows.append(build_signal_row(base=base, signal=signal))
        if options.include_model_dataset:
            model_rows.append(
                build_model_row(
                    base=base,
                    aggregates=aggregates,
                    signal=signal,
                    exported_at=exported_at,
                )
            )

    payload = {
        "job_rows": align_rows(job_rows, JOB_LISTINGS_COLUMNS),
        "requirements_rows": align_rows(requirements_rows, JOB_REQUIREMENTS_COLUMNS),
        "skills_rows": align_rows(skills_rows, JOB_SKILLS_COLUMNS),
        "signals_rows": align_rows(signals_rows, JOB_USER_SIGNALS_COLUMNS),
        "model_rows": align_rows(model_rows, MODEL_COLUMNS),
        "counts": {
            "jobListings": len(job_rows),
            "jobRequirements": len(requirements_rows),
            "jobSkills": len(skills_rows),
            "jobUserSignals": len(signals_rows),
            "jobModelDataset": len(model_rows),
        },
    }
    payload["dictionary_rows"] = build_dictionary_rows(payload)
    return payload


def fetch_jobs(connection: Connection, *, options: DatasetExportOptions) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if options.source != "all":
        conditions.append("sp.slug = :source_slug")
        params["source_slug"] = options.source
    if options.status != "all":
        mapping = {
            "active": "ACTIVE",
            "stale": "STALE",
            "expired": "EXPIRED",
        }
        conditions.append("jl.status = :status")
        params["status"] = mapping[options.status]
    if options.updated_since_utc is not None:
        conditions.append("jl.updated_at >= :updated_since")
        params["updated_since"] = options.updated_since_utc
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_clause = "LIMIT :limit" if options.limit is not None else ""
    if options.limit is not None:
        params["limit"] = options.limit
    query = text(
        f"""
        SELECT
          jl.id AS job_id,
          jl.source_platform_id,
          sp.slug AS source_platform_slug,
          sp.name AS source_platform_name,
          sp.base_url AS source_platform_base_url,
          sp.is_active AS source_platform_is_active,
          jl.company_id,
          c.name AS company_name,
          c.slug AS company_slug,
          c.logo_url AS company_logo_url,
          c.website_url AS company_website_url,
          jl.ingestion_run_id,
          jl.external_job_id,
          jl.title,
          jl.normalized_title,
          jl.category,
          jl.description,
          jl.requirement_summary,
          jl.work_type,
          jl.employment_type,
          jl.experience_level,
          jl.location_display,
          jl.province,
          jl.city,
          jl.salary_min,
          jl.salary_max,
          jl.salary_currency,
          jl.salary_period,
          jl.salary_display,
          jl.source_url,
          jl.external_apply_url,
          jl.source_posted_at,
          jl.source_updated_at,
          jl.last_seen_at,
          jl.expired_at,
          jl.status,
          jl.created_at,
          jl.updated_at
        FROM job_listings jl
        JOIN source_platforms sp ON sp.id = jl.source_platform_id
        JOIN companies c ON c.id = jl.company_id
        {where_clause}
        ORDER BY jl.updated_at DESC, jl.id ASC
        {limit_clause}
        """
    )
    rows = connection.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def fetch_requirements(connection: Connection, *, job_ids: list[str]) -> list[dict[str, Any]]:
    if not job_ids:
        return []
    clause, params = build_in_clause(job_ids, prefix="job_id")
    query = text(
        f"""
        SELECT
          jr.job_listing_id AS job_id,
          jr.id AS requirement_id,
          jr.type AS requirement_type,
          jr.value AS requirement_value,
          jr.priority AS requirement_priority,
          jr.sort_order AS requirement_sort_order,
          jr.created_at AS requirement_created_at
        FROM job_requirements jr
        WHERE jr.job_listing_id IN ({clause})
        ORDER BY jr.job_listing_id ASC, jr.sort_order ASC, jr.created_at ASC, jr.id ASC
        """
    )
    rows = connection.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def fetch_skills(connection: Connection, *, job_ids: list[str]) -> list[dict[str, Any]]:
    if not job_ids:
        return []
    clause, params = build_in_clause(job_ids, prefix="job_id")
    query = text(
        f"""
        SELECT
          js.job_listing_id AS job_id,
          js.id AS job_skill_id,
          js.skill_id,
          s.name AS skill_name,
          s.slug AS skill_slug,
          s.category AS skill_category,
          js.confidence AS skill_confidence,
          js.created_at AS job_skill_created_at
        FROM job_skills js
        JOIN skills s ON s.id = js.skill_id
        WHERE js.job_listing_id IN ({clause})
        ORDER BY js.job_listing_id ASC, js.created_at ASC, js.id ASC
        """
    )
    rows = connection.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def fetch_signals(
    connection: Connection,
    *,
    job_ids: list[str],
    include_ai_signals: bool,
    include_user_signals: bool,
) -> list[dict[str, Any]]:
    if not job_ids:
        return []
    base = {job_id: default_signal_row(job_id) for job_id in job_ids}
    clause, params = build_in_clause(job_ids, prefix="job_id")

    if include_user_signals:
        bookmark_rows = connection.execute(
            text(
                f"""
                SELECT
                  job_listing_id AS job_id,
                  COUNT(*) AS total,
                  MAX(created_at) AS latest_created_at
                FROM bookmarks
                WHERE job_listing_id IN ({clause})
                GROUP BY job_listing_id
                """
            ),
            params,
        ).mappings()
        for row in bookmark_rows:
            signal = base[str(row["job_id"])]
            signal["bookmark_count_total"] = int(row["total"] or 0)
            signal["bookmark_last_created_at"] = iso_utc(row["latest_created_at"])

        app_rows = connection.execute(
            text(
                f"""
                SELECT
                  job_listing_id AS job_id,
                  COUNT(*) AS total,
                  SUM(CASE WHEN status = 'APPLIED' THEN 1 ELSE 0 END) AS applied_count,
                  SUM(CASE WHEN status = 'INTERVIEW' THEN 1 ELSE 0 END) AS interview_count,
                  SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
                  SUM(CASE WHEN status = 'ACCEPTED' THEN 1 ELSE 0 END) AS accepted_count,
                  MAX(applied_at) AS latest_applied_at,
                  MAX(updated_at) AS latest_updated_at
                FROM application_records
                WHERE job_listing_id IN ({clause})
                GROUP BY job_listing_id
                """
            ),
            params,
        ).mappings()
        for row in app_rows:
            signal = base[str(row["job_id"])]
            signal["application_count_total"] = int(row["total"] or 0)
            signal["application_count_applied"] = int(row["applied_count"] or 0)
            signal["application_count_interview"] = int(row["interview_count"] or 0)
            signal["application_count_rejected"] = int(row["rejected_count"] or 0)
            signal["application_count_accepted"] = int(row["accepted_count"] or 0)
            signal["application_last_applied_at"] = iso_utc(row["latest_applied_at"])
            signal["application_last_updated_at"] = iso_utc(row["latest_updated_at"])

        latest_app_rows = connection.execute(
            text(
                f"""
                SELECT ar.job_listing_id AS job_id, ar.status AS last_status, ar.updated_at
                FROM application_records ar
                JOIN (
                  SELECT job_listing_id, MAX(updated_at) AS latest_updated_at
                  FROM application_records
                  WHERE job_listing_id IN ({clause})
                  GROUP BY job_listing_id
                ) last_row
                  ON last_row.job_listing_id = ar.job_listing_id
                 AND last_row.latest_updated_at = ar.updated_at
                """
            ),
            params,
        ).mappings()
        for row in latest_app_rows:
            signal = base[str(row["job_id"])]
            signal["application_last_status"] = normalize_enum(row["last_status"])

    if include_ai_signals:
        fit_rows = connection.execute(
            text(
                f"""
                SELECT
                  job_listing_id AS job_id,
                  COUNT(*) AS total,
                  MAX(analyzed_at) AS latest_analyzed_at
                FROM fit_score_results
                WHERE job_listing_id IN ({clause})
                GROUP BY job_listing_id
                """
            ),
            params,
        ).mappings()
        for row in fit_rows:
            signal = base[str(row["job_id"])]
            signal["fit_score_run_count"] = int(row["total"] or 0)
            signal["fit_score_latest_analyzed_at"] = iso_utc(row["latest_analyzed_at"])
        fit_latest_rows = connection.execute(
            text(
                f"""
                SELECT fsr.job_listing_id AS job_id, fsr.fit_score, fsr.readiness_level,
                       fsr.recommendation_decision, fsr.model_name
                FROM fit_score_results fsr
                JOIN (
                  SELECT job_listing_id, MAX(analyzed_at) AS latest_analyzed_at
                  FROM fit_score_results
                  WHERE job_listing_id IN ({clause})
                  GROUP BY job_listing_id
                ) last_row
                  ON last_row.job_listing_id = fsr.job_listing_id
                 AND last_row.latest_analyzed_at = fsr.analyzed_at
                """
            ),
            params,
        ).mappings()
        for row in fit_latest_rows:
            signal = base[str(row["job_id"])]
            signal["fit_score_latest"] = int(row["fit_score"] or 0)
            signal["fit_score_latest_readiness_level"] = safe_text(row["readiness_level"])
            signal["fit_score_latest_decision"] = safe_text(row["recommendation_decision"])
            signal["fit_score_latest_model_name"] = safe_text(row["model_name"])

        gap_rows = connection.execute(
            text(
                f"""
                SELECT
                  job_listing_id AS job_id,
                  COUNT(*) AS total,
                  MAX(analyzed_at) AS latest_analyzed_at
                FROM skill_gap_results
                WHERE job_listing_id IN ({clause})
                GROUP BY job_listing_id
                """
            ),
            params,
        ).mappings()
        for row in gap_rows:
            signal = base[str(row["job_id"])]
            signal["skill_gap_run_count"] = int(row["total"] or 0)
            signal["skill_gap_latest_analyzed_at"] = iso_utc(row["latest_analyzed_at"])
        gap_latest_rows = connection.execute(
            text(
                f"""
                SELECT sgr.job_listing_id AS job_id, sgr.gaps, sgr.model_name
                FROM skill_gap_results sgr
                JOIN (
                  SELECT job_listing_id, MAX(analyzed_at) AS latest_analyzed_at
                  FROM skill_gap_results
                  WHERE job_listing_id IN ({clause})
                  GROUP BY job_listing_id
                ) last_row
                  ON last_row.job_listing_id = sgr.job_listing_id
                 AND last_row.latest_analyzed_at = sgr.analyzed_at
                """
            ),
            params,
        ).mappings()
        for row in gap_latest_rows:
            signal = base[str(row["job_id"])]
            signal["skill_gap_latest_gap_count"] = estimate_gap_count(row.get("gaps"))
            signal["skill_gap_latest_model_name"] = safe_text(row.get("model_name"))

        cv_rows = connection.execute(
            text(
                f"""
                SELECT
                  job_listing_id AS job_id,
                  COUNT(*) AS total,
                  MAX(analyzed_at) AS latest_analyzed_at
                FROM cv_analysis_results
                WHERE job_listing_id IN ({clause})
                GROUP BY job_listing_id
                """
            ),
            params,
        ).mappings()
        for row in cv_rows:
            signal = base[str(row["job_id"])]
            signal["cv_analysis_run_count"] = int(row["total"] or 0)
            signal["cv_analysis_latest_analyzed_at"] = iso_utc(row["latest_analyzed_at"])
        cv_latest_rows = connection.execute(
            text(
                f"""
                SELECT car.job_listing_id AS job_id, car.language, car.input_mode,
                       car.compare_source, car.model_name
                FROM cv_analysis_results car
                JOIN (
                  SELECT job_listing_id, MAX(analyzed_at) AS latest_analyzed_at
                  FROM cv_analysis_results
                  WHERE job_listing_id IN ({clause})
                  GROUP BY job_listing_id
                ) last_row
                  ON last_row.job_listing_id = car.job_listing_id
                 AND last_row.latest_analyzed_at = car.analyzed_at
                """
            ),
            params,
        ).mappings()
        for row in cv_latest_rows:
            signal = base[str(row["job_id"])]
            signal["cv_analysis_latest_language"] = normalize_enum(row["language"])
            signal["cv_analysis_latest_input_mode"] = normalize_enum(row["input_mode"])
            signal["cv_analysis_latest_compare_source"] = normalize_enum(row["compare_source"])
            signal["cv_analysis_latest_model_name"] = safe_text(row["model_name"])

    ai_log_rows = connection.execute(
        text(
            """
            SELECT
              id, kind, status, model_name, error_code, created_at, input_summary, output_summary
            FROM ai_request_logs
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings()
    ai_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_set = set(job_ids)
    for row in ai_log_rows:
        job_id = extract_job_id_from_ai_log(row)
        if job_id and job_id in target_set:
            ai_by_job[job_id].append(dict(row))
    for job_id, rows in ai_by_job.items():
        signal = base[job_id]
        signal["ai_request_count_total"] = len(rows)
        signal["ai_request_count_succeeded"] = sum(
            1 for item in rows if normalize_enum(item.get("status")) == "SUCCEEDED"
        )
        signal["ai_request_count_failed"] = sum(
            1 for item in rows if normalize_enum(item.get("status")) == "FAILED"
        )
        latest = rows[-1]
        signal["ai_request_latest_kind"] = normalize_enum(latest.get("kind"))
        signal["ai_request_latest_status"] = normalize_enum(latest.get("status"))
        signal["ai_request_latest_model_name"] = safe_text(latest.get("model_name"))
        signal["ai_request_latest_created_at"] = iso_utc(latest.get("created_at"))
        error_counter = Counter(
            safe_text(item.get("error_code")) for item in rows if item.get("error_code")
        )
        signal["ai_request_error_code_top"] = (
            error_counter.most_common(1)[0][0] if error_counter else ""
        )

    return [base[job_id] for job_id in job_ids]


def extract_job_id_from_ai_log(row: dict[str, Any]) -> str | None:
    candidates: list[Any] = []
    candidates.extend(extract_json_candidates(row.get("input_summary")))
    candidates.extend(extract_json_candidates(row.get("output_summary")))
    for value in candidates:
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return None


def extract_json_candidates(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        results: list[Any] = []
        for key, value in payload.items():
            if TRACKING_KEY_PATTERN.search(str(key)):
                continue
            if str(key) in {"jobId", "job_id", "jobListingId", "job_listing_id"}:
                results.append(value)
            if isinstance(value, dict):
                results.extend(extract_json_candidates(value))
        return results
    return []


def default_signal_row(job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "bookmark_count_total": 0,
        "bookmark_last_created_at": "",
        "application_count_total": 0,
        "application_count_applied": 0,
        "application_count_interview": 0,
        "application_count_rejected": 0,
        "application_count_accepted": 0,
        "application_last_status": "",
        "application_last_applied_at": "",
        "application_last_updated_at": "",
        "fit_score_run_count": 0,
        "fit_score_latest": "",
        "fit_score_latest_readiness_level": "",
        "fit_score_latest_decision": "",
        "fit_score_latest_model_name": "",
        "fit_score_latest_analyzed_at": "",
        "skill_gap_run_count": 0,
        "skill_gap_latest_gap_count": "",
        "skill_gap_latest_model_name": "",
        "skill_gap_latest_analyzed_at": "",
        "cv_analysis_run_count": 0,
        "cv_analysis_latest_language": "",
        "cv_analysis_latest_input_mode": "",
        "cv_analysis_latest_compare_source": "",
        "cv_analysis_latest_model_name": "",
        "cv_analysis_latest_analyzed_at": "",
        "ai_request_count_total": 0,
        "ai_request_count_succeeded": 0,
        "ai_request_count_failed": 0,
        "ai_request_latest_kind": "",
        "ai_request_latest_status": "",
        "ai_request_latest_model_name": "",
        "ai_request_latest_created_at": "",
        "ai_request_error_code_top": "",
    }


def estimate_gap_count(gaps: Any) -> int:
    if gaps is None:
        return 0
    if isinstance(gaps, str):
        try:
            gaps = json.loads(gaps)
        except json.JSONDecodeError:
            return 0
    if isinstance(gaps, list):
        return len(gaps)
    if isinstance(gaps, dict):
        if isinstance(gaps.get("gaps"), list):
            return len(gaps["gaps"])
        return len(gaps)
    return 0


def build_aggregates(
    *,
    base: dict[str, Any],
    requirements: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    signal: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    description = safe_text(base.get("description"))
    requirement_summary = safe_text(base.get("requirement_summary"))
    title = safe_text(base.get("title"))
    company_name = safe_text(base.get("company_name"))
    category = safe_text(base.get("category"))
    location_display = safe_text(base.get("location_display"))
    salary_min = to_optional_int(base.get("salary_min"))
    salary_max = to_optional_int(base.get("salary_max"))

    paragraph_count = count_paragraphs(description)
    has_safe_html, has_unsafe_html = html_safety(description, requirement_summary)
    language_signal = infer_language(description, requirement_summary)

    req_counts = Counter(normalize_enum(row.get("requirement_type")) for row in requirements)
    req_priority_counts = Counter(
        normalize_enum(row.get("requirement_priority")) for row in requirements
    )
    req_sorted = sorted(
        requirements,
        key=lambda row: (
            int(row.get("requirement_sort_order") or 0),
            iso_sort_key(row.get("requirement_created_at")),
            safe_text(row.get("requirement_id")),
        ),
    )
    req_values = [
        safe_text(row.get("requirement_value"))
        for row in req_sorted
        if safe_text(row.get("requirement_value"))
    ]

    confidence_values = [to_optional_float(item.get("skill_confidence")) for item in skills]
    confidence_clean = [value for value in confidence_values if value is not None]
    skill_slugs = [
        safe_text(item.get("skill_slug")).lower()
        for item in skills
        if safe_text(item.get("skill_slug"))
    ]
    skill_names = [
        safe_text(item.get("skill_name")) for item in skills if safe_text(item.get("skill_name"))
    ]
    skill_categories = [
        safe_text(item.get("skill_category"))
        for item in skills
        if safe_text(item.get("skill_category"))
    ]

    top_names = [name for name, _ in Counter(skill_names).most_common(10)]
    top_slugs = [slug for slug, _ in Counter(skill_slugs).most_common(10)]

    detail_fields = [
        title,
        description,
        requirement_summary,
        safe_text(base.get("work_type")),
        safe_text(base.get("employment_type")),
        safe_text(base.get("experience_level")),
        location_display,
        safe_text(base.get("salary_display")),
        safe_text(base.get("source_url")),
        safe_text(base.get("external_apply_url")),
    ]
    detail_readiness_score = round(
        (sum(1 for item in detail_fields if item) / len(detail_fields)) * 100
    )

    last_seen_at = parse_dt(base.get("last_seen_at"))
    stale_threshold = datetime.now(UTC) - timedelta(hours=settings.freshness_stale_after_hours)
    is_stale = normalize_enum(base.get("status")) in {"STALE", "EXPIRED", "CLOSED", "HIDDEN"} or (
        last_seen_at is not None and last_seen_at < stale_threshold
    )

    has_salary_range = (
        salary_min is not None and salary_max is not None and salary_max >= salary_min
    )
    salary_midpoint: int | None = None
    salary_range_width: int | None = None
    if has_salary_range:
        salary_midpoint = int((salary_min + salary_max) / 2)
        salary_range_width = int(salary_max - salary_min)
    elif salary_min is not None:
        salary_midpoint = salary_min
    elif salary_max is not None:
        salary_midpoint = salary_max

    province = safe_text(base.get("province")).lower().strip()
    city = safe_text(base.get("city")).lower().strip()
    location_key = f"{province}|{city}" if (province or city) else ""

    completeness_inputs = [
        title,
        safe_text(base.get("normalized_title")),
        category,
        description,
        requirement_summary,
        safe_text(base.get("work_type")),
        safe_text(base.get("employment_type")),
        safe_text(base.get("experience_level")),
        location_display,
        safe_text(base.get("source_url")),
        safe_text(base.get("status")),
    ]
    normalization_completeness_score = round(
        (sum(1 for item in completeness_inputs if item) / len(completeness_inputs)) * 100
    )

    fit_input_quality_score = round(
        (
            0.5 * bool(req_values)
            + 0.4 * bool(skill_slugs)
            + 0.1 * bool(safe_text(base.get("experience_level")))
        )
        * 100
    )
    coverage_score = round(((bool(req_values) + bool(skill_slugs)) / 2) * 100)
    ratio = round((len(req_values) / len(skill_slugs)), 3) if skill_slugs else ""

    tracker_signal_available = (
        signal["bookmark_count_total"] > 0
        or signal["application_count_total"] > 0
        or signal["fit_score_run_count"] > 0
        or signal["skill_gap_run_count"] > 0
        or signal["cv_analysis_run_count"] > 0
    )
    if signal["application_count_accepted"] > 0:
        tracker_state = "accepted"
    elif signal["application_count_interview"] > 0:
        tracker_state = "interview"
    elif signal["application_count_rejected"] > 0:
        tracker_state = "rejected"
    elif signal["application_count_applied"] > 0:
        tracker_state = "applied"
    elif signal["bookmark_count_total"] > 0:
        tracker_state = "bookmarked"
    else:
        tracker_state = "none"

    return {
        "is_stale": is_stale,
        "has_salary_range": has_salary_range,
        "salary_midpoint": salary_midpoint,
        "salary_range_width": salary_range_width,
        "location_key": location_key,
        "search_blob_preview": " | ".join(
            part for part in [title, company_name, category, location_display] if part
        ),
        "detail_readiness_score": detail_readiness_score,
        "description_length_chars": len(description),
        "description_paragraph_count": paragraph_count,
        "requirement_summary_length_chars": len(requirement_summary),
        "requirement_summary_has_prefix_legacy": bool(
            REQUIREMENT_SUMMARY_PREFIX_PATTERN.search(requirement_summary)
        ),
        "has_safe_display_html": has_safe_html,
        "has_unsafe_html_signal": has_unsafe_html,
        "language_signal": language_signal,
        "is_mixed_language_signal": language_signal == "MIXED",
        "normalization_completeness_score": normalization_completeness_score,
        "requirements_count_total": len(requirements),
        "requirements_count_skill": req_counts.get("SKILL", 0),
        "requirements_count_experience": req_counts.get("EXPERIENCE", 0),
        "requirements_count_education": req_counts.get("EDUCATION", 0),
        "requirements_count_responsibility": req_counts.get("RESPONSIBILITY", 0),
        "requirements_count_other": req_counts.get("OTHER", 0),
        "requirements_priority_high_count": req_priority_counts.get("HIGH", 0),
        "requirements_priority_medium_count": req_priority_counts.get("MEDIUM", 0),
        "requirements_priority_low_count": req_priority_counts.get("LOW", 0),
        "requirements_first_value": req_values[0] if req_values else "",
        "requirements_concat": " || ".join(req_values),
        "skills_count_total": len(skills),
        "skills_unique_slug_count": len(set(skill_slugs)),
        "skills_confidence_avg": round(sum(confidence_clean) / len(confidence_clean), 4)
        if confidence_clean
        else "",
        "skills_confidence_min": round(min(confidence_clean), 4) if confidence_clean else "",
        "skills_confidence_max": round(max(confidence_clean), 4) if confidence_clean else "",
        "skills_top_10_names": " | ".join(top_names),
        "skills_top_10_slugs": " | ".join(top_slugs),
        "skills_categories_concat": " | ".join(sorted(set(skill_categories))),
        "filter_keyword_ready": bool(title or safe_text(base.get("normalized_title"))),
        "filter_location_ready": bool(location_display or province or city),
        "filter_work_type_ready": bool(safe_text(base.get("work_type"))),
        "filter_employment_type_ready": bool(safe_text(base.get("employment_type"))),
        "filter_experience_ready": bool(safe_text(base.get("experience_level"))),
        "filter_salary_ready": bool(
            salary_min is not None
            or salary_max is not None
            or safe_text(base.get("salary_display"))
        ),
        "filter_category_ready": bool(category),
        "fit_input_has_requirements": bool(req_values),
        "fit_input_has_skills": bool(skill_slugs),
        "fit_input_has_experience_signal": bool(safe_text(base.get("experience_level"))),
        "fit_input_quality_score": fit_input_quality_score,
        "skill_gap_input_coverage_score": coverage_score,
        "skill_gap_requirements_vs_skills_ratio": ratio,
        "tracker_signal_available": tracker_signal_available,
        "tracker_conversion_state": tracker_state,
        "skill_names": skill_names,
        "skill_slugs": skill_slugs,
        "skill_categories": skill_categories,
        "requirements_values": req_values,
        "requirements_rows": req_sorted,
    }


def build_job_listing_row(
    *,
    base: dict[str, Any],
    aggregates: dict[str, Any],
    signal: dict[str, Any],
    exported_at: datetime,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "job_id": safe_text(base.get("job_id")),
        "source_platform_id": safe_text(base.get("source_platform_id")),
        "source_platform_slug": safe_text(base.get("source_platform_slug")),
        "source_platform_name": safe_text(base.get("source_platform_name")),
        "source_platform_base_url": safe_text(base.get("source_platform_base_url")),
        "source_platform_is_active": bool_to_int(base.get("source_platform_is_active")),
        "company_id": safe_text(base.get("company_id")),
        "company_name": safe_text(base.get("company_name")),
        "company_slug": safe_text(base.get("company_slug")),
        "company_logo_url": safe_text(base.get("company_logo_url")),
        "company_website_url": safe_text(base.get("company_website_url")),
        "ingestion_run_id": safe_text(base.get("ingestion_run_id")),
        "external_job_id": safe_text(base.get("external_job_id")),
        "dataset_exported_at": iso_utc(exported_at),
        "dataset_version": DATASET_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "title": safe_text(base.get("title")),
        "normalized_title": safe_text(base.get("normalized_title")),
        "category": safe_text(base.get("category")),
        "description": safe_text(base.get("description")),
        "requirement_summary": safe_text(base.get("requirement_summary")),
        "work_type": normalize_enum(base.get("work_type")),
        "employment_type": normalize_enum(base.get("employment_type")),
        "experience_level": normalize_enum(base.get("experience_level")),
        "location_display": safe_text(base.get("location_display")),
        "province": safe_text(base.get("province")),
        "city": safe_text(base.get("city")),
        "salary_min": to_optional_int(base.get("salary_min")) or "",
        "salary_max": to_optional_int(base.get("salary_max")) or "",
        "salary_currency": safe_text(base.get("salary_currency")),
        "salary_period": normalize_enum(base.get("salary_period")),
        "salary_display": safe_text(base.get("salary_display")),
        "source_url": safe_text(base.get("source_url")),
        "external_apply_url": safe_text(base.get("external_apply_url")),
        "source_posted_at": iso_utc(base.get("source_posted_at")),
        "source_updated_at": iso_utc(base.get("source_updated_at")),
        "last_seen_at": iso_utc(base.get("last_seen_at")),
        "expired_at": iso_utc(base.get("expired_at")),
        "status": normalize_enum(base.get("status")),
        "created_at": iso_utc(base.get("created_at")),
        "updated_at": iso_utc(base.get("updated_at")),
    }
    row.update(
        {
            key: normalize_csv_value(value)
            for key, value in aggregates.items()
            if key in JOB_LISTINGS_COLUMNS
        }
    )
    row.update(
        {
            key: normalize_csv_value(signal.get(key, ""))
            for key in JOB_LISTINGS_COLUMNS
            if key.startswith(
                (
                    "bookmark_",
                    "application_",
                    "fit_score_",
                    "skill_gap_",
                    "cv_analysis_",
                    "ai_request_",
                )
            )
        }
    )
    row["dataset_row_hash"] = stable_row_hash(row, JOB_LISTINGS_COLUMNS)
    return row


def build_requirement_rows(
    *,
    base: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in requirements:
        rows.append(
            {
                "job_id": safe_text(base.get("job_id")),
                "requirement_id": safe_text(item.get("requirement_id")),
                "requirement_type": normalize_enum(item.get("requirement_type")),
                "requirement_value": safe_text(item.get("requirement_value")),
                "requirement_priority": normalize_enum(item.get("requirement_priority")),
                "requirement_sort_order": int(item.get("requirement_sort_order") or 0),
                "requirement_created_at": iso_utc(item.get("requirement_created_at")),
                "source_platform_slug": safe_text(base.get("source_platform_slug")),
                "company_name": safe_text(base.get("company_name")),
                "job_title": safe_text(base.get("title")),
                "job_status": normalize_enum(base.get("status")),
                "job_last_seen_at": iso_utc(base.get("last_seen_at")),
            }
        )
    return rows


def build_skill_rows(
    *,
    base: dict[str, Any],
    skills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in skills:
        rows.append(
            {
                "job_id": safe_text(base.get("job_id")),
                "job_skill_id": safe_text(item.get("job_skill_id")),
                "skill_id": safe_text(item.get("skill_id")),
                "skill_name": safe_text(item.get("skill_name")),
                "skill_slug": safe_text(item.get("skill_slug")),
                "skill_category": safe_text(item.get("skill_category")),
                "skill_confidence": to_optional_float(item.get("skill_confidence")) or "",
                "job_skill_created_at": iso_utc(item.get("job_skill_created_at")),
                "source_platform_slug": safe_text(base.get("source_platform_slug")),
                "company_name": safe_text(base.get("company_name")),
                "job_title": safe_text(base.get("title")),
                "job_status": normalize_enum(base.get("status")),
                "job_last_seen_at": iso_utc(base.get("last_seen_at")),
            }
        )
    return rows


def build_signal_row(*, base: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    row = {
        "job_id": safe_text(base.get("job_id")),
        "source_platform_slug": safe_text(base.get("source_platform_slug")),
        "job_title": safe_text(base.get("title")),
        "company_name": safe_text(base.get("company_name")),
        "job_status": normalize_enum(base.get("status")),
    }
    for key in JOB_USER_SIGNALS_COLUMNS:
        if key in row:
            continue
        row[key] = normalize_csv_value(signal.get(key, ""))
    return row


def build_model_row(
    *,
    base: dict[str, Any],
    aggregates: dict[str, Any],
    signal: dict[str, Any],
    exported_at: datetime,
) -> dict[str, Any]:
    status = normalize_enum(base.get("status"))
    description = safe_text(base.get("description"))
    requirement_summary = safe_text(base.get("requirement_summary"))
    req_values = list(aggregates["requirements_values"])
    skill_names = list(aggregates["skill_names"])
    skill_slugs = list(aggregates["skill_slugs"])
    skill_categories = list(aggregates["skill_categories"])
    requirements_rows = list(aggregates["requirements_rows"])
    location_context = " | ".join(
        part
        for part in [
            safe_text(base.get("location_display")),
            safe_text(base.get("province")),
            safe_text(base.get("city")),
        ]
        if part
    )
    salary_context = " | ".join(
        part
        for part in [
            safe_text(base.get("salary_display")),
            str(to_optional_int(base.get("salary_min")) or ""),
            str(to_optional_int(base.get("salary_max")) or ""),
            safe_text(base.get("salary_currency")),
            normalize_enum(base.get("salary_period")),
        ]
        if part
    )
    required_skills = [
        row["requirement_value"]
        for row in requirements_rows
        if normalize_enum(row.get("requirement_type")) == "SKILL"
    ]
    optional_skills = [value for value in skill_names if value not in required_skills]
    requirements_json = [
        {
            "type": normalize_enum(row.get("requirement_type")),
            "value": safe_text(row.get("requirement_value")),
            "priority": normalize_enum(row.get("requirement_priority")),
            "sort_order": int(row.get("requirement_sort_order") or 0),
        }
        for row in requirements_rows
    ]
    skills_json = [
        {
            "name": safe_text(item.get("skill_name")),
            "slug": safe_text(item.get("skill_slug")),
            "category": safe_text(item.get("skill_category")),
            "confidence": to_optional_float(item.get("skill_confidence")),
        }
        for item in skills_from_aggregates(
            requirements_rows, skill_names, skill_slugs, skill_categories
        )
    ]
    full_context_parts = [
        safe_text(base.get("title")),
        safe_text(base.get("normalized_title")),
        safe_text(base.get("company_name")),
        safe_text(base.get("category")),
        location_context,
        salary_context,
        strip_html(description),
        strip_html(requirement_summary),
        " ; ".join(req_values),
        " ; ".join(skill_names),
    ]
    model_input_full_context = "\n".join(part for part in full_context_parts if part)
    short_context = " | ".join(
        part
        for part in [
            safe_text(base.get("title")),
            safe_text(base.get("company_name")),
            location_context,
        ]
        if part
    )
    model_split, split_group_key = split_assignment(base=base)
    readiness = model_task_readiness(aggregates=aggregates, description=description)
    blockers = model_task_blockers(readiness)

    completeness = int(aggregates["normalization_completeness_score"])
    weak_quality_tier = "A" if completeness >= 80 else "B" if completeness >= 55 else "C"
    weak_apply_priority = (
        "high"
        if not aggregates["is_stale"] and aggregates["fit_input_quality_score"] >= 70
        else "medium"
        if not aggregates["is_stale"]
        else "low"
    )
    row = {
        "job_id": safe_text(base.get("job_id")),
        "external_job_id": safe_text(base.get("external_job_id")),
        "source_platform_slug": safe_text(base.get("source_platform_slug")),
        "company_id": safe_text(base.get("company_id")),
        "company_name": safe_text(base.get("company_name")),
        "dataset_version": DATASET_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "dataset_exported_at": iso_utc(exported_at),
        "model_split": model_split,
        "split_group_key": split_group_key,
        "is_holdout_source": bool_to_int(
            safe_text(base.get("source_platform_slug")) == "kitalulus"
        ),
        "is_low_confidence_label": bool_to_int(completeness < 55),
        "label_confidence_score": round(min(max(completeness / 100, 0), 1), 4),
        "supported_model_tasks_json": to_json_string(list(TASKS_SUPPORTED)),
        "unsupported_model_tasks_json": to_json_string(list(TASKS_UNSUPPORTED)),
        "model_task_readiness_json": to_json_string(readiness),
        "model_task_blockers_json": to_json_string(blockers),
        "model_input_title": safe_text(base.get("title")),
        "model_input_normalized_title": safe_text(base.get("normalized_title")),
        "model_input_company_context": safe_text(base.get("company_name")),
        "model_input_location_context": location_context,
        "model_input_salary_context": salary_context,
        "model_input_description_plaintext": strip_html(description),
        "model_input_requirement_summary_plaintext": strip_html(requirement_summary),
        "model_input_requirements_text": " ; ".join(req_values),
        "model_input_skills_text": " ; ".join(skill_names),
        "model_input_full_context": model_input_full_context,
        "model_input_short_context": short_context,
        "model_input_cv_compare_context": " | ".join(
            part
            for part in [
                safe_text(base.get("title")),
                strip_html(requirement_summary),
                " ; ".join(req_values[:10]),
                " ; ".join(skill_names[:15]),
            ]
            if part
        ),
        "model_input_career_copilot_context": " | ".join(
            part
            for part in [
                safe_text(base.get("title")),
                safe_text(base.get("company_name")),
                safe_text(base.get("category")),
                "Important requirements: " + " ; ".join(req_values[:8]) if req_values else "",
                "Keywords: " + " ; ".join(skill_names[:12]) if skill_names else "",
            ]
            if part
        ),
        "label_work_type": normalize_enum(base.get("work_type")),
        "label_employment_type": normalize_enum(base.get("employment_type")),
        "label_experience_level": normalize_enum(base.get("experience_level")),
        "label_category": safe_text(base.get("category")),
        "label_role_family": role_family(
            safe_text(base.get("normalized_title")) or safe_text(base.get("title"))
        ),
        "label_seniority_bucket": seniority_bucket(normalize_enum(base.get("experience_level"))),
        "label_salary_bucket": salary_bucket(
            to_optional_int(base.get("salary_min")), to_optional_int(base.get("salary_max"))
        ),
        "label_location_city": safe_text(base.get("city")),
        "label_location_province": safe_text(base.get("province")),
        "label_is_remote_friendly": bool_to_int(normalize_enum(base.get("work_type")) == "REMOTE"),
        "label_is_entry_level_friendly": bool_to_int(
            normalize_enum(base.get("experience_level")) in {"ENTRY_LEVEL", "JUNIOR"}
        ),
        "label_is_tech_or_digital_role": bool_to_int(
            is_tech_role(safe_text(base.get("title")), skill_names)
        ),
        "label_job_search_rank_bucket": rank_bucket(aggregates=aggregates, signal=signal),
        "label_recommendation_candidate_tier": recommendation_tier(aggregates=aggregates),
        "skills_json": to_json_string(skills_json),
        "skill_slugs_json": to_json_string(skill_slugs),
        "skill_names_json": to_json_string(skill_names),
        "skill_categories_json": to_json_string(sorted(set(skill_categories))),
        "skill_count": len(skill_names),
        "skill_confidence_avg": aggregates["skills_confidence_avg"],
        "skill_source_quality": "explicit" if skill_names else "fallback",
        "primary_skill_slug": skill_slugs[0] if skill_slugs else "",
        "primary_skill_category": skill_categories[0] if skill_categories else "",
        "required_skill_keywords_json": to_json_string(required_skills),
        "optional_skill_keywords_json": to_json_string(optional_skills),
        "skill_embedding_text": " ; ".join(skill_names),
        "requirements_json": to_json_string(requirements_json),
        "requirements_skill_json": to_json_string(
            [row for row in requirements_json if row["type"] == "SKILL"]
        ),
        "requirements_experience_json": to_json_string(
            [row for row in requirements_json if row["type"] == "EXPERIENCE"]
        ),
        "requirements_education_json": to_json_string(
            [row for row in requirements_json if row["type"] == "EDUCATION"]
        ),
        "requirements_responsibility_json": to_json_string(
            [row for row in requirements_json if row["type"] == "RESPONSIBILITY"]
        ),
        "requirements_other_json": to_json_string(
            [row for row in requirements_json if row["type"] == "OTHER"]
        ),
        "requirements_count_total": len(requirements_json),
        "requirements_type_distribution_json": to_json_string(
            requirement_distribution(requirements_json)
        ),
        "requirements_priority_distribution_json": to_json_string(
            requirement_priority_distribution(requirements_json)
        ),
        "requirement_classification_quality_score": classify_requirement_quality(requirements_json),
        "requirement_keywords_json": to_json_string(req_values[:40]),
        "ats_keywords_json": to_json_string(sorted(set(skill_names + required_skills))[:50]),
        "important_requirement_highlights_json": to_json_string(
            [row["value"] for row in requirements_json if row["priority"] == "HIGH"][:10]
        ),
        "fit_context_skills_required_json": to_json_string(required_skills),
        "fit_context_experience_requirements_json": to_json_string(
            [row["value"] for row in requirements_json if row["type"] == "EXPERIENCE"]
        ),
        "fit_context_education_requirements_json": to_json_string(
            [row["value"] for row in requirements_json if row["type"] == "EDUCATION"]
        ),
        "fit_context_responsibilities_json": to_json_string(
            [row["value"] for row in requirements_json if row["type"] == "RESPONSIBILITY"]
        ),
        "fit_context_preferences_json": to_json_string(
            {
                "work_type": normalize_enum(base.get("work_type")),
                "employment_type": normalize_enum(base.get("employment_type")),
                "location": safe_text(base.get("location_display")),
                "salary_display": safe_text(base.get("salary_display")),
                "experience_level": normalize_enum(base.get("experience_level")),
            }
        ),
        "skill_gap_target_skills_json": to_json_string(skill_slugs),
        "skill_gap_core_skills_json": to_json_string(required_skills[:20]),
        "skill_gap_optional_skills_json": to_json_string(optional_skills[:20]),
        "readiness_signal_level": weak_apply_priority,
        "candidate_matching_weight_json": to_json_string(
            {"skills": 0.45, "experience": 0.25, "preferences": 0.20, "freshness": 0.10}
        ),
        "job_fit_feature_vector_json": to_json_string(
            [aggregates["fit_input_quality_score"], len(required_skills), len(skill_names)]
        ),
        "preference_match_feature_vector_json": to_json_string(
            [
                bool_to_int(bool(safe_text(base.get("work_type")))),
                bool_to_int(bool(safe_text(base.get("location_display")))),
                bool_to_int(bool(safe_text(base.get("salary_display")))),
            ]
        ),
        "experience_match_feature_vector_json": to_json_string(
            [seniority_numeric(normalize_enum(base.get("experience_level"))), len(required_skills)]
        ),
        "skill_match_feature_vector_json": to_json_string(
            [len(skill_names), len(required_skills), aggregates["skills_unique_slug_count"]]
        ),
        "skill_gap_feature_vector_json": to_json_string(
            [
                aggregates["skill_gap_input_coverage_score"],
                len(required_skills),
                len(optional_skills),
            ]
        ),
        "weak_label_apply_priority": weak_apply_priority,
        "weak_label_job_quality_tier": weak_quality_tier,
        "weak_label_market_salary_signal": salary_signal(
            to_optional_int(base.get("salary_min")),
            to_optional_int(base.get("salary_max")),
        ),
        "weak_label_freshness_signal": "expired"
        if status in {"EXPIRED", "CLOSED", "HIDDEN"}
        else "stale"
        if aggregates["is_stale"]
        else "fresh",
        "weak_label_search_relevance_keywords_json": to_json_string(search_keywords(base)),
        "weak_label_role_keywords_json": to_json_string(
            role_keywords(safe_text(base.get("title")))
        ),
        "weak_label_readiness_level": weak_apply_priority,
        "weak_label_success_probability_bucket": success_bucket(weak_apply_priority, signal),
        "weak_label_actionable_next_steps_json": to_json_string(
            actionable_steps(weak_apply_priority)
        ),
        "text_quality_score": text_quality_score(
            description=description, requirement_summary=requirement_summary
        ),
        "normalization_completeness_score": aggregates["normalization_completeness_score"],
        "model_input_token_estimate": estimate_tokens(model_input_full_context),
        "has_minimum_model_context": bool_to_int(bool(model_input_full_context.strip())),
        "missing_model_context_fields_json": to_json_string(
            missing_context_fields(
                title=safe_text(base.get("title")),
                description=description,
                requirements=req_values,
                skills=skill_names,
            )
        ),
        "source_posted_at": iso_utc(base.get("source_posted_at")),
        "last_seen_at": iso_utc(base.get("last_seen_at")),
        "status": status,
        "ai_request_latest_model_name": safe_text(signal.get("ai_request_latest_model_name")),
        "ai_request_count_failed": int(signal.get("ai_request_count_failed") or 0),
        "xai_skill_evidence_json": to_json_string(skill_names[:15]),
        "xai_experience_evidence_json": to_json_string(
            [row["value"] for row in requirements_json if row["type"] == "EXPERIENCE"][:10]
        ),
        "xai_preference_evidence_json": to_json_string(
            [
                safe_text(base.get("work_type")),
                safe_text(base.get("location_display")),
                salary_context,
            ]
        ),
        "xai_requirement_evidence_json": to_json_string(req_values[:20]),
        "xai_salary_location_evidence_json": to_json_string([salary_context, location_context]),
        "evaluation_expected_outputs_json": to_json_string(
            {
                "job_fit_scoring": "score, readiness_level, explainable_breakdown",
                "skill_gap_analysis": "missing_skills, priority_levels, actionable_plan",
                "career_strategy_recommendation": "apply_priority, next_steps",
                "cv_analyzer_job_context": "keywords, experience_expectation, ats_hints",
            }
        ),
        "evaluation_rubric_json": to_json_string(
            {
                "job_fit_scoring": {"relevance": 0.4, "explainability": 0.3, "consistency": 0.3},
                "skill_gap_analysis": {"precision": 0.4, "coverage": 0.3, "actionability": 0.3},
                "career_strategy_recommendation": {"clarity": 0.4, "evidence": 0.3, "safety": 0.3},
                "cv_analyzer_job_context": {"signal_quality": 0.5, "completeness": 0.5},
            }
        ),
    }
    return align_row(row, MODEL_COLUMNS)


def split_assignment(*, base: dict[str, Any]) -> tuple[str, str]:
    group_key = "|".join(
        [
            safe_text(base.get("source_platform_slug")).lower(),
            safe_text(base.get("company_name")).strip().lower(),
            safe_text(base.get("normalized_title") or base.get("title")).strip().lower(),
        ]
    )
    score = int(hashlib.sha256(group_key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    if score < TRAIN_SPLIT:
        return "train", group_key
    if score < (TRAIN_SPLIT + VALIDATION_SPLIT):
        return "validation", group_key
    return "test", group_key


def model_task_readiness(*, aggregates: dict[str, Any], description: str) -> dict[str, float]:
    base_score = max(min(aggregates["normalization_completeness_score"] / 100, 1.0), 0.0)
    req = 1.0 if aggregates["requirements_count_total"] > 0 else 0.0
    skill = 1.0 if aggregates["skills_count_total"] > 0 else 0.0
    desc = 1.0 if bool(description.strip()) else 0.0
    return {
        "job_search_ranking": round((0.4 * base_score) + (0.3 * desc) + (0.3 * skill), 4),
        "job_fit_scoring": round((0.3 * base_score) + (0.4 * req) + (0.3 * skill), 4),
        "skill_gap_analysis": round((0.2 * base_score) + (0.5 * req) + (0.3 * skill), 4),
        "career_strategy_recommendation": round(
            (0.5 * base_score) + (0.25 * req) + (0.25 * skill), 4
        ),
        "cv_analyzer_job_context": round((0.35 * base_score) + (0.35 * req) + (0.30 * desc), 4),
        "application_intelligence": round((0.65 * base_score) + (0.35 * skill), 4),
        "eda_trend_analysis": round(base_score, 4),
        "xai_explanation": round((0.4 * req) + (0.4 * skill) + (0.2 * base_score), 4),
    }


def model_task_blockers(readiness: dict[str, float]) -> dict[str, list[str]]:
    blockers: dict[str, list[str]] = {}
    for task, score in readiness.items():
        blockers[task] = [] if score >= 0.55 else ["insufficient_job_context"]
    blockers["user_profile_embedding"] = ["user_profile_data_not_included"]
    blockers["cv_raw_text_scoring"] = ["cv_raw_text_not_included"]
    blockers["personalized_outcome_prediction"] = ["personal_user_labels_not_included"]
    return blockers


def build_dictionary_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    mapping = [
        ("job_listings_dataset.csv", JOB_LISTINGS_COLUMNS, payload.get("job_rows", [])),
        (
            "job_requirements_dataset.csv",
            JOB_REQUIREMENTS_COLUMNS,
            payload.get("requirements_rows", []),
        ),
        ("job_skills_dataset.csv", JOB_SKILLS_COLUMNS, payload.get("skills_rows", [])),
        ("job_user_signals_dataset.csv", JOB_USER_SIGNALS_COLUMNS, payload.get("signals_rows", [])),
        ("job_ai_model_training_dataset.csv", MODEL_COLUMNS, payload.get("model_rows", [])),
    ]
    for file_name, columns, sample_rows in mapping:
        type_map = infer_type_map(columns=columns, sample_rows=sample_rows)
        for column in columns:
            rows.append(
                {
                    "file_name": file_name,
                    "column_name": column,
                    "column_type": type_map.get(column, "text"),
                    "source_table": infer_source_table(column),
                    "definition": infer_definition(column),
                }
            )
    return rows


def infer_type_map(*, columns: list[str], sample_rows: list[dict[str, Any]]) -> dict[str, str]:
    type_map: dict[str, str] = {}
    for column in columns:
        seen = "text"
        for row in sample_rows:
            value = row.get(column, "")
            if isinstance(value, bool):
                seen = "boolean"
                break
            if isinstance(value, int):
                seen = "integer"
                break
            if isinstance(value, float):
                seen = "number"
                break
        type_map[column] = seen
    return type_map


def infer_source_table(column: str) -> str:
    if column.startswith("requirement_") or column.startswith("requirements_"):
        return "job_requirements"
    if column.startswith("skill_") or column.startswith("skills_"):
        return "job_skills,skills"
    if column.startswith("bookmark_"):
        return "bookmarks"
    if column.startswith("application_"):
        return "application_records"
    if column.startswith("fit_score_"):
        return "fit_score_results"
    if column.startswith("skill_gap_"):
        return "skill_gap_results"
    if column.startswith("cv_analysis_"):
        return "cv_analysis_results"
    if column.startswith("ai_request_"):
        return "ai_request_logs"
    if column.startswith("source_platform_"):
        return "source_platforms"
    if column.startswith("company_"):
        return "companies"
    return "job_listings"


def infer_definition(column: str) -> str:
    words = column.replace("_", " ")
    return f"Dataset field for {words}."


def write_dataset_files(*, options: DatasetExportOptions, payload: dict[str, Any]) -> list[str]:
    files: list[tuple[str, list[str], list[dict[str, Any]]]] = [
        ("job_listings_dataset.csv", JOB_LISTINGS_COLUMNS, payload["job_rows"]),
        ("job_requirements_dataset.csv", JOB_REQUIREMENTS_COLUMNS, payload["requirements_rows"]),
        ("job_skills_dataset.csv", JOB_SKILLS_COLUMNS, payload["skills_rows"]),
        ("job_user_signals_dataset.csv", JOB_USER_SIGNALS_COLUMNS, payload["signals_rows"]),
    ]
    if options.include_model_dataset:
        files.append(("job_ai_model_training_dataset.csv", MODEL_COLUMNS, payload["model_rows"]))
    files.append(
        (
            "dataset_dictionary.csv",
            ["file_name", "column_name", "column_type", "source_table", "definition"],
            payload["dictionary_rows"],
        )
    )

    written: list[str] = []
    for filename, columns, rows in files:
        target = options.output_dir / filename
        write_csv(target, columns=columns, rows=rows)
        written.append(str(target))

    if options.output_format == "single-csv":
        single_rows = build_single_file_rows(
            payload["job_rows"], options.single_file_max_flat_chars
        )
        target = options.output_dir / DEFAULT_SINGLE_FILE_NAME
        columns = JOB_LISTINGS_COLUMNS + ["skills_concat"]
        write_csv(target, columns=columns, rows=single_rows)
        written.append(str(target))
    return written


def build_single_file_rows(rows: list[dict[str, Any]], max_flat_chars: int) -> list[dict[str, Any]]:
    single_rows: list[dict[str, Any]] = []
    for row in rows:
        combined_skills = safe_text(row.get("skills_top_10_names"))
        requirements_concat = safe_text(row.get("requirements_concat"))
        flattened_len = len(requirements_concat) + len(combined_skills)
        if flattened_len > max_flat_chars:
            raise CliInputError(
                f"single-file flatten columns exceed safe limit for job_id={row.get('job_id')}"
            )
        next_row = dict(row)
        next_row["skills_concat"] = combined_skills
        single_rows.append(next_row)
    return single_rows


def write_csv(path: Path, *, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {column: normalize_csv_value(row.get(column, "")) for column in columns}
            )


def group_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[safe_text(row.get(key))].append(row)
    return grouped


def build_in_clause(values: list[str], *, prefix: str) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    placeholders: list[str] = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        placeholders.append(f":{key}")
        params[key] = value
    return ", ".join(placeholders), params


def align_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return [align_row(row, columns) for row in rows]


def align_row(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    return {column: normalize_csv_value(row.get(column, "")) for column in columns}


def normalize_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, datetime):
        return iso_utc(value)
    return value


def bool_to_int(value: Any) -> int:
    return 1 if bool(value) else 0


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    text_value = str(value).strip()
    return text_value


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def iso_utc(value: Any) -> str:
    parsed = parse_dt(value)
    if parsed is None:
        return ""
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_enum(value: Any) -> str:
    text_value = safe_text(value)
    return text_value.upper() if text_value else ""


def to_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def strip_html(text_value: str) -> str:
    if not text_value:
        return ""
    stripped = HTML_TAG_STRIPPER.sub(" ", text_value)
    return " ".join(stripped.split())


def count_paragraphs(text_value: str) -> int:
    if not text_value:
        return 0
    plain = strip_html(text_value)
    if not plain:
        return 0
    paragraphs = [segment for segment in re.split(r"[\n\r]+|[.!?]\s+", plain) if segment.strip()]
    return len(paragraphs)


def html_safety(description: str, requirement_summary: str) -> tuple[bool, bool]:
    combined = f"{description}\n{requirement_summary}"
    if not combined.strip():
        return True, False
    matches = DISPLAY_HTML_TAG_PATTERN.findall(combined)
    safe = True
    for tag_name, attrs in matches:
        if tag_name.lower() not in DISPLAY_HTML_ALLOWLIST:
            safe = False
        if attrs and attrs.strip():
            safe = False
    unsafe = bool(DISPLAY_HTML_UNSAFE_TOKEN_PATTERN.search(combined)) or not safe
    return safe, unsafe


def infer_language(description: str, requirement_summary: str) -> str:
    text_value = f"{strip_html(description)} {strip_html(requirement_summary)}".lower()
    if not text_value.strip():
        return "UNKNOWN"
    id_tokens = {"dan", "yang", "untuk", "pengalaman", "kualifikasi", "dengan", "minimal"}
    en_tokens = {"and", "with", "experience", "requirements", "ability", "team"}
    id_hits = sum(1 for token in id_tokens if f" {token} " in f" {text_value} ")
    en_hits = sum(1 for token in en_tokens if f" {token} " in f" {text_value} ")
    if id_hits > 0 and en_hits > 0:
        return "MIXED"
    if id_hits > 0:
        return "ID"
    if en_hits > 0:
        return "EN"
    return "UNKNOWN"


def iso_sort_key(value: Any) -> str:
    return iso_utc(value)


def stable_row_hash(row: dict[str, Any], columns: list[str]) -> str:
    payload = {column: normalize_csv_value(row.get(column, "")) for column in columns}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def to_json_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def role_family(text_value: str) -> str:
    value = text_value.lower()
    if any(
        token in value for token in ("engineer", "developer", "software", "backend", "frontend")
    ):
        return "engineering"
    if any(token in value for token in ("data", "analyst", "science", "ml", "ai")):
        return "data_ai"
    if any(token in value for token in ("design", "ui", "ux", "product designer")):
        return "design"
    if any(token in value for token in ("marketing", "sales", "business development")):
        return "growth"
    return "other"


def seniority_bucket(level: str) -> str:
    if level in {"ENTRY_LEVEL", "JUNIOR"}:
        return "entry"
    if level in {"MID_LEVEL"}:
        return "mid"
    if level in {"SENIOR", "LEAD"}:
        return "senior"
    return "unknown"


def seniority_numeric(level: str) -> int:
    mapping = {
        "ENTRY_LEVEL": 1,
        "JUNIOR": 2,
        "MID_LEVEL": 3,
        "SENIOR": 4,
        "LEAD": 5,
    }
    return mapping.get(level, 0)


def salary_bucket(salary_min: int | None, salary_max: int | None) -> str:
    midpoint = None
    if salary_min is not None and salary_max is not None:
        midpoint = int((salary_min + salary_max) / 2)
    elif salary_min is not None:
        midpoint = salary_min
    elif salary_max is not None:
        midpoint = salary_max
    if midpoint is None:
        return "unknown"
    if midpoint < 5_000_000:
        return "low"
    if midpoint < 12_000_000:
        return "mid"
    return "high"


def is_tech_role(title: str, skill_names: list[str]) -> bool:
    text_value = f"{title} {' '.join(skill_names)}".lower()
    tokens = ("python", "javascript", "sql", "data", "backend", "frontend", "engineer", "developer")
    return any(token in text_value for token in tokens)


def rank_bucket(*, aggregates: dict[str, Any], signal: dict[str, Any]) -> str:
    score = (
        int(aggregates["detail_readiness_score"])
        + int(aggregates["fit_input_quality_score"])
        + (signal["application_count_interview"] * 5)
    )
    if score >= 170:
        return "top"
    if score >= 120:
        return "mid"
    return "low"


def recommendation_tier(*, aggregates: dict[str, Any]) -> str:
    if not aggregates["is_stale"] and aggregates["fit_input_quality_score"] >= 80:
        return "tier_1"
    if not aggregates["is_stale"] and aggregates["fit_input_quality_score"] >= 60:
        return "tier_2"
    return "tier_3"


def requirement_distribution(requirements_json: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(item.get("type", "") for item in requirements_json)
    return {
        key: int(counter.get(key, 0))
        for key in ["SKILL", "EXPERIENCE", "EDUCATION", "RESPONSIBILITY", "OTHER"]
    }


def requirement_priority_distribution(requirements_json: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(item.get("priority", "") for item in requirements_json)
    return {key: int(counter.get(key, 0)) for key in ["HIGH", "MEDIUM", "LOW"]}


def classify_requirement_quality(requirements_json: list[dict[str, Any]]) -> float:
    if not requirements_json:
        return 0.0
    typed = sum(1 for item in requirements_json if item.get("type") and item.get("type") != "OTHER")
    prioritized = sum(1 for item in requirements_json if item.get("priority"))
    return round(
        ((typed / len(requirements_json)) * 0.7) + ((prioritized / len(requirements_json)) * 0.3), 4
    )


def salary_signal(salary_min: int | None, salary_max: int | None) -> str:
    if salary_min is None and salary_max is None:
        return "unknown"
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        return "outlier"
    return "known"


def search_keywords(base: dict[str, Any]) -> list[str]:
    tokens = set()
    for value in [
        safe_text(base.get("title")),
        safe_text(base.get("normalized_title")),
        safe_text(base.get("category")),
        safe_text(base.get("province")),
        safe_text(base.get("city")),
    ]:
        for token in re.split(r"[^a-zA-Z0-9]+", value.lower()):
            if len(token) >= 3:
                tokens.add(token)
    return sorted(tokens)[:50]


def role_keywords(title: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9]+", title.lower()) if len(token) >= 3][:30]


def success_bucket(priority: str, signal: dict[str, Any]) -> str:
    if signal["application_count_accepted"] > 0:
        return "high"
    if priority == "high" and signal["application_count_rejected"] == 0:
        return "medium"
    return "low"


def actionable_steps(priority: str) -> list[str]:
    if priority == "high":
        return ["apply_now", "highlight_relevant_skills", "tailor_cv_keywords"]
    if priority == "medium":
        return ["close_skill_gap", "improve_requirement_alignment", "apply_next"]
    return ["build_core_skills", "search_similar_roles", "recheck_later"]


def text_quality_score(*, description: str, requirement_summary: str) -> int:
    desc_score = 1 if len(strip_html(description)) >= 80 else 0
    summary_score = 1 if len(strip_html(requirement_summary)) >= 20 else 0
    return int(((desc_score * 0.7) + (summary_score * 0.3)) * 100)


def estimate_tokens(text_value: str) -> int:
    if not text_value:
        return 0
    return max(1, round(len(text_value.split()) * 1.35))


def missing_context_fields(
    *, title: str, description: str, requirements: list[str], skills: list[str]
) -> list[str]:
    missing: list[str] = []
    if not title:
        missing.append("title")
    if not description.strip():
        missing.append("description")
    if not requirements:
        missing.append("requirements")
    if not skills:
        missing.append("skills")
    return missing


def skills_from_aggregates(
    requirements_rows: list[dict[str, Any]],
    skill_names: list[str],
    skill_slugs: list[str],
    skill_categories: list[str],
) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    max_len = max(len(skill_names), len(skill_slugs), len(skill_categories))
    for index in range(max_len):
        skills.append(
            {
                "skill_name": skill_names[index] if index < len(skill_names) else "",
                "skill_slug": skill_slugs[index] if index < len(skill_slugs) else "",
                "skill_category": skill_categories[index] if index < len(skill_categories) else "",
                "skill_confidence": None,
            }
        )
    if not skills and requirements_rows:
        for row in requirements_rows[:5]:
            if normalize_enum(row.get("requirement_type")) == "SKILL":
                value = safe_text(row.get("requirement_value"))
                if value:
                    skills.append(
                        {
                            "skill_name": value,
                            "skill_slug": value.lower().replace(" ", "-"),
                            "skill_category": "",
                            "skill_confidence": None,
                        }
                    )
    return skills


if __name__ == "__main__":
    raise SystemExit(main())
