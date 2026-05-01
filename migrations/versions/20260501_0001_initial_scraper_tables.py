"""initial scraper operational tables

Revision ID: 20260501_0001
Revises:
Create Date: 2026-05-01 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260501_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_records_count", sa.Integer(), nullable=False),
        sa.Column("normalized_records_count", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "scrape_runs_source_status_started_at_idx",
        "scrape_runs",
        ["source_platform", "status", "started_at"],
    )

    op.create_table(
        "raw_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=False),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_platform", "external_id", name="raw_jobs_source_external_id_unique"
        ),
    )
    op.create_index("raw_jobs_scrape_run_id_idx", "raw_jobs", ["scrape_run_id"])

    op.create_table(
        "normalized_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("raw_job_id", sa.String(length=36), nullable=True),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["raw_job_id"], ["raw_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_platform",
            "external_id",
            name="normalized_jobs_source_external_id_unique",
        ),
    )
    op.create_index(
        "normalized_jobs_status_last_seen_at_idx",
        "normalized_jobs",
        ["status", "last_seen_at"],
    )
    op.create_index("normalized_jobs_source_platform_idx", "normalized_jobs", ["source_platform"])

    op.create_table(
        "sync_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=True),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=True),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column(
            "attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "sync_events_status_attempted_at_idx", "sync_events", ["status", "attempted_at"]
    )
    op.create_index(
        "sync_events_source_external_id_idx", "sync_events", ["source_platform", "external_id"]
    )


def downgrade() -> None:
    op.drop_index("sync_events_source_external_id_idx", table_name="sync_events")
    op.drop_index("sync_events_status_attempted_at_idx", table_name="sync_events")
    op.drop_table("sync_events")
    op.drop_index("normalized_jobs_source_platform_idx", table_name="normalized_jobs")
    op.drop_index("normalized_jobs_status_last_seen_at_idx", table_name="normalized_jobs")
    op.drop_table("normalized_jobs")
    op.drop_index("raw_jobs_scrape_run_id_idx", table_name="raw_jobs")
    op.drop_table("raw_jobs")
    op.drop_index("scrape_runs_source_status_started_at_idx", table_name="scrape_runs")
    op.drop_table("scrape_runs")
