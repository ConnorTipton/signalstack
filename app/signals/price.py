"""Detector B — Price confirmation detector.

Evaluates 1-minute bars for one of four patterns triggered by a news event:

  bullish (polarity="positive"):
    first_5m_high_break  — close exceeds the high of the first 5 bars
    vwap_reclaim         — two consecutive closes above VWAP

  bearish (polarity="negative"):
    support_loss         — close breaks below the low of the first 5 bars
    failed_bounce        — price bounces then reverses below the opening bar

The detector is stateless: evaluate() takes a plain list of BarSnapshot
objects and returns a PriceConfirmation or None, with no DB dependencies.

The worker polls detected_events for unmatched Detector A rows, fetches bars,
calls evaluate(), and writes the result.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, aliased

from app.db.models.market import UnderlyingBar1m
from app.db.models.signals import DetectedEvent
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 30.0
_DEFAULT_BATCH = 50
_LOOKBACK_BARS = 5  # bars used to establish the reference level
_WINDOW_MINUTES = 30  # how far ahead to fetch bars after the news event


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class BarSnapshot:
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    vwap: float | None


@dataclass
class PriceConfirmation:
    pattern: str  # first_5m_high_break | vwap_reclaim | support_loss | failed_bounce
    polarity: str  # positive | negative
    confidence: float  # 0.0–1.0
    importance: float  # magnitude of total move normalised to 0.0–1.0
    reference_level: float  # price level that was broken (ref_high / ref_low / vwap / open)
    trigger_price: float  # the close that confirmed the pattern
    trigger_bar_index: int  # index in the bars list of the confirming bar


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class PriceDetector:
    """Stateless price-confirmation detector.

    Call evaluate() with at least MIN_BARS_NEEDED BarSnapshots and the
    polarity from the triggering news event.  Returns the first matching
    PriceConfirmation, or None when no pattern fires.
    """

    MIN_BARS_NEEDED = _LOOKBACK_BARS + 1  # 5 reference bars + 1 confirmation bar

    def evaluate(
        self,
        bars: list[BarSnapshot],
        polarity: str,
    ) -> PriceConfirmation | None:
        """Return the first confirmation found, or None."""
        if len(bars) < self.MIN_BARS_NEEDED:
            return None
        if polarity == "positive":
            return self._check_first_5m_high_break(bars) or self._check_vwap_reclaim(bars)
        return self._check_support_loss(bars) or self._check_failed_bounce(bars)

    @staticmethod
    def _check_first_5m_high_break(bars: list[BarSnapshot]) -> PriceConfirmation | None:
        ref_high = max(b.high for b in bars[:_LOOKBACK_BARS])
        for i, bar in enumerate(bars[_LOOKBACK_BARS:], start=_LOOKBACK_BARS):
            if bar.close > ref_high:
                magnitude = (bar.close - ref_high) / ref_high
                return PriceConfirmation(
                    pattern="first_5m_high_break",
                    polarity="positive",
                    confidence=min(1.0, 0.5 + magnitude * 10),
                    importance=min(1.0, abs(bar.close - bars[0].open) / bars[0].open * 20),
                    reference_level=ref_high,
                    trigger_price=bar.close,
                    trigger_bar_index=i,
                )
        return None

    @staticmethod
    def _check_vwap_reclaim(bars: list[BarSnapshot]) -> PriceConfirmation | None:
        for i in range(len(bars) - 1):
            bar, nxt = bars[i], bars[i + 1]
            if bar.vwap is None or nxt.vwap is None:
                continue
            if bar.close > bar.vwap and nxt.close > nxt.vwap:
                return PriceConfirmation(
                    pattern="vwap_reclaim",
                    polarity="positive",
                    confidence=0.7,
                    importance=min(1.0, abs(nxt.close - bars[0].open) / bars[0].open * 20),
                    reference_level=bar.vwap,
                    trigger_price=nxt.close,
                    trigger_bar_index=i + 1,
                )
        return None

    @staticmethod
    def _check_support_loss(bars: list[BarSnapshot]) -> PriceConfirmation | None:
        ref_low = min(b.low for b in bars[:_LOOKBACK_BARS])
        for i, bar in enumerate(bars[_LOOKBACK_BARS:], start=_LOOKBACK_BARS):
            if bar.close < ref_low:
                magnitude = (ref_low - bar.close) / ref_low
                return PriceConfirmation(
                    pattern="support_loss",
                    polarity="negative",
                    confidence=min(1.0, 0.5 + magnitude * 10),
                    importance=min(1.0, abs(bar.close - bars[0].open) / bars[0].open * 20),
                    reference_level=ref_low,
                    trigger_price=bar.close,
                    trigger_bar_index=i,
                )
        return None

    @staticmethod
    def _check_failed_bounce(bars: list[BarSnapshot]) -> PriceConfirmation | None:
        first_open = bars[0].open
        bounced = False
        for i, bar in enumerate(bars[1:], start=1):
            if bar.high > first_open * 1.002:  # at least 0.2 % above open
                bounced = True
            if bounced and bar.close < first_open:
                return PriceConfirmation(
                    pattern="failed_bounce",
                    polarity="negative",
                    confidence=0.65,
                    importance=min(1.0, abs(bar.close - first_open) / first_open * 20),
                    reference_level=first_open,
                    trigger_price=bar.close,
                    trigger_bar_index=i,
                )
        return None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class PriceDetectorWorker:
    """Async loop that drives PriceDetector on a fixed interval.

    Parameters
    ----------
    detector:
        PriceDetector instance. Defaults to a plain PriceDetector().
    interval_seconds:
        Seconds between detection cycles. Default 30.
    batch_size:
        Max Detector A events to process per cycle. Default 50.
    window_minutes:
        How many minutes of bars to fetch after the news event. Default 30.
    """

    def __init__(
        self,
        detector: PriceDetector | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        batch_size: int = _DEFAULT_BATCH,
        window_minutes: int = _WINDOW_MINUTES,
    ) -> None:
        self._detector = detector or PriceDetector()
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._window_minutes = window_minutes

    async def run(self) -> None:
        """Main loop: run detector, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                count = await asyncio.to_thread(self._run_once_in_session)
                if count:
                    log.info("PriceDetector: emitted %d event(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("PriceDetector cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def _run_once_in_session(self) -> int:
        with SessionLocal() as db:
            return self.run_once(db)

    def run_once(self, db: Session) -> int:
        """Emit Detector B events for all unmatched Detector A events.

        Returns the number of events written.
        """
        news_events = self._fetch_unmatched_news_events(db, batch_size=self._batch_size)
        count = 0
        for news_event in news_events:
            bars = self._fetch_bars(
                db, news_event.symbol_id, news_event.detected_at, self._window_minutes
            )
            confirmation = self._detector.evaluate(bars, news_event.polarity or "positive")
            if confirmation is None:
                continue
            db.add(self._build_detected_event(news_event, confirmation))
            count += 1
        db.commit()
        return count

    # ------------------------------------------------------------------
    # Pure helper — testable without a DB
    # ------------------------------------------------------------------

    @staticmethod
    def _build_detected_event(news_event: DetectedEvent, conf: PriceConfirmation) -> DetectedEvent:
        return DetectedEvent(
            detector="B",
            symbol_id=news_event.symbol_id,
            ticker=news_event.ticker,
            event_type=conf.pattern,
            polarity=conf.polarity,
            importance=conf.importance,
            confidence=conf.confidence,
            source_tier=news_event.source_tier,
            # news_article_id acts as idempotency key: one B event per (article, symbol)
            news_article_id=news_event.news_article_id,
            metadata_json={
                "news_event_id": news_event.id,
                "pattern": conf.pattern,
                "reference_level": conf.reference_level,
                "trigger_price": conf.trigger_price,
                "trigger_bar_index": conf.trigger_bar_index,
            },
        )

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_unmatched_news_events(
        db: Session,
        batch_size: int = _DEFAULT_BATCH,
    ) -> list[DetectedEvent]:
        """Return Detector A events that have no matching Detector B event yet.

        Idempotency is keyed on (news_article_id, symbol_id): Detector B writes
        news_article_id onto its own row so we can check for existence cheaply
        without touching metadata_json.
        """
        det_b = aliased(DetectedEvent)
        already_matched = (
            db.query(det_b.id)
            .filter(
                det_b.detector == "B",
                det_b.news_article_id == DetectedEvent.news_article_id,
                det_b.symbol_id == DetectedEvent.symbol_id,
            )
            .exists()
        )
        return (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detector == "A",
                DetectedEvent.news_article_id.isnot(None),
                ~already_matched,
            )
            .order_by(DetectedEvent.detected_at)
            .limit(batch_size)
            .all()
        )

    @staticmethod
    def _fetch_bars(
        db: Session,
        symbol_id: int,
        since: datetime,
        window_minutes: int,
    ) -> list[BarSnapshot]:
        until = since + timedelta(minutes=window_minutes)
        rows = (
            db.query(UnderlyingBar1m)
            .filter(
                UnderlyingBar1m.symbol_id == symbol_id,
                UnderlyingBar1m.bar_time >= since,
                UnderlyingBar1m.bar_time < until,
            )
            .order_by(UnderlyingBar1m.bar_time)
            .all()
        )
        return [
            BarSnapshot(
                bar_time=r.bar_time,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                vwap=float(r.vwap) if r.vwap is not None else None,
            )
            for r in rows
        ]
