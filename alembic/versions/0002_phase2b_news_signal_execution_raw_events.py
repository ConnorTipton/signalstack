"""Phase 2b: news, signal, execution, and raw event tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_RAW_MARKET_HYPERTABLES = [
    ("raw_tradier_events", "received_at"),
    ("raw_alpaca_market_events", "received_at"),
]

_DROP_ORDER = [
    "position_events",
    "paper_positions",
    "paper_orders",
    "alerts",
    "signal_candidates",
    "detected_events",
    "llm_news_labels",
    "news_article_tickers",
    "news_articles",
    "daily_metrics",
    "raw_news_backup_events",
    "raw_marketaux_events",
    "raw_official_news_events",
    "raw_alpaca_market_events",
    "raw_tradier_events",
]


def upgrade() -> None:
    # --- News tables ---

    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column("source_tier", sa.Integer(), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("related_url", sa.Text(), nullable=True),
        sa.Column("normalization_version", sa.String(20), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("duplicate_of_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Dedupe indexes — partial so NULLs are excluded from uniqueness check.
    op.create_index(
        "uq_news_articles_source_event_id",
        "news_articles",
        ["source_name", "provider_event_id"],
        unique=True,
        postgresql_where=sa.text("provider_event_id IS NOT NULL"),
    )
    op.create_index(
        "uq_news_articles_content_hash",
        "news_articles",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )

    op.create_table(
        "news_article_tickers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_news_article_tickers_article_id", "news_article_tickers", ["article_id"])
    op.create_index(
        "uq_news_article_tickers_article_ticker",
        "news_article_tickers",
        ["article_id", "ticker"],
        unique=True,
    )

    op.create_table(
        "llm_news_labels",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=True),
        sa.Column("polarity", sa.String(10), nullable=True),
        sa.Column("importance", sa.Numeric(4, 3), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("one_sentence_summary", sa.Text(), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_llm_news_labels_article_id", "llm_news_labels", ["article_id"])

    # --- Signal tables ---

    op.create_table(
        "detected_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("detector", sa.String(1), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=True),
        sa.Column("polarity", sa.String(10), nullable=True),
        sa.Column("importance", sa.Numeric(4, 3), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("source_tier", sa.Integer(), nullable=True),
        sa.Column("one_sentence_summary", sa.Text(), nullable=True),
        sa.Column("news_article_id", sa.BigInteger(), nullable=True),
        sa.Column("llm_label_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detected_events_symbol_id", "detected_events", ["symbol_id"])

    op.create_table(
        "signal_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("news_event_id", sa.BigInteger(), nullable=True),
        sa.Column("price_event_id", sa.BigInteger(), nullable=True),
        sa.Column("options_event_id", sa.BigInteger(), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("news_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("price_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("options_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("liquidity_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("data_confidence_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("provider_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("grade", sa.String(3), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runtime_mode", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signal_candidates_symbol_id", "signal_candidates", ["symbol_id"])

    # --- Execution tables ---

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("signal_candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("grade", sa.String(3), nullable=True),
        sa.Column("contract_symbol", sa.String(30), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("strike", sa.Numeric(10, 2), nullable=True),
        sa.Column("option_type", sa.String(4), nullable=True),
        sa.Column("entry_condition", sa.Text(), nullable=True),
        sa.Column("invalidation", sa.Text(), nullable=True),
        sa.Column("target1", sa.Text(), nullable=True),
        sa.Column("target2", sa.Text(), nullable=True),
        sa.Column("time_stop", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("liquidity_note", sa.Text(), nullable=True),
        sa.Column("data_note", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_symbol_id", "alerts", ["symbol_id"])

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("alert_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("contract_symbol", sa.String(30), nullable=False),
        sa.Column("option_type", sa.String(4), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "order_type", sa.String(10), nullable=False, server_default=sa.text("'limit'")
        ),
        sa.Column("limit_price", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("alpaca_order_id", sa.String(100), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fill_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_orders_symbol_id", "paper_orders", ["symbol_id"])

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("alert_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("contract_symbol", sa.String(30), nullable=False),
        sa.Column("option_type", sa.String(4), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(10, 4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
        sa.Column("target1_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("target2_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("invalidation_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("time_stop_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_positions_symbol_id", "paper_positions", ["symbol_id"])

    op.create_table(
        "position_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("price_at_event", sa.Numeric(10, 4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["position_id"], ["paper_positions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_position_events_position_id", "position_events", ["position_id"])

    op.create_table(
        "daily_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("total_signals", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_alerts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "total_paper_orders", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "total_positions_closed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "winning_positions", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "losing_positions", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("total_pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("avg_score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "alerts_by_grade",
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
        sa.UniqueConstraint("metric_date"),
    )

    # --- Raw market event tables (hypertables) ---

    op.create_table(
        "raw_tradier_events",
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "source_name",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'tradier'"),
        ),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalization_version", sa.String(20), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("received_at", "id"),
    )

    op.create_table(
        "raw_alpaca_market_events",
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "source_name",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'alpaca_market'"),
        ),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalization_version", sa.String(20), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("received_at", "id"),
    )

    for table, time_col in _RAW_MARKET_HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', '{time_col}', if_not_exists => TRUE)"
        )

    # --- Raw news event tables (regular tables with dedupe indexes) ---

    _news_raw_cols = [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_name", sa.String(50), nullable=False),
        sa.Column("source_tier", sa.Integer(), nullable=False),
        sa.Column("provider_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("related_url", sa.Text(), nullable=True),
        sa.Column("normalization_version", sa.String(20), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]

    for table_name, default_tier in [
        ("raw_official_news_events", 1),
        ("raw_marketaux_events", 2),
        ("raw_news_backup_events", 3),
    ]:
        # Rebuild column list with per-table source_tier default.
        cols = [
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("source_name", sa.String(50), nullable=False),
            sa.Column(
                "source_tier",
                sa.Integer(),
                nullable=False,
                server_default=sa.text(str(default_tier)),
            ),
            sa.Column("provider_confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("provider_event_id", sa.String(255), nullable=True),
            sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("related_url", sa.Text(), nullable=True),
            sa.Column("normalization_version", sa.String(20), nullable=True),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        ]
        op.create_table(table_name, *cols)
        op.create_index(
            f"uq_{table_name}_source_event_id",
            table_name,
            ["source_name", "provider_event_id"],
            unique=True,
            postgresql_where=sa.text("provider_event_id IS NOT NULL"),
        )
        op.create_index(
            f"uq_{table_name}_content_hash",
            table_name,
            ["content_hash"],
            unique=True,
            postgresql_where=sa.text("content_hash IS NOT NULL"),
        )


def downgrade() -> None:
    for table in _DROP_ORDER:
        op.drop_table(table)
