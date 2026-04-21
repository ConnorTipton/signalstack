from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Identity, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnderlyingBar1m(Base):
    """1-minute OHLCV bars. Hypertable partitioned on bar_time."""

    __tablename__ = "underlying_bars_1m"

    # Natural composite PK satisfies TimescaleDB (time column included).
    bar_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    symbol_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    vwap: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UnderlyingQuote(Base):
    """Streaming best-bid/offer quotes. Hypertable partitioned on quote_time."""

    __tablename__ = "underlying_quotes"

    quote_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    symbol_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bid: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    ask: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OptionQuote(Base):
    """Streaming option contract quotes. Hypertable partitioned on quote_time."""

    __tablename__ = "option_quotes"

    quote_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    symbol_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    contract_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    option_type: Mapped[str] = mapped_column(String(4), nullable=False)
    bid: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    ask: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    implied_volatility: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    delta: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OptionTrade(Base):
    """Printed option trades. Hypertable partitioned on trade_time."""

    __tablename__ = "option_trades"

    trade_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    symbol_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    contract_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    option_type: Mapped[str] = mapped_column(String(4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OptionChainSnapshot(Base):
    """Periodic summary of an option chain for one expiration. Hypertable on snapshot_time."""

    __tablename__ = "option_chain_snapshots"

    snapshot_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    symbol_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    contract_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_call_oi: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_put_oi: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_call_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_put_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
