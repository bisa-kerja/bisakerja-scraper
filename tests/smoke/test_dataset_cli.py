from __future__ import annotations

import csv
import json

from sqlalchemy import create_engine, text

from cli.dataset import main


class StubSettings:
    def __init__(self, backend_database_url: str) -> None:
        self.backend_database_url = backend_database_url
        self.freshness_stale_after_hours = 72


def test_jobs_csv_export_writes_model_dataset(monkeypatch, tmp_path, capsys) -> None:
    backend_path = tmp_path / "backend.db"
    backend_url = f"sqlite:///{backend_path}"
    build_backend_fixture(backend_url)
    monkeypatch.setattr("cli.dataset.load_settings", lambda _: StubSettings(backend_url))

    output_dir = tmp_path / "datasets"
    assert main(["jobs-csv", "--output-dir", str(output_dir)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["rowCounts"]["jobListings"] == 2
    assert payload["rowCounts"]["jobModelDataset"] == 2

    model_path = output_dir / "job_ai_model_training_dataset.csv"
    assert model_path.exists()
    with model_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert "user_id" not in rows[0]
    assert "job_fit_scoring" in rows[0]["supported_model_tasks_json"]
    assert rows[0]["model_split"] in {"train", "validation", "test"}


def test_jobs_csv_export_applies_source_and_status_filters(monkeypatch, tmp_path, capsys) -> None:
    backend_path = tmp_path / "backend-filter.db"
    backend_url = f"sqlite:///{backend_path}"
    build_backend_fixture(backend_url)
    monkeypatch.setattr("cli.dataset.load_settings", lambda _: StubSettings(backend_url))

    output_dir = tmp_path / "datasets-filter"
    assert (
        main(
            [
                "jobs-csv",
                "--output-dir",
                str(output_dir),
                "--source",
                "dealls",
                "--status",
                "active",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["rowCounts"]["jobListings"] == 1
    assert payload["rowCounts"]["jobModelDataset"] == 1


def test_jobs_csv_single_file_respects_flatten_limit(monkeypatch, tmp_path, capsys) -> None:
    backend_path = tmp_path / "backend-single.db"
    backend_url = f"sqlite:///{backend_path}"
    build_backend_fixture(backend_url, long_requirement=True)
    monkeypatch.setattr("cli.dataset.load_settings", lambda _: StubSettings(backend_url))

    output_dir = tmp_path / "datasets-single"
    assert (
        main(
            [
                "jobs-csv",
                "--output-dir",
                str(output_dir),
                "--format",
                "single-csv",
                "--single-file-max-flat-chars",
                "20",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert "flatten columns exceed safe limit" in payload["reason"]


def build_backend_fixture(database_url: str, *, long_requirement: bool = False) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        create_schema(connection)
        insert_fixture_rows(connection, long_requirement=long_requirement)
    engine.dispose()


def create_schema(connection) -> None:  # noqa: ANN001
    statements = [
        """
        CREATE TABLE source_platforms (
          id TEXT PRIMARY KEY,
          slug TEXT NOT NULL,
          name TEXT NOT NULL,
          base_url TEXT,
          is_active INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE companies (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          slug TEXT,
          logo_url TEXT,
          website_url TEXT
        )
        """,
        """
        CREATE TABLE job_listings (
          id TEXT PRIMARY KEY,
          source_platform_id TEXT NOT NULL,
          company_id TEXT NOT NULL,
          ingestion_run_id TEXT,
          external_job_id TEXT NOT NULL,
          title TEXT NOT NULL,
          normalized_title TEXT,
          category TEXT,
          description TEXT,
          requirement_summary TEXT,
          work_type TEXT,
          employment_type TEXT,
          experience_level TEXT,
          location_display TEXT,
          province TEXT,
          city TEXT,
          salary_min INTEGER,
          salary_max INTEGER,
          salary_currency TEXT,
          salary_period TEXT,
          salary_display TEXT,
          source_url TEXT,
          external_apply_url TEXT,
          source_posted_at TEXT,
          source_updated_at TEXT,
          last_seen_at TEXT,
          expired_at TEXT,
          status TEXT,
          created_at TEXT,
          updated_at TEXT
        )
        """,
        """
        CREATE TABLE job_requirements (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          type TEXT NOT NULL,
          value TEXT NOT NULL,
          priority TEXT,
          sort_order INTEGER,
          created_at TEXT
        )
        """,
        """
        CREATE TABLE skills (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          slug TEXT NOT NULL,
          category TEXT
        )
        """,
        """
        CREATE TABLE job_skills (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          skill_id TEXT NOT NULL,
          confidence REAL,
          created_at TEXT
        )
        """,
        """
        CREATE TABLE bookmarks (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          created_at TEXT
        )
        """,
        """
        CREATE TABLE application_records (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          status TEXT NOT NULL,
          applied_at TEXT,
          updated_at TEXT
        )
        """,
        """
        CREATE TABLE fit_score_results (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          fit_score INTEGER,
          readiness_level TEXT,
          recommendation_decision TEXT,
          model_name TEXT,
          analyzed_at TEXT
        )
        """,
        """
        CREATE TABLE skill_gap_results (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          gaps TEXT,
          model_name TEXT,
          analyzed_at TEXT
        )
        """,
        """
        CREATE TABLE cv_analysis_results (
          id TEXT PRIMARY KEY,
          job_listing_id TEXT NOT NULL,
          language TEXT,
          input_mode TEXT,
          compare_source TEXT,
          model_name TEXT,
          analyzed_at TEXT
        )
        """,
        """
        CREATE TABLE ai_request_logs (
          id TEXT PRIMARY KEY,
          kind TEXT,
          status TEXT,
          model_name TEXT,
          error_code TEXT,
          created_at TEXT,
          input_summary TEXT,
          output_summary TEXT
        )
        """,
    ]
    for statement in statements:
        connection.execute(text(statement))


def insert_fixture_rows(connection, *, long_requirement: bool) -> None:  # noqa: ANN001
    connection.execute(
        text(
            """
            INSERT INTO source_platforms (id, slug, name, base_url, is_active) VALUES
              ('sp-1', 'dealls', 'Dealls', 'https://dealls.com', 1),
              ('sp-2', 'glints', 'Glints', 'https://glints.com', 1)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO companies (id, name, slug, logo_url, website_url) VALUES
              ('co-1', 'Tech Nusantara', 'tech-nusantara', 'https://cdn/logo.png', 'https://tech.example'),
              ('co-2', 'Data Maju', 'data-maju', '', '')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO job_listings (
              id, source_platform_id, company_id, ingestion_run_id, external_job_id, title,
              normalized_title, category, description, requirement_summary, work_type,
              employment_type, experience_level, location_display, province, city, salary_min,
              salary_max, salary_currency, salary_period, salary_display, source_url,
              external_apply_url, source_posted_at, source_updated_at, last_seen_at, expired_at,
              status, created_at, updated_at
            ) VALUES
              (
                'job-1', 'sp-1', 'co-1', 'run-1', 'dealls-1', 'Backend Engineer',
                'Backend Engineer', 'Engineering', '<p>Build API services.</p>', 'Python dan SQL',
                'REMOTE', 'FULL_TIME', 'MID_LEVEL', 'Jakarta Selatan, DKI Jakarta', 'DKI Jakarta',
                'Jakarta Selatan', 8000000, 12000000, 'IDR', 'MONTHLY', 'Rp8-12jt',
                'https://dealls.com/jobs/1', 'https://dealls.com/jobs/1/apply',
                '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '2026-05-06T00:00:00Z', NULL,
                'ACTIVE', '2026-05-01T00:00:00Z', '2026-05-06T00:00:00Z'
              ),
              (
                'job-2', 'sp-2', 'co-2', 'run-2', 'glints-1', 'Data Analyst',
                'Data Analyst', 'Data', '<p>Analyze data.</p>', 'Excel',
                'ONSITE', 'CONTRACT', 'ENTRY_LEVEL', 'Bandung, Jawa Barat', 'Jawa Barat',
                'Bandung', 5000000, 7000000, 'IDR', 'MONTHLY', 'Rp5-7jt',
                'https://glints.com/jobs/1', 'https://glints.com/jobs/1/apply',
                '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z', '2026-04-25T00:00:00Z',
                '2026-05-01T00:00:00Z', 'STALE', '2026-04-20T00:00:00Z', '2026-04-25T00:00:00Z'
              )
            """
        )
    )
    long_text = (
        "Requirement sangat panjang untuk uji batas flatten. " * 20
        if long_requirement
        else "Memahami Python"
    )
    connection.execute(
        text(
            """
            INSERT INTO job_requirements (
              id,
              job_listing_id,
              type,
              value,
              priority,
              sort_order,
              created_at
            ) VALUES
              ('req-1', 'job-1', 'SKILL', :long_text, 'HIGH', 1, '2026-05-01T00:00:00Z'),
              (
                'req-2',
                'job-1',
                'EXPERIENCE',
                '3 tahun pengalaman backend',
                'MEDIUM',
                2,
                '2026-05-01T00:00:00Z'
              ),
              ('req-3', 'job-2', 'SKILL', 'Excel', 'HIGH', 1, '2026-04-20T00:00:00Z')
            """
        ),
        {"long_text": long_text},
    )
    connection.execute(
        text(
            """
            INSERT INTO skills (id, name, slug, category) VALUES
              ('sk-1', 'Python', 'python', 'programming'),
              ('sk-2', 'SQL', 'sql', 'database'),
              ('sk-3', 'Excel', 'excel', 'spreadsheet')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO job_skills (id, job_listing_id, skill_id, confidence, created_at) VALUES
              ('js-1', 'job-1', 'sk-1', 0.95, '2026-05-01T00:00:00Z'),
              ('js-2', 'job-1', 'sk-2', 0.90, '2026-05-01T00:00:00Z'),
              ('js-3', 'job-2', 'sk-3', 0.80, '2026-04-20T00:00:00Z')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO bookmarks (id, job_listing_id, created_at) VALUES
              ('bm-1', 'job-1', '2026-05-06T00:00:00Z')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO application_records (
              id,
              job_listing_id,
              status,
              applied_at,
              updated_at
            ) VALUES
              ('app-1', 'job-1', 'INTERVIEW', '2026-05-05T00:00:00Z', '2026-05-06T00:00:00Z')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO fit_score_results (
              id,
              job_listing_id,
              fit_score,
              readiness_level,
              recommendation_decision,
              model_name,
              analyzed_at
            ) VALUES
              ('fit-1', 'job-1', 82, 'HIGH', 'APPLY', 'gpt-model', '2026-05-06T00:00:00Z')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO skill_gap_results (id, job_listing_id, gaps, model_name, analyzed_at) VALUES
              ('gap-1', 'job-1', '["docker","aws"]', 'gpt-model', '2026-05-06T00:00:00Z')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO cv_analysis_results (
              id, job_listing_id, language, input_mode, compare_source, model_name, analyzed_at
            ) VALUES
              ('cv-1', 'job-1', 'ID', 'UPLOAD', 'JOB_SEARCH', 'gpt-model', '2026-05-06T00:00:00Z')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO ai_request_logs (
              id, kind, status, model_name, error_code, created_at, input_summary, output_summary
            ) VALUES
              (
                'ai-1', 'JOB_FIT', 'SUCCEEDED', 'gpt-model', '',
                '2026-05-06T00:00:00Z', '{"jobId":"job-1"}', '{"result":"ok"}'
              ),
              (
                'ai-2', 'CV_ANALYSIS', 'FAILED', 'gpt-model', 'timeout',
                '2026-05-06T01:00:00Z', '{"job_listing_id":"job-1"}', '{"error":"timeout"}'
              )
            """
        )
    )
