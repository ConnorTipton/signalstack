"""Add market query indexes and preserve Marketaux raw rows

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_MARKET_INDEXES = [
    (
        "ix_underlying_bars_symbol_time_desc",
        "underlying_bars_1m",
        ["symbol_id", sa.text("bar_time DESC")],
    ),
    (
        "ix_option_quotes_contract_time_desc",
        "option_quotes",
        ["contract_symbol", sa.text("quote_time DESC")],
    ),
    (
        "ix_option_quotes_symbol_time_desc",
        "option_quotes",
        ["symbol_id", sa.text("quote_time DESC")],
    ),
    (
        "ix_option_trades_symbol_trade_time",
        "option_trades",
        ["symbol_id", "trade_time"],
    ),
    (
        "ix_option_chain_snapshots_symbol_snapshot_time",
        "option_chain_snapshots",
        ["symbol_id", "snapshot_time"],
    ),
]


def upgrade() -> None:
    op.drop_index("uq_raw_marketaux_events_content_hash", table_name="raw_marketaux_events")
    for name, table, columns in _MARKET_INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(_MARKET_INDEXES):
        op.drop_index(name, table_name=table)
    op.create_index(
        "uq_raw_marketaux_events_content_hash",
        "raw_marketaux_events",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )
