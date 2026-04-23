"""Add TimescaleDB data-retention policies on raw/quote hypertables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-22

Retention windows:
  underlying_bars_1m        — 365 days  (aggregated bars; keep longer)
  underlying_quotes         — 180 days  (normalized quotes)
  provider_health           — 90 days
  option_chain_snapshots    — 90 days
  option_quotes             — 90 days
  option_trades             — 90 days
  raw_tradier_events        — 90 days
  raw_alpaca_market_events  — 90 days

if_not_exists=TRUE on add / remove so the migration is idempotent.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_POLICIES: list[tuple[str, str]] = [
    ("underlying_bars_1m", "365 days"),
    ("underlying_quotes", "180 days"),
    ("provider_health", "90 days"),
    ("option_chain_snapshots", "90 days"),
    ("option_quotes", "90 days"),
    ("option_trades", "90 days"),
    ("raw_tradier_events", "90 days"),
    ("raw_alpaca_market_events", "90 days"),
]


def upgrade() -> None:
    for table, interval in _POLICIES:
        op.execute(
            f"SELECT add_retention_policy('{table}', INTERVAL '{interval}', if_not_exists => TRUE)"
        )


def downgrade() -> None:
    for table, _ in _POLICIES:
        # Wrapped in DO block so downgrade is safe on any TimescaleDB version
        op.execute(
            f"""
            DO $$
            BEGIN
                PERFORM remove_retention_policy('{table}');
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END $$;
            """
        )
