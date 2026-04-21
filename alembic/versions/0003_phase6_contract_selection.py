"""Phase 6: contract selection columns on signal_candidates

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_NEW_COLUMNS = [
    ("contract_symbol", sa.String(30), {}),
    ("contract_expiration", sa.Date(), {}),
    ("contract_strike", sa.Numeric(10, 2), {}),
    ("contract_type", sa.String(4), {}),
    ("contract_bid", sa.Numeric(10, 4), {}),
    ("contract_ask", sa.Numeric(10, 4), {}),
    ("contract_spread_pct", sa.Numeric(6, 4), {}),
    ("contract_oi", sa.Integer(), {}),
    ("contract_volume", sa.Integer(), {}),
    ("contract_selection_reason", sa.Text(), {}),
    ("contract_rejection_json", postgresql.JSONB(), {}),
    ("contract_selected_at", sa.DateTime(timezone=True), {}),
]


def upgrade() -> None:
    for col_name, col_type, _ in _NEW_COLUMNS:
        op.add_column(
            "signal_candidates",
            sa.Column(col_name, col_type, nullable=True),
        )


def downgrade() -> None:
    for col_name, _, __ in reversed(_NEW_COLUMNS):
        op.drop_column("signal_candidates", col_name)
