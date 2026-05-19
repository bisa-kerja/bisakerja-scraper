"""add raw job scrape metadata

Revision ID: 20260503_0006
Revises: 20260502_0005
Create Date: 2026-05-03 00:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260503_0006"
down_revision = "20260502_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_jobs", sa.Column("metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_jobs", "metadata_json")
