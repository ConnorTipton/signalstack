"""EventPlayer — reads normalized pipeline events from the DB for a time window.

All methods are read-only. Each accepts a Session so callers can inject a mock
or a real session without any internal coupling to SessionLocal.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.execution import Alert, PaperPosition
from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawMarketauxEvent, RawOfficialNewsEvent
from app.db.models.signals import DetectedEvent, SignalCandidate
from app.replay.report import DetectorPostmortem, ProviderSourceTrace, ReplayEvent

log = logging.getLogger(__name__)


class EventPlayer:
    """Stateless reader that assembles replay data from normalized tables.

    All public methods return plain lists of Pydantic models — no side effects,
    no writes, no commits.
    """

    def load_events(
        self,
        db: Session,
        window_start: datetime,
        window_end: datetime,
        tickers: list[str] | None = None,
    ) -> list[ReplayEvent]:
        """Return every pipeline event in the window, sorted chronologically."""
        events: list[ReplayEvent] = []
        events.extend(self._load_news(db, window_start, window_end, tickers))
        events.extend(self._load_detected(db, window_start, window_end, tickers))
        events.extend(self._load_signals(db, window_start, window_end, tickers))
        events.extend(self._load_alerts(db, window_start, window_end, tickers))
        events.extend(self._load_positions(db, window_start, window_end, tickers))
        events.sort(key=lambda e: e.event_time)
        return events

    def build_postmortems(
        self,
        db: Session,
        window_start: datetime,
        window_end: datetime,
        tickers: list[str] | None = None,
    ) -> list[DetectorPostmortem]:
        """Per-detector stats: total events, how many reached a signal/alert."""
        q = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= window_start,
            DetectedEvent.detected_at <= window_end,
        )
        if tickers:
            q = q.filter(DetectedEvent.ticker.in_(tickers))
        detected = q.all()
        if not detected:
            return []

        ev_ids = [e.id for e in detected]
        candidates = (
            db.query(SignalCandidate)
            .filter(
                or_(
                    SignalCandidate.news_event_id.in_(ev_ids),
                    SignalCandidate.price_event_id.in_(ev_ids),
                    SignalCandidate.options_event_id.in_(ev_ids),
                )
            )
            .all()
        )

        news_in_signal = {c.news_event_id for c in candidates if c.news_event_id}
        price_in_signal = {c.price_event_id for c in candidates if c.price_event_id}
        opts_in_signal = {c.options_event_id for c in candidates if c.options_event_id}

        news_in_alert: set[int] = set()
        price_in_alert: set[int] = set()
        opts_in_alert: set[int] = set()
        promoted_ids = {c.id for c in candidates if c.status == "promoted"}
        if promoted_ids:
            alerts = (
                db.query(Alert)
                .filter(Alert.signal_candidate_id.in_(promoted_ids))
                .all()
            )
            alerted_ids = {a.signal_candidate_id for a in alerts if a.signal_candidate_id}
            for c in candidates:
                if c.id in alerted_ids:
                    if c.news_event_id:
                        news_in_alert.add(c.news_event_id)
                    if c.price_event_id:
                        price_in_alert.add(c.price_event_id)
                    if c.options_event_id:
                        opts_in_alert.add(c.options_event_id)

        by_detector: defaultdict[str, list[int]] = defaultdict(list)
        for ev in detected:
            by_detector[ev.detector].append(ev.id)

        postmortems = []
        for det, ids in sorted(by_detector.items()):
            id_set = set(ids)
            if det == "A":
                in_signal = len(id_set & news_in_signal)
                in_alert = len(id_set & news_in_alert)
            elif det == "B":
                in_signal = len(id_set & price_in_signal)
                in_alert = len(id_set & price_in_alert)
            elif det == "C":
                in_signal = len(id_set & opts_in_signal)
                in_alert = len(id_set & opts_in_alert)
            else:
                in_signal = 0
                in_alert = 0
            postmortems.append(
                DetectorPostmortem(
                    detector=det,
                    total_events=len(ids),
                    events_that_led_to_signal=in_signal,
                    events_that_led_to_alert=in_alert,
                )
            )

        return postmortems

    def build_source_traces(
        self,
        db: Session,
        window_start: datetime,
        window_end: datetime,
        tickers: list[str] | None = None,
    ) -> list[ProviderSourceTrace]:
        """Trace normalized news articles back to the raw provider table that supplied them."""
        q = db.query(NewsArticle).filter(
            NewsArticle.created_at >= window_start,
            NewsArticle.created_at <= window_end,
        )
        if tickers:
            article_ids_sq = db.query(NewsArticleTicker.article_id).filter(
                NewsArticleTicker.ticker.in_(tickers)
            )
            q = q.filter(NewsArticle.id.in_(article_ids_sq))
        return [self._trace_article(db, a) for a in q.all()]

    # ------------------------------------------------------------------
    # Private loaders — one per event kind
    # ------------------------------------------------------------------

    def _load_news(
        self, db: Session, start: datetime, end: datetime, tickers: list[str] | None
    ) -> list[ReplayEvent]:
        q = db.query(NewsArticle).filter(
            NewsArticle.created_at >= start,
            NewsArticle.created_at <= end,
        )
        if tickers:
            sq = db.query(NewsArticleTicker.article_id).filter(
                NewsArticleTicker.ticker.in_(tickers)
            )
            q = q.filter(NewsArticle.id.in_(sq))
        return [
            ReplayEvent(
                event_time=a.created_at,
                event_kind="news_article",
                source_name=a.source_name,
                source_tier=a.source_tier,
                row_id=a.id,
                details={"title": a.title[:120], "is_duplicate": a.is_duplicate},
            )
            for a in q.all()
        ]

    def _load_detected(
        self, db: Session, start: datetime, end: datetime, tickers: list[str] | None
    ) -> list[ReplayEvent]:
        q = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= start,
            DetectedEvent.detected_at <= end,
        )
        if tickers:
            q = q.filter(DetectedEvent.ticker.in_(tickers))
        return [
            ReplayEvent(
                event_time=e.detected_at,
                event_kind="detected_event",
                ticker=e.ticker,
                source_tier=e.source_tier,
                row_id=e.id,
                details={
                    "detector": e.detector,
                    "event_type": e.event_type,
                    "polarity": e.polarity,
                    "importance": float(e.importance) if e.importance is not None else None,
                    "confidence": float(e.confidence) if e.confidence is not None else None,
                },
            )
            for e in q.all()
        ]

    def _load_signals(
        self, db: Session, start: datetime, end: datetime, tickers: list[str] | None
    ) -> list[ReplayEvent]:
        q = db.query(SignalCandidate).filter(
            SignalCandidate.created_at >= start,
            SignalCandidate.created_at <= end,
        )
        if tickers:
            q = q.filter(SignalCandidate.ticker.in_(tickers))
        return [
            ReplayEvent(
                event_time=sc.created_at,
                event_kind="signal_candidate",
                ticker=sc.ticker,
                row_id=sc.id,
                details={
                    "score": float(sc.score) if sc.score is not None else None,
                    "grade": sc.grade,
                    "status": sc.status,
                    "rejection_reason": sc.rejection_reason,
                },
            )
            for sc in q.all()
        ]

    def _load_alerts(
        self, db: Session, start: datetime, end: datetime, tickers: list[str] | None
    ) -> list[ReplayEvent]:
        q = db.query(Alert).filter(
            Alert.created_at >= start,
            Alert.created_at <= end,
        )
        if tickers:
            q = q.filter(Alert.ticker.in_(tickers))
        return [
            ReplayEvent(
                event_time=a.created_at,
                event_kind="alert",
                ticker=a.ticker,
                row_id=a.id,
                details={
                    "score": float(a.score),
                    "grade": a.grade,
                    "sent": a.sent_at is not None,
                },
            )
            for a in q.all()
        ]

    def _load_positions(
        self, db: Session, start: datetime, end: datetime, tickers: list[str] | None
    ) -> list[ReplayEvent]:
        events: list[ReplayEvent] = []

        q_open = db.query(PaperPosition).filter(
            PaperPosition.opened_at >= start,
            PaperPosition.opened_at <= end,
        )
        if tickers:
            q_open = q_open.filter(PaperPosition.ticker.in_(tickers))
        for p in q_open.all():
            events.append(
                ReplayEvent(
                    event_time=p.opened_at,
                    event_kind="position_open",
                    ticker=p.ticker,
                    row_id=p.id,
                    details={
                        "contract_symbol": p.contract_symbol,
                        "entry_price": float(p.entry_price),
                    },
                )
            )

        q_close = db.query(PaperPosition).filter(
            PaperPosition.closed_at >= start,
            PaperPosition.closed_at <= end,
            PaperPosition.status == "closed",
        )
        if tickers:
            q_close = q_close.filter(PaperPosition.ticker.in_(tickers))
        for p in q_close.all():
            if p.closed_at is None:
                continue
            events.append(
                ReplayEvent(
                    event_time=p.closed_at,
                    event_kind="position_close",
                    ticker=p.ticker,
                    row_id=p.id,
                    details={
                        "exit_reason": p.exit_reason,
                        "exit_price": float(p.exit_price or 0),
                        "pnl": float(p.pnl or 0),
                        "pnl_pct": float(p.pnl_pct or 0),
                    },
                )
            )

        return events

    def _trace_article(self, db: Session, article: NewsArticle) -> ProviderSourceTrace:
        raw_table = None
        raw_id = None
        if article.provider_event_id:
            if article.source_tier == 1:
                raw = (
                    db.query(RawOfficialNewsEvent)
                    .filter(
                        RawOfficialNewsEvent.provider_event_id == article.provider_event_id
                    )
                    .first()
                )
                if raw:
                    raw_table = "raw_official_news_events"
                    raw_id = raw.id
            elif article.source_tier == 2:
                raw = (
                    db.query(RawMarketauxEvent)
                    .filter(
                        RawMarketauxEvent.provider_event_id == article.provider_event_id
                    )
                    .first()
                )
                if raw:
                    raw_table = "raw_marketaux_events"
                    raw_id = raw.id

        return ProviderSourceTrace(
            article_id=article.id,
            provider_name=article.source_name,
            source_tier=article.source_tier,
            provider_event_id=article.provider_event_id,
            raw_table=raw_table,
            raw_event_id=raw_id,
            received_at=article.received_at,
        )
