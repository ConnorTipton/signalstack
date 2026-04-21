"""ScenarioRunner — orchestrates a replay run and assembles the ReplayReport."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.replay.event_player import EventPlayer
from app.replay.report import ReplayReport


class ScenarioRunner:
    """Runs a full replay for a time window and returns a structured report.

    Parameters
    ----------
    player:
        EventPlayer instance. If None, a default is created. Pass a mock here
        for testing without a real DB.
    """

    def __init__(self, player: EventPlayer | None = None) -> None:
        self._player = player or EventPlayer()

    def run(
        self,
        db: Session,
        window_start: datetime,
        window_end: datetime,
        tickers: list[str] | None = None,
        max_timeline_events: int = 1000,
    ) -> ReplayReport:
        """Build a ReplayReport for the given window.

        Parameters
        ----------
        db:
            Open SQLAlchemy session.
        window_start / window_end:
            Inclusive UTC bounds for the replay window.
        tickers:
            Optional list of ticker symbols to restrict the report.
            Empty list or None means all tickers.
        max_timeline_events:
            Cap on the number of events included in ``timeline``.
            Summary counts always reflect the full window.
        """
        ticker_list = list(tickers) if tickers else []
        ticker_filter = ticker_list or None

        timeline = self._player.load_events(db, window_start, window_end, ticker_filter)
        postmortems = self._player.build_postmortems(db, window_start, window_end, ticker_filter)
        traces = self._player.build_source_traces(db, window_start, window_end, ticker_filter)

        total_news = sum(1 for e in timeline if e.event_kind == "news_article")
        total_detected = sum(1 for e in timeline if e.event_kind == "detected_event")
        total_signals = sum(1 for e in timeline if e.event_kind == "signal_candidate")
        total_alerts = sum(
            1 for e in timeline if e.event_kind == "alert" and e.details.get("sent")
        )
        total_pos_open = sum(1 for e in timeline if e.event_kind == "position_open")
        close_events = [e for e in timeline if e.event_kind == "position_close"]
        total_pos_close = len(close_events)

        realized_pnl = sum(e.details.get("pnl", 0.0) for e in close_events)
        winning = sum(1 for e in close_events if e.details.get("pnl", 0.0) > 0)
        win_rate = (winning / total_pos_close) if total_pos_close else None

        return ReplayReport(
            window_start=window_start,
            window_end=window_end,
            tickers=ticker_list,
            total_news_articles=total_news,
            total_detected_events=total_detected,
            total_signal_candidates=total_signals,
            total_alerts_sent=total_alerts,
            total_positions_opened=total_pos_open,
            total_positions_closed=total_pos_close,
            realized_pnl=realized_pnl,
            win_rate=win_rate,
            timeline=timeline[:max_timeline_events],
            detector_postmortems=postmortems,
            provider_traces=traces,
        )
