"""Add pipeline idempotency constraints

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_detected_events_detector_article_symbol", table_name="detected_events")
    op.drop_index("ix_signal_candidates_news_event_id", table_name="signal_candidates")
    op.drop_index("ix_alerts_signal_candidate_id", table_name="alerts")
    op.drop_index("ix_paper_orders_alert_id", table_name="paper_orders")

    op.create_index(
        "uq_detected_events_detector_article_symbol",
        "detected_events",
        ["detector", "news_article_id", "symbol_id"],
        unique=True,
        postgresql_where=sa.text("news_article_id IS NOT NULL"),
        sqlite_where=sa.text("news_article_id IS NOT NULL"),
    )
    op.create_index(
        "uq_signal_candidates_news_event_id",
        "signal_candidates",
        ["news_event_id"],
        unique=True,
        postgresql_where=sa.text("news_event_id IS NOT NULL"),
        sqlite_where=sa.text("news_event_id IS NOT NULL"),
    )
    op.create_index(
        "uq_alerts_signal_candidate_id",
        "alerts",
        ["signal_candidate_id"],
        unique=True,
        postgresql_where=sa.text("signal_candidate_id IS NOT NULL"),
        sqlite_where=sa.text("signal_candidate_id IS NOT NULL"),
    )
    op.create_index(
        "uq_paper_orders_alert_id",
        "paper_orders",
        ["alert_id"],
        unique=True,
        postgresql_where=sa.text("alert_id IS NOT NULL"),
        sqlite_where=sa.text("alert_id IS NOT NULL"),
    )
    op.create_index(
        "uq_llm_news_labels_article_model",
        "llm_news_labels",
        ["article_id", "model_name"],
        unique=True,
        postgresql_where=sa.text("article_id IS NOT NULL"),
        sqlite_where=sa.text("article_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_llm_news_labels_article_model", table_name="llm_news_labels")
    op.drop_index("uq_paper_orders_alert_id", table_name="paper_orders")
    op.drop_index("uq_alerts_signal_candidate_id", table_name="alerts")
    op.drop_index("uq_signal_candidates_news_event_id", table_name="signal_candidates")
    op.drop_index("uq_detected_events_detector_article_symbol", table_name="detected_events")

    op.create_index(
        "ix_paper_orders_alert_id",
        "paper_orders",
        ["alert_id"],
        unique=False,
    )
    op.create_index(
        "ix_alerts_signal_candidate_id",
        "alerts",
        ["signal_candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_candidates_news_event_id",
        "signal_candidates",
        ["news_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_detected_events_detector_article_symbol",
        "detected_events",
        ["detector", "news_article_id", "symbol_id"],
        unique=False,
    )
