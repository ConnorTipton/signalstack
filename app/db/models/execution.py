from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class Alert(Base):
    """Decision-ready alert matching the §16 template."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index(
            "uq_alerts_signal_candidate_id",
            "signal_candidate_id",
            unique=True,
            postgresql_where=text("signal_candidate_id IS NOT NULL"),
            sqlite_where=text("signal_candidate_id IS NOT NULL"),
        ),
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_sent_at", "sent_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_candidate_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("signal_candidates.id", ondelete="SET NULL"), nullable=True
    )
    symbol_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("symbols.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    contract_symbol: Mapped[str | None] = mapped_column(String(30), nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    strike: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(4), nullable=True)
    entry_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation: Mapped[str | None] = mapped_column(Text, nullable=True)
    target1: Mapped[str | None] = mapped_column(Text, nullable=True)
    target2: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_stop: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    liquidity_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        Index(
            "uq_paper_orders_alert_id",
            "alert_id",
            unique=True,
            postgresql_where=text("alert_id IS NOT NULL"),
            sqlite_where=text("alert_id IS NOT NULL"),
        ),
        Index("ix_paper_orders_created_at", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'submitted', 'filled', 'cancelled', 'rejected', 'submit_failed')",
            name="ck_paper_orders_status",
        ),
        CheckConstraint("side IN ('buy', 'sell')", name="ck_paper_orders_side"),
        CheckConstraint("option_type IN ('call', 'put')", name="ck_paper_orders_option_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True
    )
    symbol_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("symbols.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    contract_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    option_type: Mapped[str] = mapped_column(String(4), nullable=False)
    strike: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    order_type: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'limit'")
    )
    limit_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    alpaca_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        Index("ix_paper_positions_opened_at", "opened_at"),
        Index("ix_paper_positions_closed_at", "closed_at"),
        CheckConstraint("status IN ('open', 'closed')", name="ck_paper_positions_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True
    )
    alert_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True
    )
    symbol_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("symbols.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    contract_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    option_type: Mapped[str] = mapped_column(String(4), nullable=False)
    strike: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    target1_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    target2_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    invalidation_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    time_stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PositionEvent(Base):
    __tablename__ = "position_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    price_at_event: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_alerts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_paper_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_positions_closed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    winning_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    losing_positions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_pnl: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    avg_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    alerts_by_grade: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
