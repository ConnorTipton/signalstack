"""Pydantic models for replay report structures."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReplayEvent(BaseModel):
    """A single pipeline event, normalized for timeline display."""

    event_time: datetime
    # news_article | detected_event | signal_candidate | alert | position_open | position_close
    event_kind: str
    ticker: str | None = None
    source_name: str | None = None
    source_tier: int | None = None
    row_id: int
    details: dict = {}


class DetectorPostmortem(BaseModel):
    """Per-detector summary: how many events fired and how many led downstream."""

    detector: str
    total_events: int
    events_that_led_to_signal: int
    events_that_led_to_alert: int


class ProviderSourceTrace(BaseModel):
    """Traces a normalized news article back to the raw provider table that supplied it."""

    article_id: int
    provider_name: str
    source_tier: int
    provider_event_id: str | None = None
    raw_table: str | None = None
    raw_event_id: int | None = None
    received_at: datetime | None = None


class ReplayReport(BaseModel):
    """Full replay report for a time window."""

    window_start: datetime
    window_end: datetime
    tickers: list[str]
    total_news_articles: int
    total_detected_events: int
    total_signal_candidates: int
    total_alerts_sent: int
    total_positions_opened: int
    total_positions_closed: int
    realized_pnl: float
    win_rate: float | None
    timeline: list[ReplayEvent]
    detector_postmortems: list[DetectorPostmortem]
    provider_traces: list[ProviderSourceTrace]
