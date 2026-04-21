"""Raw provider payload tables — store first, normalize second (blueprint §20.B)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ---------------------------------------------------------------------------
# Market raw event tables (high-volume streaming) — TimescaleDB hypertables.
# Composite PK includes the time column as required by TimescaleDB.
# ---------------------------------------------------------------------------


class RawTradierEvent(Base):
    __tablename__ = "raw_tradier_events"

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_name: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'tradier'")
    )
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    normalization_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RawAlpacaMarketEvent(Base):
    __tablename__ = "raw_alpaca_market_events"

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_name: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'alpaca_market'")
    )
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    normalization_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


# ---------------------------------------------------------------------------
# News raw event tables (lower-volume polling) — regular tables with full
# §11 metadata fields for dedupe and source tracing.
# ---------------------------------------------------------------------------


class RawOfficialNewsEvent(Base):
    __tablename__ = "raw_official_news_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_tier: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    provider_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RawMarketauxEvent(Base):
    __tablename__ = "raw_marketaux_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'marketaux'")
    )
    source_tier: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    provider_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RawNewsBackupEvent(Base):
    __tablename__ = "raw_news_backup_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_tier: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    provider_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
