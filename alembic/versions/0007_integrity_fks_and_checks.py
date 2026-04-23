"""Add FK constraints and CHECK constraints for pipeline data integrity

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22

FKs use NOT VALID so this migration succeeds on existing databases without
scanning every row. New rows are enforced immediately. Run
  ALTER TABLE <t> VALIDATE CONSTRAINT <name>;
per table when you want to confirm existing data is clean.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Foreign keys — symbol_id columns (non-nullable, RESTRICT on delete) #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE detected_events
            ADD CONSTRAINT fk_detected_events_symbol_id
            FOREIGN KEY (symbol_id) REFERENCES symbols(id) NOT VALID
    """)
    op.execute("""
        ALTER TABLE signal_candidates
            ADD CONSTRAINT fk_signal_candidates_symbol_id
            FOREIGN KEY (symbol_id) REFERENCES symbols(id) NOT VALID
    """)
    op.execute("""
        ALTER TABLE alerts
            ADD CONSTRAINT fk_alerts_symbol_id
            FOREIGN KEY (symbol_id) REFERENCES symbols(id) NOT VALID
    """)
    op.execute("""
        ALTER TABLE paper_orders
            ADD CONSTRAINT fk_paper_orders_symbol_id
            FOREIGN KEY (symbol_id) REFERENCES symbols(id) NOT VALID
    """)
    op.execute("""
        ALTER TABLE paper_positions
            ADD CONSTRAINT fk_paper_positions_symbol_id
            FOREIGN KEY (symbol_id) REFERENCES symbols(id) NOT VALID
    """)

    # ------------------------------------------------------------------ #
    # Foreign keys — nullable join columns (SET NULL on delete)           #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE detected_events
            ADD CONSTRAINT fk_detected_events_news_article_id
            FOREIGN KEY (news_article_id) REFERENCES news_articles(id)
            ON DELETE SET NULL NOT VALID
    """)
    op.execute("""
        ALTER TABLE detected_events
            ADD CONSTRAINT fk_detected_events_llm_label_id
            FOREIGN KEY (llm_label_id) REFERENCES llm_news_labels(id)
            ON DELETE SET NULL NOT VALID
    """)
    op.execute("""
        ALTER TABLE signal_candidates
            ADD CONSTRAINT fk_signal_candidates_news_event_id
            FOREIGN KEY (news_event_id) REFERENCES detected_events(id)
            ON DELETE SET NULL NOT VALID
    """)
    op.execute("""
        ALTER TABLE alerts
            ADD CONSTRAINT fk_alerts_signal_candidate_id
            FOREIGN KEY (signal_candidate_id) REFERENCES signal_candidates(id)
            ON DELETE SET NULL NOT VALID
    """)
    op.execute("""
        ALTER TABLE paper_orders
            ADD CONSTRAINT fk_paper_orders_alert_id
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
            ON DELETE SET NULL NOT VALID
    """)
    op.execute("""
        ALTER TABLE paper_positions
            ADD CONSTRAINT fk_paper_positions_order_id
            FOREIGN KEY (order_id) REFERENCES paper_orders(id)
            ON DELETE SET NULL NOT VALID
    """)
    op.execute("""
        ALTER TABLE paper_positions
            ADD CONSTRAINT fk_paper_positions_alert_id
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
            ON DELETE SET NULL NOT VALID
    """)

    # ------------------------------------------------------------------ #
    # CHECK constraints — enum-like columns                               #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE detected_events
            ADD CONSTRAINT ck_detected_events_detector
            CHECK (detector IN ('A', 'B', 'C'))
    """)
    op.execute("""
        ALTER TABLE detected_events
            ADD CONSTRAINT ck_detected_events_polarity
            CHECK (polarity IN ('positive', 'neutral', 'negative'))
    """)
    op.execute("""
        ALTER TABLE signal_candidates
            ADD CONSTRAINT ck_signal_candidates_status
            CHECK (status IN ('pending', 'promoted', 'watch', 'rejected'))
    """)
    op.execute("""
        ALTER TABLE paper_orders
            ADD CONSTRAINT ck_paper_orders_status
            CHECK (status IN ('pending', 'submitted', 'filled', 'cancelled', 'rejected', 'submit_failed'))
    """)
    op.execute("""
        ALTER TABLE paper_orders
            ADD CONSTRAINT ck_paper_orders_side
            CHECK (side IN ('buy', 'sell'))
    """)
    op.execute("""
        ALTER TABLE paper_orders
            ADD CONSTRAINT ck_paper_orders_option_type
            CHECK (option_type IN ('call', 'put'))
    """)
    op.execute("""
        ALTER TABLE paper_positions
            ADD CONSTRAINT ck_paper_positions_status
            CHECK (status IN ('open', 'closed'))
    """)


def downgrade() -> None:
    # CHECK constraints
    op.execute("ALTER TABLE paper_positions DROP CONSTRAINT IF EXISTS ck_paper_positions_status")
    op.execute("ALTER TABLE paper_orders DROP CONSTRAINT IF EXISTS ck_paper_orders_option_type")
    op.execute("ALTER TABLE paper_orders DROP CONSTRAINT IF EXISTS ck_paper_orders_side")
    op.execute("ALTER TABLE paper_orders DROP CONSTRAINT IF EXISTS ck_paper_orders_status")
    op.execute("ALTER TABLE signal_candidates DROP CONSTRAINT IF EXISTS ck_signal_candidates_status")
    op.execute("ALTER TABLE detected_events DROP CONSTRAINT IF EXISTS ck_detected_events_polarity")
    op.execute("ALTER TABLE detected_events DROP CONSTRAINT IF EXISTS ck_detected_events_detector")

    # FK constraints — nullable joins
    op.execute("ALTER TABLE paper_positions DROP CONSTRAINT IF EXISTS fk_paper_positions_alert_id")
    op.execute("ALTER TABLE paper_positions DROP CONSTRAINT IF EXISTS fk_paper_positions_order_id")
    op.execute("ALTER TABLE paper_orders DROP CONSTRAINT IF EXISTS fk_paper_orders_alert_id")
    op.execute("ALTER TABLE alerts DROP CONSTRAINT IF EXISTS fk_alerts_signal_candidate_id")
    op.execute("ALTER TABLE signal_candidates DROP CONSTRAINT IF EXISTS fk_signal_candidates_news_event_id")
    op.execute("ALTER TABLE detected_events DROP CONSTRAINT IF EXISTS fk_detected_events_llm_label_id")
    op.execute("ALTER TABLE detected_events DROP CONSTRAINT IF EXISTS fk_detected_events_news_article_id")

    # FK constraints — symbol_id
    op.execute("ALTER TABLE paper_positions DROP CONSTRAINT IF EXISTS fk_paper_positions_symbol_id")
    op.execute("ALTER TABLE paper_orders DROP CONSTRAINT IF EXISTS fk_paper_orders_symbol_id")
    op.execute("ALTER TABLE alerts DROP CONSTRAINT IF EXISTS fk_alerts_symbol_id")
    op.execute("ALTER TABLE signal_candidates DROP CONSTRAINT IF EXISTS fk_signal_candidates_symbol_id")
    op.execute("ALTER TABLE detected_events DROP CONSTRAINT IF EXISTS fk_detected_events_symbol_id")
