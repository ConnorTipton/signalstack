"""Phase 2a: core market schema

Revision ID: 0001
Revises:
Create Date: 2026-04-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_HYPERTABLES = [
    ("provider_health", "checked_at"),
    ("underlying_bars_1m", "bar_time"),
    ("underlying_quotes", "quote_time"),
    ("option_quotes", "quote_time"),
    ("option_trades", "trade_time"),
    ("option_chain_snapshots", "snapshot_time"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    op.create_table(
        "symbols",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )

    op.create_table(
        "provider_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("runtime_mode", sa.String(20), nullable=True),
        sa.Column("priority_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "config_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_name"),
    )

    # --- Hypertables ---

    op.create_table(
        "provider_health",
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column("is_healthy", sa.Boolean(), nullable=False),
        sa.Column("provider_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("lag_seconds", sa.Numeric(10, 3), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("checked_at", "id"),
    )
    op.create_index("ix_provider_health_provider_name", "provider_health", ["provider_name"])

    op.create_table(
        "underlying_bars_1m",
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=False),
        sa.Column("high", sa.Numeric(12, 4), nullable=False),
        sa.Column("low", sa.Numeric(12, 4), nullable=False),
        sa.Column("close", sa.Numeric(12, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("vwap", sa.Numeric(12, 4), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("bar_time", "symbol_id"),
    )

    op.create_table(
        "underlying_quotes",
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("bid", sa.Numeric(12, 4), nullable=True),
        sa.Column("ask", sa.Numeric(12, 4), nullable=True),
        sa.Column("bid_size", sa.Integer(), nullable=True),
        sa.Column("ask_size", sa.Integer(), nullable=True),
        sa.Column("last", sa.Numeric(12, 4), nullable=True),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("quote_time", "id"),
    )
    op.create_index("ix_underlying_quotes_symbol_id", "underlying_quotes", ["symbol_id"])

    op.create_table(
        "option_quotes",
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("contract_symbol", sa.String(30), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("option_type", sa.String(4), nullable=False),
        sa.Column("bid", sa.Numeric(10, 4), nullable=True),
        sa.Column("ask", sa.Numeric(10, 4), nullable=True),
        sa.Column("bid_size", sa.Integer(), nullable=True),
        sa.Column("ask_size", sa.Integer(), nullable=True),
        sa.Column("last", sa.Numeric(10, 4), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("implied_volatility", sa.Numeric(10, 6), nullable=True),
        sa.Column("delta", sa.Numeric(8, 6), nullable=True),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("quote_time", "id"),
    )
    op.create_index("ix_option_quotes_symbol_id", "option_quotes", ["symbol_id"])

    op.create_table(
        "option_trades",
        sa.Column("trade_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("contract_symbol", sa.String(30), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("option_type", sa.String(4), nullable=False),
        sa.Column("price", sa.Numeric(10, 4), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("conditions", sa.String(100), nullable=True),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("trade_time", "id"),
    )
    op.create_index("ix_option_trades_symbol_id", "option_trades", ["symbol_id"])

    op.create_table(
        "option_chain_snapshots",
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("contract_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "total_call_oi", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "total_put_oi", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "total_call_volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "total_put_volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("snapshot_time", "id"),
    )
    op.create_index(
        "ix_option_chain_snapshots_symbol_id", "option_chain_snapshots", ["symbol_id"]
    )

    # Convert time-series tables to TimescaleDB hypertables.
    for table, time_col in _HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', '{time_col}', if_not_exists => TRUE)"
        )


def downgrade() -> None:
    for table, _ in reversed(_HYPERTABLES):
        op.drop_table(table)
    op.drop_table("provider_configs")
    op.drop_table("symbols")
