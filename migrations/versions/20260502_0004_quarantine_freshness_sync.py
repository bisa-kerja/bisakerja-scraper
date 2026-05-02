"""add normalization quarantine

Revision ID: 20260502_0004
Revises: 20260502_0003
Create Date: 2026-05-02 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260502_0004"
down_revision = "20260502_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "normalization_quarantine",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=True),
        sa.Column("raw_job_id", sa.String(length=36), nullable=True),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("error_category", sa.String(length=128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("source_field_path", sa.String(length=255), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["raw_job_id"], ["raw_jobs.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "normalization_quarantine_status_source_idx",
        "normalization_quarantine",
        ["status", "source_platform"],
    )
    op.create_index(
        "normalization_quarantine_raw_job_id_idx",
        "normalization_quarantine",
        ["raw_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "normalization_quarantine_raw_job_id_idx",
        table_name="normalization_quarantine",
    )
    op.drop_index(
        "normalization_quarantine_status_source_idx",
        table_name="normalization_quarantine",
    )
    op.drop_table("normalization_quarantine")
