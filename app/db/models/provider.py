from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    runtime_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    priority_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderHealth(Base):
    """Time-series log of provider health checks. Hypertable partitioned on checked_at."""

    __tablename__ = "provider_health"
    __table_args__ = (Index("ix_provider_health_name_checked_at", "provider_name", "checked_at"),)

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lag_seconds: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
