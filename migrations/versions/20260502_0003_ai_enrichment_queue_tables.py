"""add ai enrichment audit staging and queue tables

Revision ID: 20260502_0003
Revises: 20260502_0002
Create Date: 2026-05-02 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260502_0003"
down_revision = "20260502_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_request_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=True),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("base_url_alias", sa.String(length=255), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("response_summary", sa.JSON(), nullable=True),
        sa.Column("error_category", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ai_request_logs_job_created_at_idx",
        "ai_request_logs",
        ["normalized_job_id", "created_at"],
    )
    op.create_index(
        "ai_request_logs_status_created_at_idx",
        "ai_request_logs",
        ["status", "created_at"],
    )

    op.create_table(
        "job_skills_staging",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=False),
        sa.Column("ai_request_log_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("normalized_value", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["ai_request_log_id"], ["ai_request_logs.id"]),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_job_id",
            "normalized_value",
            name="job_skills_staging_job_value_unique",
        ),
    )
    op.create_index("job_skills_staging_job_idx", "job_skills_staging", ["normalized_job_id"])

    op.create_table(
        "job_requirements_staging",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=False),
        sa.Column("ai_request_log_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("requirement_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["ai_request_log_id"], ["ai_request_logs.id"]),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_job_id",
            "requirement_type",
            "normalized_value",
            name="job_requirements_staging_job_type_value_unique",
        ),
    )
    op.create_index(
        "job_requirements_staging_job_idx",
        "job_requirements_staging",
        ["normalized_job_id"],
    )

    op.create_table(
        "stage_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=True),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("stage_jobs_status_available_at_idx", "stage_jobs", ["status", "available_at"])
    op.create_index("stage_jobs_correlation_id_idx", "stage_jobs", ["correlation_id"])
    op.create_index("stage_jobs_scrape_run_id_idx", "stage_jobs", ["scrape_run_id"])


def downgrade() -> None:
    op.drop_index("stage_jobs_scrape_run_id_idx", table_name="stage_jobs")
    op.drop_index("stage_jobs_correlation_id_idx", table_name="stage_jobs")
    op.drop_index("stage_jobs_status_available_at_idx", table_name="stage_jobs")
    op.drop_table("stage_jobs")
    op.drop_index("job_requirements_staging_job_idx", table_name="job_requirements_staging")
    op.drop_table("job_requirements_staging")
    op.drop_index("job_skills_staging_job_idx", table_name="job_skills_staging")
    op.drop_table("job_skills_staging")
    op.drop_index("ai_request_logs_status_created_at_idx", table_name="ai_request_logs")
    op.drop_index("ai_request_logs_job_created_at_idx", table_name="ai_request_logs")
    op.drop_table("ai_request_logs")
