"""Unit tests for PriceDetector (Detector B).

All rule tests operate on plain BarSnapshot lists — no DB required.
Worker tests mock the DB fetch methods.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.db.models.signals import DetectedEvent
from app.signals.price import BarSnapshot, PriceConfirmation, PriceDetector, PriceDetectorWorker

# ---------------------------------------------------------------------------
# Bar-building helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


def _bar(
    close: float,
    *,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    vwap: float | None = None,
    idx: int = 0,
) -> BarSnapshot:
    o = open if open is not None else close - 0.05
    h = high if high is not None else close + 0.05
    lo = low if low is not None else close - 0.10
    return BarSnapshot(
        bar_time=_T0,
        open=o,
        high=h,
        low=lo,
        close=close,
        vwap=vwap,
    )


def _bars(closes: list[float], vwaps: list[float | None] | None = None) -> list[BarSnapshot]:
    """Build a bar list from close prices; first bar open = closes[0] - 0.05."""
    result = []
    vwaps = vwaps or [None] * len(closes)
    for _i, (c, v) in enumerate(zip(closes, vwaps, strict=True)):
        result.append(
            BarSnapshot(
                bar_time=_T0,
                open=c - 0.05,
                high=c + 0.05,
                low=c - 0.10,
                close=c,
                vwap=v,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Too few bars
# ---------------------------------------------------------------------------


def test_evaluate_returns_none_with_too_few_bars():
    detector = PriceDetector()
    bars = _bars([100.0] * (PriceDetector.MIN_BARS_NEEDED - 1))
    assert detector.evaluate(bars, "positive") is None


def test_evaluate_returns_none_with_empty_bars():
    assert PriceDetector().evaluate([], "positive") is None


# ---------------------------------------------------------------------------
# first_5m_high_break
# ---------------------------------------------------------------------------


def test_first_5m_high_break_detected():
    # Bars 0–4 have highs at close+0.05 → max high ≈ 100.05
    # Bar 5 closes at 101 (above 100.05)
    closes = [100.0] * 5 + [101.0]
    detector = PriceDetector()
    result = detector.evaluate(_bars(closes), "positive")
    assert result is not None
    assert result.pattern == "first_5m_high_break"
    assert result.polarity == "positive"
    assert result.trigger_bar_index == 5
    assert result.trigger_price == pytest.approx(101.0)


def test_first_5m_high_break_not_triggered_when_no_close_above():
    # All bars at same close — bar 5 only meets but doesn't exceed ref_high
    closes = [100.0] * 6  # bar 5 close = 100.0, ref_high = 100.05 (high) → no break
    detector = PriceDetector()
    result = detector.evaluate(_bars(closes), "positive")
    # vwap is None so vwap_reclaim also skips
    assert result is None


def test_first_5m_high_break_confidence_capped_at_1():
    # Massive break — confidence must not exceed 1.0
    closes = [100.0] * 5 + [120.0]
    result = PriceDetector().evaluate(_bars(closes), "positive")
    assert result is not None
    assert result.confidence <= 1.0


def test_first_5m_high_break_importance_capped_at_1():
    closes = [100.0] * 5 + [200.0]
    result = PriceDetector().evaluate(_bars(closes), "positive")
    assert result is not None
    assert result.importance <= 1.0


def test_first_5m_high_break_reference_level_is_max_of_first_5_highs():
    # Introduce a spike on bar 2
    bars = _bars([100.0] * 6)
    bars[2] = BarSnapshot(bar_time=_T0, open=99.95, high=105.0, low=99.9, close=100.0, vwap=None)
    bars[5] = BarSnapshot(bar_time=_T0, open=103.0, high=106.0, low=102.9, close=106.0, vwap=None)
    result = PriceDetector().evaluate(bars, "positive")
    assert result is not None
    assert result.reference_level == pytest.approx(105.0)


# ---------------------------------------------------------------------------
# vwap_reclaim
# ---------------------------------------------------------------------------


def test_vwap_reclaim_detected_when_two_consecutive_closes_above_vwap():
    # Call the rule directly so first_5m_high_break doesn't win first
    vwaps = [100.5] * 7
    closes = [100.0] * 5 + [101.0, 101.5]
    result = PriceDetector()._check_vwap_reclaim(_bars(closes, vwaps))
    assert result is not None
    assert result.pattern == "vwap_reclaim"
    assert result.polarity == "positive"


def test_vwap_reclaim_not_triggered_by_single_close_above_vwap():
    # Only one bar above vwap, next bar drops back
    vwaps = [100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5]
    closes = [100.0, 100.0, 100.0, 100.0, 100.0, 101.0, 100.0]
    result = PriceDetector()._check_vwap_reclaim(_bars(closes, vwaps))
    assert result is None


def test_vwap_reclaim_skipped_when_vwap_is_none():
    closes = [101.0] * 7  # all above where vwap would be, but vwap=None
    result = PriceDetector()._check_vwap_reclaim(_bars(closes))
    assert result is None


def test_vwap_reclaim_confidence_is_fixed():
    vwaps = [100.5] * 7
    closes = [100.0] * 5 + [101.0, 101.5]
    result = PriceDetector()._check_vwap_reclaim(_bars(closes, vwaps))
    assert result is not None
    assert result.confidence == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# support_loss
# ---------------------------------------------------------------------------


def test_support_loss_detected():
    # Bars 0-4 have lows at close-0.10 → min low ≈ 99.90; bar 5 closes at 99.0
    closes = [100.0] * 5 + [99.0]
    result = PriceDetector().evaluate(_bars(closes), "negative")
    assert result is not None
    assert result.pattern == "support_loss"
    assert result.polarity == "negative"
    assert result.trigger_bar_index == 5


def test_support_loss_not_triggered_when_close_above_ref_low():
    closes = [100.0] * 6  # bar 5 close = 100.0 > ref_low ≈ 99.90 → no loss
    result = PriceDetector()._check_support_loss(_bars(closes))
    assert result is None


def test_support_loss_confidence_capped_at_1():
    closes = [100.0] * 5 + [50.0]
    result = PriceDetector().evaluate(_bars(closes), "negative")
    assert result is not None
    assert result.confidence <= 1.0


def test_support_loss_reference_level_is_min_of_first_5_lows():
    bars = _bars([100.0] * 6)
    bars[3] = BarSnapshot(bar_time=_T0, open=99.95, high=100.0, low=95.0, close=100.0, vwap=None)
    bars[5] = BarSnapshot(bar_time=_T0, open=94.5, high=94.9, low=94.0, close=94.0, vwap=None)
    result = PriceDetector().evaluate(bars, "negative")
    assert result is not None
    assert result.reference_level == pytest.approx(95.0)


# ---------------------------------------------------------------------------
# failed_bounce
# ---------------------------------------------------------------------------


def test_failed_bounce_detected():
    # All bars get a very low floor (low=90.0) so support_loss won't fire before
    # failed_bounce even though bar 5 closes below first_open.
    first_open = 100.00
    bars = [
        BarSnapshot(
            bar_time=_T0,
            open=first_open,
            high=first_open + 0.1,
            low=90.0,
            close=first_open,
            vwap=None,
        )
        for _ in range(6)
    ]
    # Bar 2: bounces above first_open * 1.002
    bars[2] = BarSnapshot(
        bar_time=_T0, open=100.0, high=first_open * 1.005, low=99.9, close=100.1, vwap=None
    )
    # Bar 5: closes below first_open but above ref_low (90.0) → failed_bounce fires
    bars[5] = BarSnapshot(
        bar_time=_T0, open=99.9, high=100.0, low=99.5, close=first_open - 0.50, vwap=None
    )
    result = PriceDetector().evaluate(bars, "negative")
    assert result is not None
    assert result.pattern == "failed_bounce"
    assert result.polarity == "negative"


def test_failed_bounce_not_triggered_without_bounce():
    # Price just drops straight — no bounce, so failed_bounce doesn't fire
    closes = [100.0, 99.9, 99.8, 99.7, 99.6, 99.5]
    result = PriceDetector()._check_failed_bounce(_bars(closes))
    assert result is None


def test_failed_bounce_confidence_is_fixed():
    first_open = 100.00
    bars = [
        BarSnapshot(
            bar_time=_T0,
            open=first_open,
            high=first_open + 0.1,
            low=90.0,
            close=first_open,
            vwap=None,
        )
        for _ in range(6)
    ]
    bars[2] = BarSnapshot(
        bar_time=_T0, open=100.0, high=first_open * 1.005, low=99.9, close=100.1, vwap=None
    )
    bars[5] = BarSnapshot(
        bar_time=_T0, open=99.9, high=99.9, low=99.5, close=first_open - 0.10, vwap=None
    )
    result = PriceDetector()._check_failed_bounce(bars)
    assert result is not None
    assert result.confidence == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# Polarity routing
# ---------------------------------------------------------------------------


def test_positive_polarity_only_checks_bullish_patterns():
    # Bearish setup: no high break, no vwap → None
    closes = [100.0] * 5 + [99.0]  # bar 5 below, not above, ref_high
    result = PriceDetector().evaluate(_bars(closes), "positive")
    assert result is None


def test_negative_polarity_only_checks_bearish_patterns():
    # Bullish setup: bar 5 above ref_high, but polarity is negative → None
    closes = [100.0] * 5 + [101.0]
    result = PriceDetector().evaluate(_bars(closes), "negative")
    # support_loss: ref_low ≈ 99.9, bar 5 close = 101 > 99.9 → no
    # failed_bounce: first_open ≈ 99.95, bar 5 high ≈ 101.05 > first_open*1.002 → bounced
    #   but bar 5 close = 101 > first_open → no reversal
    assert result is None


# ---------------------------------------------------------------------------
# PriceDetectorWorker._build_detected_event
# ---------------------------------------------------------------------------


def _news_event(
    id: int = 1,
    symbol_id: int = 2,
    ticker: str = "AAPL",
    polarity: str = "positive",
    source_tier: int = 1,
    news_article_id: int = 10,
) -> MagicMock:
    ev = MagicMock(spec=DetectedEvent)
    ev.id = id
    ev.symbol_id = symbol_id
    ev.ticker = ticker
    ev.polarity = polarity
    ev.source_tier = source_tier
    ev.news_article_id = news_article_id
    ev.detected_at = _T0
    return ev


def _confirmation(pattern: str = "first_5m_high_break") -> PriceConfirmation:
    return PriceConfirmation(
        pattern=pattern,
        polarity="positive",
        confidence=0.8,
        importance=0.5,
        reference_level=100.0,
        trigger_price=101.0,
        trigger_bar_index=5,
    )


def test_build_detected_event_sets_detector_b():
    ev = PriceDetectorWorker._build_detected_event(_news_event(), _confirmation())
    assert ev.detector == "B"


def test_build_detected_event_copies_symbol_and_ticker():
    news_ev = _news_event(symbol_id=7, ticker="MSFT")
    ev = PriceDetectorWorker._build_detected_event(news_ev, _confirmation())
    assert ev.symbol_id == 7
    assert ev.ticker == "MSFT"


def test_build_detected_event_sets_news_article_id_for_idempotency():
    news_ev = _news_event(news_article_id=42)
    ev = PriceDetectorWorker._build_detected_event(news_ev, _confirmation())
    assert ev.news_article_id == 42


def test_build_detected_event_metadata_contains_news_event_id():
    news_ev = _news_event(id=99)
    ev = PriceDetectorWorker._build_detected_event(news_ev, _confirmation())
    assert ev.metadata_json["news_event_id"] == 99


def test_build_detected_event_metadata_contains_reference_and_trigger():
    conf = _confirmation()
    ev = PriceDetectorWorker._build_detected_event(_news_event(), conf)
    assert ev.metadata_json["reference_level"] == conf.reference_level
    assert ev.metadata_json["trigger_price"] == conf.trigger_price


def test_build_detected_event_copies_confidence_and_importance():
    conf = PriceConfirmation(
        pattern="vwap_reclaim",
        polarity="positive",
        confidence=0.7,
        importance=0.3,
        reference_level=100.5,
        trigger_price=101.0,
        trigger_bar_index=6,
    )
    ev = PriceDetectorWorker._build_detected_event(_news_event(), conf)
    assert float(ev.confidence) == pytest.approx(0.7)
    assert float(ev.importance) == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# PriceDetectorWorker.run_once — control flow
# ---------------------------------------------------------------------------


def test_run_once_emits_event_when_confirmation_found():
    closes = [100.0] * 5 + [101.0]
    bars = _bars(closes)

    worker = PriceDetectorWorker()
    worker._fetch_unmatched_news_events = lambda db, **kw: [_news_event()]
    worker._fetch_bars = lambda db, symbol_id, since, window: bars

    db = MagicMock()
    db.commit = MagicMock()

    count = worker.run_once(db)
    assert count == 1
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_run_once_skips_when_no_confirmation():
    # Bars stay flat — no bullish pattern fires
    closes = [100.0] * 6
    bars = _bars(closes)

    worker = PriceDetectorWorker()
    worker._fetch_unmatched_news_events = lambda db, **kw: [_news_event(polarity="positive")]
    worker._fetch_bars = lambda db, symbol_id, since, window: bars

    db = MagicMock()
    count = worker.run_once(db)
    assert count == 0
    db.add.assert_not_called()


def test_run_once_skips_when_too_few_bars():
    bars = _bars([100.0] * (PriceDetector.MIN_BARS_NEEDED - 1))

    worker = PriceDetectorWorker()
    worker._fetch_unmatched_news_events = lambda db, **kw: [_news_event()]
    worker._fetch_bars = lambda db, symbol_id, since, window: bars

    db = MagicMock()
    count = worker.run_once(db)
    assert count == 0
    db.add.assert_not_called()


def test_run_once_returns_zero_when_no_news_events():
    worker = PriceDetectorWorker()
    worker._fetch_unmatched_news_events = lambda db, **kw: []

    db = MagicMock()
    count = worker.run_once(db)
    assert count == 0


def test_run_once_processes_multiple_news_events():
    closes = [100.0] * 5 + [101.0]
    bars = _bars(closes)

    worker = PriceDetectorWorker()
    worker._fetch_unmatched_news_events = lambda db, **kw: [
        _news_event(id=1, news_article_id=10),
        _news_event(id=2, news_article_id=11),
    ]
    worker._fetch_bars = lambda db, symbol_id, since, window: bars

    db = MagicMock()
    count = worker.run_once(db)
    assert count == 2
    assert db.add.call_count == 2


# ---------------------------------------------------------------------------
# PriceDetectorWorker async loop
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    worker = PriceDetectorWorker(interval_seconds=0.01)
    worker._fetch_unmatched_news_events = lambda db, **kw: []

    import app.signals.price as price_mod

    original = price_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *_):
            pass

    price_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        price_mod.SessionLocal = original
