"""add sync event audit fields

Revision ID: 20260502_0002
Revises: 20260501_0001
Create Date: 2026-05-02 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260502_0002"
down_revision = "20260501_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sync_events") as batch_op:
        batch_op.add_column(sa.Column("payload_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        )
        batch_op.add_column(sa.Column("response_summary", sa.JSON(), nullable=True))
        batch_op.create_unique_constraint(
            "sync_events_target_job_payload_unique",
            ["target", "normalized_job_id", "payload_hash"],
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_events") as batch_op:
        batch_op.drop_constraint("sync_events_target_job_payload_unique", type_="unique")
        batch_op.drop_column("response_summary")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("payload_hash")
