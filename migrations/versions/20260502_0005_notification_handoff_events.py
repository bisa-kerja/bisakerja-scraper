"""add notification handoff events

Revision ID: 20260502_0005
Revises: 20260502_0004
Create Date: 2026-05-02 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260502_0005"
down_revision = "20260502_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_handoff_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scrape_run_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_job_id", sa.String(length=36), nullable=False),
        sa.Column("sync_event_id", sa.String(length=36), nullable=False),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("response_summary", sa.JSON(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["normalized_job_id"], ["normalized_jobs.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.ForeignKeyConstraint(["sync_event_id"], ["sync_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scrape_run_id",
            "source_platform",
            "external_id",
            "target",
            name="notification_handoff_run_source_external_target_unique",
        ),
    )
    op.create_index(
        "notification_handoff_status_attempted_at_idx",
        "notification_handoff_events",
        ["status", "attempted_at"],
    )
    op.create_index(
        "notification_handoff_sync_event_id_idx",
        "notification_handoff_events",
        ["sync_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "notification_handoff_sync_event_id_idx",
        table_name="notification_handoff_events",
    )
    op.drop_index(
        "notification_handoff_status_attempted_at_idx",
        table_name="notification_handoff_events",
    )
    op.drop_table("notification_handoff_events")
