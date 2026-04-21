"""Unit tests for OptionsDetector (Detector C).

All rule tests use plain OptionTradeSnapshot / ChainSnapshot lists — no DB.
Worker tests mock the DB fetch methods.
"""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.db.models.signals import DetectedEvent
from app.signals.options import (
    _FULL_MODE_CONFIDENCE_MIN,
    _MIN_FULL_TRADES,
    _MIN_PROXY_VOLUME,
    ChainSnapshot,
    OptionsConfirmation,
    OptionsDetector,
    OptionsDetectorWorker,
    OptionTradeSnapshot,
)

_T0 = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
_EXP = date(2025, 1, 10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trade(option_type: str, price: float = 2.00, size: int = 10) -> OptionTradeSnapshot:
    return OptionTradeSnapshot(
        trade_time=_T0,
        option_type=option_type,
        price=price,
        size=size,
        expiration_date=_EXP,
        strike=100.0,
    )


def _trades(
    n_calls: int, n_puts: int, price: float = 2.00, size: int = 10
) -> list[OptionTradeSnapshot]:
    return [_trade("call", price, size) for _ in range(n_calls)] + [
        _trade("put", price, size) for _ in range(n_puts)
    ]


def _snapshot(call_vol: int, put_vol: int) -> ChainSnapshot:
    return ChainSnapshot(
        snapshot_time=_T0,
        expiration_date=_EXP,
        total_call_volume=call_vol,
        total_put_volume=put_vol,
    )


# ---------------------------------------------------------------------------
# Full mode — _evaluate_full
# ---------------------------------------------------------------------------


def test_full_mode_returns_none_below_min_trades():
    trades = _trades(_MIN_FULL_TRADES - 1, 0)
    assert OptionsDetector._evaluate_full(trades) is None


def test_full_mode_returns_none_when_zero_notional():
    trades = [_trade("call", price=0.0) for _ in range(_MIN_FULL_TRADES)]
    assert OptionsDetector._evaluate_full(trades) is None


def test_full_mode_bullish_when_calls_dominant():
    # 8 calls, 2 puts → call_fraction = 0.80 > 0.65
    trades = _trades(8, 2)
    result = OptionsDetector._evaluate_full(trades)
    assert result is not None
    assert result.polarity == "positive"
    assert result.pattern == "notional_lean_bullish"
    assert result.mode == "full"


def test_full_mode_bearish_when_puts_dominant():
    # 2 calls, 8 puts → call_fraction = 0.20 < 0.35
    trades = _trades(2, 8)
    result = OptionsDetector._evaluate_full(trades)
    assert result is not None
    assert result.polarity == "negative"
    assert result.pattern == "notional_lean_bearish"


def test_full_mode_returns_none_when_no_clear_lean():
    # 5 calls, 5 puts → call_fraction = 0.50, inside neutral band
    trades = _trades(5, 5)
    assert OptionsDetector._evaluate_full(trades) is None


def test_full_mode_call_fraction_correct():
    # 8 calls at $3, 2 puts at $3 → call_notional = 80*10*3 = 240... wait
    # Each trade has size=10. 8 call trades × 2.00 × 10 = 160; 2 put × 2.00 × 10 = 40
    trades = _trades(8, 2, price=2.00, size=10)
    result = OptionsDetector._evaluate_full(trades)
    assert result is not None
    assert result.call_fraction == pytest.approx(0.80)


def test_full_mode_confidence_at_threshold_is_min():
    # call_fraction just at threshold (0.65) → minimum full-mode confidence 0.60
    # Build trades to hit exactly 0.65: 13 calls, 7 puts (13/20 = 0.65)
    trades = _trades(13, 7)
    result = OptionsDetector._evaluate_full(trades)
    assert result is not None
    assert result.confidence >= 0.60


def test_full_mode_confidence_never_exceeds_1():
    # All calls → max lean → confidence should not exceed 1.0
    trades = _trades(20, 0)
    result = OptionsDetector._evaluate_full(trades)
    assert result is not None
    assert result.confidence <= 1.0


def test_full_mode_confidence_higher_with_stronger_lean():
    # 8 calls / 2 puts vs 13 calls / 7 puts
    strong = OptionsDetector._evaluate_full(_trades(8, 2))
    weak = OptionsDetector._evaluate_full(_trades(13, 7))
    assert strong is not None and weak is not None
    assert strong.confidence > weak.confidence


def test_full_mode_importance_capped_at_1():
    trades = _trades(100, 0)  # 100 call trades
    result = OptionsDetector._evaluate_full(trades)
    assert result is not None
    assert result.importance <= 1.0


# ---------------------------------------------------------------------------
# Proxy mode — _evaluate_proxy
# ---------------------------------------------------------------------------


def test_proxy_mode_returns_none_with_empty_snapshots():
    assert OptionsDetector._evaluate_proxy([]) is None


def test_proxy_mode_returns_none_below_min_volume():
    snaps = [_snapshot(_MIN_PROXY_VOLUME // 2, 0)]
    assert OptionsDetector._evaluate_proxy(snaps) is None


def test_proxy_mode_bullish_when_calls_dominant():
    # 800 calls, 200 puts across all snapshots → call_fraction = 0.80
    snaps = [_snapshot(400, 100), _snapshot(400, 100)]
    result = OptionsDetector._evaluate_proxy(snaps)
    assert result is not None
    assert result.polarity == "positive"
    assert result.pattern == "chain_volume_lean_bullish"
    assert result.mode == "proxy"


def test_proxy_mode_bearish_when_puts_dominant():
    snaps = [_snapshot(100, 400), _snapshot(100, 400)]
    result = OptionsDetector._evaluate_proxy(snaps)
    assert result is not None
    assert result.polarity == "negative"
    assert result.pattern == "chain_volume_lean_bearish"


def test_proxy_mode_returns_none_when_no_clear_lean():
    snaps = [_snapshot(250, 250)]
    assert OptionsDetector._evaluate_proxy(snaps) is None


def test_proxy_mode_confidence_never_exceeds_075():
    # Extreme lean — all calls
    snaps = [_snapshot(1000, 0)]
    result = OptionsDetector._evaluate_proxy(snaps)
    assert result is not None
    assert result.confidence <= 0.75


def test_proxy_mode_confidence_above_045_at_threshold():
    # Exactly at threshold (65% calls, 35% puts)
    snaps = [_snapshot(130, 70)]  # 130/(130+70) = 0.65
    result = OptionsDetector._evaluate_proxy(snaps)
    assert result is not None
    assert result.confidence >= 0.45


def test_proxy_mode_aggregates_across_all_snapshots():
    # Three expirations each with mixed volumes
    snaps = [_snapshot(200, 50), _snapshot(200, 50), _snapshot(200, 50)]
    result = OptionsDetector._evaluate_proxy(snaps)
    assert result is not None
    assert result.call_fraction == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# evaluate — mode routing
# ---------------------------------------------------------------------------


def test_evaluate_uses_full_mode_when_confidence_high_and_enough_trades():
    trades = _trades(8, 2)
    snaps = [_snapshot(200, 800)]  # bearish chain
    result = OptionsDetector().evaluate(
        trades, snaps, provider_confidence=_FULL_MODE_CONFIDENCE_MIN
    )
    assert result is not None
    assert result.mode == "full"
    assert result.polarity == "positive"  # full mode wins (bullish trades)


def test_evaluate_falls_back_to_proxy_when_confidence_below_threshold():
    trades = _trades(8, 2)  # bullish trades, but won't be used
    snaps = [_snapshot(200, 800)]  # bearish chain
    result = OptionsDetector().evaluate(trades, snaps, provider_confidence=0.50)
    assert result is not None
    assert result.mode == "proxy"
    assert result.polarity == "negative"  # proxy wins (bearish chain)


def test_evaluate_falls_back_to_proxy_when_too_few_trades():
    trades = _trades(_MIN_FULL_TRADES - 1, 0)
    snaps = [_snapshot(100, 400)]
    result = OptionsDetector().evaluate(trades, snaps, provider_confidence=1.0)
    assert result is not None
    assert result.mode == "proxy"


def test_evaluate_returns_none_when_no_data_at_all():
    result = OptionsDetector().evaluate([], [], provider_confidence=0.0)
    assert result is None


def test_evaluate_returns_none_when_proxy_has_no_lean():
    trades = _trades(3, 0)  # too few for full mode
    snaps = [_snapshot(50, 50)]  # neutral
    result = OptionsDetector().evaluate(trades, snaps, provider_confidence=0.0)
    assert result is None


# ---------------------------------------------------------------------------
# OptionsDetectorWorker._build_detected_event
# ---------------------------------------------------------------------------


def _news_event(
    id: int = 1,
    symbol_id: int = 2,
    ticker: str = "AAPL",
    source_tier: int = 1,
    news_article_id: int = 10,
) -> MagicMock:
    ev = MagicMock(spec=DetectedEvent)
    ev.id = id
    ev.symbol_id = symbol_id
    ev.ticker = ticker
    ev.source_tier = source_tier
    ev.news_article_id = news_article_id
    ev.detected_at = _T0
    return ev


def _confirmation(mode: str = "full", polarity: str = "positive") -> OptionsConfirmation:
    return OptionsConfirmation(
        mode=mode,
        pattern="notional_lean_bullish" if polarity == "positive" else "notional_lean_bearish",
        polarity=polarity,
        confidence=0.80,
        importance=0.60,
        call_fraction=0.75,
    )


def test_build_detected_event_sets_detector_c():
    ev = OptionsDetectorWorker._build_detected_event(_news_event(), _confirmation())
    assert ev.detector == "C"


def test_build_detected_event_copies_symbol_and_ticker():
    ev = OptionsDetectorWorker._build_detected_event(
        _news_event(symbol_id=9, ticker="NVDA"), _confirmation()
    )
    assert ev.symbol_id == 9
    assert ev.ticker == "NVDA"


def test_build_detected_event_sets_news_article_id_for_idempotency():
    ev = OptionsDetectorWorker._build_detected_event(
        _news_event(news_article_id=55), _confirmation()
    )
    assert ev.news_article_id == 55


def test_build_detected_event_metadata_contains_mode():
    ev = OptionsDetectorWorker._build_detected_event(_news_event(), _confirmation(mode="proxy"))
    assert ev.metadata_json["mode"] == "proxy"


def test_build_detected_event_metadata_contains_call_fraction():
    conf = _confirmation()
    ev = OptionsDetectorWorker._build_detected_event(_news_event(), conf)
    assert ev.metadata_json["call_fraction"] == pytest.approx(conf.call_fraction)


def test_build_detected_event_copies_confidence_and_importance():
    conf = _confirmation()
    ev = OptionsDetectorWorker._build_detected_event(_news_event(), conf)
    assert float(ev.confidence) == pytest.approx(conf.confidence)
    assert float(ev.importance) == pytest.approx(conf.importance)


# ---------------------------------------------------------------------------
# OptionsDetectorWorker.run_once — control flow
# ---------------------------------------------------------------------------


def _db_mock() -> MagicMock:
    db = MagicMock()
    db.commit = MagicMock()
    db.add = MagicMock()
    return db


def test_run_once_emits_event_when_confirmation_found():
    worker = OptionsDetectorWorker()
    worker._get_provider_confidence = lambda db: 0.9
    worker._fetch_unmatched_news_events = lambda db, **kw: [_news_event()]
    worker._fetch_trades = lambda db, symbol_id, since, window: _trades(8, 2)
    worker._fetch_snapshots = lambda db, symbol_id, since, window: []

    db = _db_mock()
    count = worker.run_once(db)

    assert count == 1
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_run_once_skips_when_no_confirmation():
    worker = OptionsDetectorWorker()
    worker._get_provider_confidence = lambda db: 0.0
    worker._fetch_unmatched_news_events = lambda db, **kw: [_news_event()]
    worker._fetch_trades = lambda db, symbol_id, since, window: []
    worker._fetch_snapshots = lambda db, symbol_id, since, window: [_snapshot(50, 50)]

    db = _db_mock()
    count = worker.run_once(db)

    assert count == 0
    db.add.assert_not_called()


def test_run_once_returns_zero_when_no_news_events():
    worker = OptionsDetectorWorker()
    worker._get_provider_confidence = lambda db: 0.9
    worker._fetch_unmatched_news_events = lambda db, **kw: []

    db = _db_mock()
    count = worker.run_once(db)
    assert count == 0


def test_run_once_processes_multiple_events():
    worker = OptionsDetectorWorker()
    worker._get_provider_confidence = lambda db: 0.9
    worker._fetch_unmatched_news_events = lambda db, **kw: [
        _news_event(id=1, news_article_id=10),
        _news_event(id=2, news_article_id=11),
    ]
    worker._fetch_trades = lambda db, symbol_id, since, window: _trades(8, 2)
    worker._fetch_snapshots = lambda db, symbol_id, since, window: []

    db = _db_mock()
    count = worker.run_once(db)
    assert count == 2
    assert db.add.call_count == 2


def test_run_once_uses_proxy_mode_when_provider_confidence_low():
    worker = OptionsDetectorWorker()
    worker._get_provider_confidence = lambda db: 0.0
    worker._fetch_unmatched_news_events = lambda db, **kw: [_news_event()]
    worker._fetch_trades = lambda db, symbol_id, since, window: _trades(
        20, 0
    )  # would be bullish in full
    worker._fetch_snapshots = lambda db, symbol_id, since, window: [
        _snapshot(200, 800)
    ]  # bearish proxy

    db = _db_mock()
    worker.run_once(db)

    added: DetectedEvent = db.add.call_args[0][0]
    assert added.metadata_json["mode"] == "proxy"
    assert added.polarity == "negative"


# ---------------------------------------------------------------------------
# OptionsDetectorWorker async loop
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    worker = OptionsDetectorWorker(interval_seconds=0.01)
    worker._get_provider_confidence = lambda db: 0.0
    worker._fetch_unmatched_news_events = lambda db, **kw: []

    import app.signals.options as options_mod

    original = options_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *_):
            pass

    options_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        options_mod.SessionLocal = original
