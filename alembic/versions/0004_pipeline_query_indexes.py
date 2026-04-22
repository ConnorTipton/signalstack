"""Add pipeline and review query indexes

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_INDEXES = [
    (
        "ix_detected_events_detector_article_symbol",
        "detected_events",
        ["detector", "news_article_id", "symbol_id"],
    ),
    ("ix_detected_events_detected_at", "detected_events", ["detected_at"]),
    ("ix_signal_candidates_news_event_id", "signal_candidates", ["news_event_id"]),
    (
        "ix_signal_candidates_status_contract_symbol",
        "signal_candidates",
        ["status", "contract_symbol"],
    ),
    ("ix_signal_candidates_created_at", "signal_candidates", ["created_at"]),
    ("ix_alerts_signal_candidate_id", "alerts", ["signal_candidate_id"]),
    ("ix_alerts_created_at", "alerts", ["created_at"]),
    ("ix_alerts_sent_at", "alerts", ["sent_at"]),
    ("ix_paper_orders_alert_id", "paper_orders", ["alert_id"]),
    ("ix_paper_orders_created_at", "paper_orders", ["created_at"]),
    ("ix_paper_positions_opened_at", "paper_positions", ["opened_at"]),
    ("ix_paper_positions_closed_at", "paper_positions", ["closed_at"]),
    ("ix_news_articles_created_at", "news_articles", ["created_at"]),
    ("ix_provider_health_name_checked_at", "provider_health", ["provider_name", "checked_at"]),
]


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
