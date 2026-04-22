"""Freshness helpers for market data used by selection and execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import settings


def market_data_cutoff(now: datetime | None = None) -> datetime:
    """Return the oldest quote/bar timestamp allowed for trading decisions."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference.astimezone(UTC) - timedelta(minutes=settings.market_data_max_age_minutes)
