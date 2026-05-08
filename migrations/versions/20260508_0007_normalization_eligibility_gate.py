"""add normalization eligibility decisions

Revision ID: 20260508_0007
Revises: 20260503_0006
Create Date: 2026-05-08 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260508_0007"
down_revision = "20260503_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "normalization_eligibility_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=True),
        sa.Column("raw_job_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=True),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("identity_key", sa.String(length=512), nullable=True),
        sa.Column("identity_hash", sa.String(length=128), nullable=True),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("backend_job_id", sa.String(length=64), nullable=True),
        sa.Column("normalized_sync_state", sa.String(length=32), nullable=True),
        sa.Column("reason_details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.ForeignKeyConstraint(["raw_job_id"], ["raw_jobs.id"]),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_job_id", name="eligibility_decisions_raw_job_unique"),
    )
    op.create_index(
        "eligibility_decisions_scrape_run_id_idx",
        "normalization_eligibility_decisions",
        ["scrape_run_id"],
    )
    op.create_index(
        "eligibility_decisions_decision_idx",
        "normalization_eligibility_decisions",
        ["decision"],
    )
    op.create_index(
        "eligibility_decisions_source_external_idx",
        "normalization_eligibility_decisions",
        ["source_platform", "external_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "eligibility_decisions_source_external_idx",
        table_name="normalization_eligibility_decisions",
    )
    op.drop_index(
        "eligibility_decisions_decision_idx",
        table_name="normalization_eligibility_decisions",
    )
    op.drop_index(
        "eligibility_decisions_scrape_run_id_idx",
        table_name="normalization_eligibility_decisions",
    )
    op.drop_table("normalization_eligibility_decisions")
