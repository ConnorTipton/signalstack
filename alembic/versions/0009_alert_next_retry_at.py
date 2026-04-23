"""Add next_retry_at to alerts for exponential-backoff retry scheduling.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "next_retry_at")
