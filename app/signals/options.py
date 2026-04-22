"""Detector C — Options abnormality detector.

Runs in two modes driven by provider_confidence from ProviderHealth:

  Full mode  (provider_confidence >= 0.70, enough trade data available)
    Rule: notional_lean — call/put split by notional value (price × size).
    Source: option_trades in the window after the news event.
    Confidence: 0.60–1.0 scaled by lean strength.

  Proxy mode (fallback when provider_confidence < 0.70 or too few trades)
    Rule: chain_volume_lean — call/put split from option_chain_snapshots.
    Source: most recent option_chain_snapshot for the symbol.
    Confidence: 0.45–0.75 (capped below full mode per blueprint §14).

The detector is stateless: evaluate() takes plain dataclasses with no DB
dependencies.  The worker handles all DB queries and idempotency.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session, aliased

from app.db.models.market import OptionChainSnapshot, OptionTrade
from app.db.models.provider import ProviderHealth
from app.db.models.signals import DetectedEvent
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 30.0
_DEFAULT_BATCH = 50
_WINDOW_MINUTES = 30

# Thresholds
_CALL_BULLISH_THRESHOLD = 0.65  # call fraction >= this → bullish
_PUT_BEARISH_THRESHOLD = 0.35  # call fraction <= this → bearish
_MIN_FULL_TRADES = 5  # minimum trades to attempt full mode
_MIN_PROXY_VOLUME = 50  # minimum combined chain volume for proxy
_FULL_MODE_CONFIDENCE_MIN = 0.70  # provider_confidence required for full mode


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class OptionTradeSnapshot:
    trade_time: datetime
    option_type: str  # "call" | "put"
    price: float
    size: int
    expiration_date: date
    strike: float


@dataclass
class ChainSnapshot:
    snapshot_time: datetime
    expiration_date: date
    total_call_volume: int
    total_put_volume: int


@dataclass
class OptionsConfirmation:
    mode: str  # "full" | "proxy"
    pattern: str  # "notional_lean_bullish" | "notional_lean_bearish"
    # "chain_volume_lean_bullish" | "chain_volume_lean_bearish"
    polarity: str  # "positive" | "negative"
    confidence: float  # full: 0.60–1.0 | proxy: 0.45–0.75
    importance: float  # 0.0–1.0
    call_fraction: float  # 0.0–1.0 — share of call activity


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class OptionsDetector:
    """Stateless options-abnormality detector.

    Call evaluate() with trade + snapshot lists and the current provider
    confidence.  Returns an OptionsConfirmation or None when no abnormality
    is detected.
    """

    def evaluate(
        self,
        trades: list[OptionTradeSnapshot],
        snapshots: list[ChainSnapshot],
        provider_confidence: float,
    ) -> OptionsConfirmation | None:
        """Return the first detected abnormality, or None.

        Attempts full mode when provider_confidence >= threshold AND there are
        enough trades.  Falls back to proxy mode otherwise.
        """
        if provider_confidence >= _FULL_MODE_CONFIDENCE_MIN:
            result = self._evaluate_full(trades)
            if result is not None:
                return result
        return self._evaluate_proxy(snapshots)

    @staticmethod
    def _evaluate_full(trades: list[OptionTradeSnapshot]) -> OptionsConfirmation | None:
        """Notional lean: call/put split by price × size across all trades."""
        if len(trades) < _MIN_FULL_TRADES:
            return None

        call_notional = sum(t.price * t.size for t in trades if t.option_type == "call")
        put_notional = sum(t.price * t.size for t in trades if t.option_type == "put")
        total_notional = call_notional + put_notional
        if total_notional == 0:
            return None

        call_fraction = call_notional / total_notional

        if call_fraction >= _CALL_BULLISH_THRESHOLD:
            polarity = "positive"
            pattern = "notional_lean_bullish"
        elif call_fraction <= _PUT_BEARISH_THRESHOLD:
            polarity = "negative"
            pattern = "notional_lean_bearish"
        else:
            return None

        # Confidence: 0.60 at threshold, 1.0 at extreme (all calls or all puts)
        lean = abs(call_fraction - 0.5)  # 0.15 at threshold, 0.50 at extreme
        confidence = min(1.0, 0.60 + (lean - 0.15) / 0.35 * 0.40)
        importance = min(1.0, len(trades) / 20.0)

        return OptionsConfirmation(
            mode="full",
            pattern=pattern,
            polarity=polarity,
            confidence=confidence,
            importance=importance,
            call_fraction=call_fraction,
        )

    @staticmethod
    def _evaluate_proxy(snapshots: list[ChainSnapshot]) -> OptionsConfirmation | None:
        """Chain volume lean: call/put split from option_chain_snapshots."""
        if not snapshots:
            return None

        total_call_vol = sum(s.total_call_volume for s in snapshots)
        total_put_vol = sum(s.total_put_volume for s in snapshots)
        total_vol = total_call_vol + total_put_vol

        if total_vol < _MIN_PROXY_VOLUME:
            return None

        call_fraction = total_call_vol / total_vol

        if call_fraction >= _CALL_BULLISH_THRESHOLD:
            polarity = "positive"
            pattern = "chain_volume_lean_bullish"
        elif call_fraction <= _PUT_BEARISH_THRESHOLD:
            polarity = "negative"
            pattern = "chain_volume_lean_bearish"
        else:
            return None

        # Confidence: 0.45 at threshold, capped at 0.75 (proxy is less reliable)
        lean = abs(call_fraction - 0.5)
        confidence = min(0.75, 0.45 + (lean - 0.15) / 0.35 * 0.30)
        importance = min(1.0, total_vol / 500.0)

        return OptionsConfirmation(
            mode="proxy",
            pattern=pattern,
            polarity=polarity,
            confidence=confidence,
            importance=importance,
            call_fraction=call_fraction,
        )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class OptionsDetectorWorker:
    """Async loop that drives OptionsDetector on a fixed interval.

    Parameters
    ----------
    detector:
        OptionsDetector instance. Defaults to a plain OptionsDetector().
    interval_seconds:
        Seconds between detection cycles. Default 30.
    batch_size:
        Max Detector A events to process per cycle. Default 50.
    window_minutes:
        How many minutes of options data to fetch after the news event.
        Default 30.
    options_provider:
        Provider name used to look up provider_confidence in ProviderHealth.
        Default "tradier".
    """

    def __init__(
        self,
        detector: OptionsDetector | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        batch_size: int = _DEFAULT_BATCH,
        window_minutes: int = _WINDOW_MINUTES,
        options_provider: str = "tradier",
    ) -> None:
        self._detector = detector or OptionsDetector()
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._window_minutes = window_minutes
        self._options_provider = options_provider

    async def run(self) -> None:
        """Main loop: run detector, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                count = await asyncio.to_thread(self._run_once_in_session)
                if count:
                    log.info("OptionsDetector: emitted %d event(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("OptionsDetector cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def _run_once_in_session(self) -> int:
        with SessionLocal() as db:
            return self.run_once(db)

    def run_once(self, db: Session) -> int:
        """Emit Detector C events for all unmatched Detector A events.

        Returns the number of events written.
        """
        provider_confidence = self._get_provider_confidence(db)
        news_events = self._fetch_unmatched_news_events(db, batch_size=self._batch_size)
        count = 0
        for news_event in news_events:
            trades = self._fetch_trades(
                db, news_event.symbol_id, news_event.detected_at, self._window_minutes
            )
            snapshots = self._fetch_snapshots(
                db, news_event.symbol_id, news_event.detected_at, self._window_minutes
            )
            confirmation = self._detector.evaluate(trades, snapshots, provider_confidence)
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
    def _build_detected_event(
        news_event: DetectedEvent,
        conf: OptionsConfirmation,
    ) -> DetectedEvent:
        return DetectedEvent(
            detector="C",
            symbol_id=news_event.symbol_id,
            ticker=news_event.ticker,
            event_type=conf.pattern,
            polarity=conf.polarity,
            importance=conf.importance,
            confidence=conf.confidence,
            source_tier=news_event.source_tier,
            # news_article_id is the idempotency key (same as Detector B)
            news_article_id=news_event.news_article_id,
            metadata_json={
                "news_event_id": news_event.id,
                "mode": conf.mode,
                "pattern": conf.pattern,
                "call_fraction": conf.call_fraction,
            },
        )

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    def _get_provider_confidence(self, db: Session) -> float:
        row = (
            db.query(ProviderHealth)
            .filter(
                ProviderHealth.provider_name == self._options_provider,
                ProviderHealth.is_healthy.is_(True),
            )
            .order_by(ProviderHealth.checked_at.desc())
            .first()
        )
        if row and row.provider_confidence is not None:
            return float(row.provider_confidence)
        return 0.0

    @staticmethod
    def _fetch_unmatched_news_events(
        db: Session,
        batch_size: int = _DEFAULT_BATCH,
    ) -> list[DetectedEvent]:
        """Return Detector A events with no matching Detector C event yet."""
        det_c = aliased(DetectedEvent)
        already_matched = (
            db.query(det_c.id)
            .filter(
                det_c.detector == "C",
                det_c.news_article_id == DetectedEvent.news_article_id,
                det_c.symbol_id == DetectedEvent.symbol_id,
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
    def _fetch_trades(
        db: Session,
        symbol_id: int,
        since: datetime,
        window_minutes: int,
    ) -> list[OptionTradeSnapshot]:
        until = since + timedelta(minutes=window_minutes)
        rows = (
            db.query(OptionTrade)
            .filter(
                OptionTrade.symbol_id == symbol_id,
                OptionTrade.trade_time >= since,
                OptionTrade.trade_time < until,
            )
            .order_by(OptionTrade.trade_time)
            .all()
        )
        return [
            OptionTradeSnapshot(
                trade_time=r.trade_time,
                option_type=r.option_type,
                price=float(r.price),
                size=int(r.size),
                expiration_date=r.expiration_date,
                strike=float(r.strike),
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_snapshots(
        db: Session,
        symbol_id: int,
        since: datetime,
        window_minutes: int,
    ) -> list[ChainSnapshot]:
        until = since + timedelta(minutes=window_minutes)
        rows = (
            db.query(OptionChainSnapshot)
            .filter(
                OptionChainSnapshot.symbol_id == symbol_id,
                OptionChainSnapshot.snapshot_time >= since,
                OptionChainSnapshot.snapshot_time < until,
            )
            .order_by(OptionChainSnapshot.snapshot_time)
            .all()
        )
        return [
            ChainSnapshot(
                snapshot_time=r.snapshot_time,
                expiration_date=r.expiration_date,
                total_call_volume=int(r.total_call_volume),
                total_put_volume=int(r.total_put_volume),
            )
            for r in rows
        ]
