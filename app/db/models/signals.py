from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DetectedEvent(Base):
    """Output of a single detector run (A=news, B=price, C=options)."""

    __tablename__ = "detected_events"
    __table_args__ = (
        Index(
            "uq_detected_events_detector_article_symbol",
            "detector",
            "news_article_id",
            "symbol_id",
            unique=True,
            postgresql_where=text("news_article_id IS NOT NULL"),
            sqlite_where=text("news_article_id IS NOT NULL"),
        ),
        Index("ix_detected_events_detected_at", "detected_at"),
        CheckConstraint("detector IN ('A', 'B', 'C')", name="ck_detected_events_detector"),
        CheckConstraint(
            "polarity IN ('bullish', 'neutral', 'bearish')", name="ck_detected_events_polarity"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    detector: Mapped[str] = mapped_column(String(1), nullable=False)
    symbol_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("symbols.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    polarity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    importance: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    source_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    one_sentence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_article_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news_articles.id", ondelete="SET NULL"), nullable=True
    )
    llm_label_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("llm_news_labels.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SignalCandidate(Base):
    """Scored combination of A+B+C detector outputs for a single ticker."""

    __tablename__ = "signal_candidates"
    __table_args__ = (
        Index(
            "uq_signal_candidates_news_event_id",
            "news_event_id",
            unique=True,
            postgresql_where=text("news_event_id IS NOT NULL"),
            sqlite_where=text("news_event_id IS NOT NULL"),
        ),
        Index("ix_signal_candidates_status_contract_symbol", "status", "contract_symbol"),
        Index("ix_signal_candidates_created_at", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'promoted', 'watch', 'rejected')",
            name="ck_signal_candidates_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("symbols.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    news_event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("detected_events.id", ondelete="SET NULL"), nullable=True
    )
    price_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    options_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    news_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    price_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    options_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    liquidity_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    data_confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    provider_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Contract selection (Phase 6)
    contract_symbol: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contract_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_strike: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    contract_type: Mapped[str | None] = mapped_column(String(4), nullable=True)
    contract_bid: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    contract_ask: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    contract_spread_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    contract_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_rejection_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    contract_selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
