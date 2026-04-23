"""Unit tests for SignalScorer and ScoringWorker (Phase 5d).

All scorer tests use plain ScoringInput objects — no DB.
Worker tests monkey-patch DB fetch methods.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.db.models.signals import DetectedEvent, SignalCandidate
from app.signals.scoring import (
    _GRADE_A_MIN,
    _GRADE_B_MIN,
    _GRADE_C_MIN,
    _PROVIDER_TIER_WEIGHT,
    _STRONG_PRICE_CONF,
    _WEAK_PROVIDER_THRESHOLD,
    ScoringInput,
    ScoringResult,
    ScoringWorker,
    SignalScorer,
)

_T0 = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _news_ev(
    confidence: float = 0.85,
    importance: float = 0.90,
    source_tier: int = 1,
    id: int = 1,
    symbol_id: int = 2,
    ticker: str = "AAPL",
    news_article_id: int = 10,
    detected_at: datetime = _T0,
) -> MagicMock:
    ev = MagicMock(spec=DetectedEvent)
    ev.id = id
    ev.detector = "A"
    ev.symbol_id = symbol_id
    ev.ticker = ticker
    ev.news_article_id = news_article_id
    ev.detected_at = detected_at
    ev.confidence = confidence
    ev.importance = importance
    ev.source_tier = source_tier
    return ev


def _price_ev(
    confidence: float = 0.80,
    importance: float = 0.70,
    id: int = 2,
) -> MagicMock:
    ev = MagicMock(spec=DetectedEvent)
    ev.id = id
    ev.detector = "B"
    ev.confidence = confidence
    ev.importance = importance
    ev.metadata_json = {}
    return ev


def _options_ev(
    confidence: float = 0.75,
    importance: float = 0.60,
    mode: str = "full",
    id: int = 3,
) -> MagicMock:
    ev = MagicMock(spec=DetectedEvent)
    ev.id = id
    ev.detector = "C"
    ev.confidence = confidence
    ev.importance = importance
    ev.metadata_json = {"mode": mode}
    return ev


def _inp(
    news: MagicMock | None = None,
    price: MagicMock | None = None,
    options: MagicMock | None = None,
    provider_confidence: float = 0.90,
    liquidity_score: float = 8.0,
) -> ScoringInput:
    return ScoringInput(
        news_event=news or _news_ev(),
        price_event=price,
        options_event=options,
        provider_confidence=provider_confidence,
        liquidity_score=liquidity_score,
    )


def _db_mock() -> MagicMock:
    db = MagicMock()
    db.commit = MagicMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Sub-score computation
# ---------------------------------------------------------------------------


def test_news_score_tier1_full_weight():
    # conf=0.85, imp=0.90, tier=1 → 0.85 * 0.90 * 1.0 * 35 = 26.775
    score = SignalScorer._news_score(_news_ev(confidence=0.85, importance=0.90, source_tier=1))
    assert score == pytest.approx(26.775)


def test_news_score_tier2_reduced_weight():
    # tier=2 → factor 0.8 → 0.85 * 0.90 * 0.8 * 35 = 21.42
    score = SignalScorer._news_score(_news_ev(confidence=0.85, importance=0.90, source_tier=2))
    assert score == pytest.approx(21.42)


def test_news_score_tier3_half_weight():
    # tier=3 → factor 0.5 → 0.85 * 0.90 * 0.5 * 35 = 13.3875
    score = SignalScorer._news_score(_news_ev(confidence=0.85, importance=0.90, source_tier=3))
    assert score == pytest.approx(13.3875)


def test_price_score_none_returns_zero():
    assert SignalScorer._price_score(None) == 0.0


def test_price_score_present():
    # conf=0.80, imp=0.70 → 0.80 * 0.70 * 30 = 16.8
    assert SignalScorer._price_score(_price_ev(0.80, 0.70)) == pytest.approx(16.8)


def test_options_score_none_returns_zero():
    assert SignalScorer._options_score(None) == 0.0


def test_options_score_full_mode():
    # conf=0.75, imp=0.60, full → 0.75 * 0.60 * 1.0 * 20 = 9.0
    assert SignalScorer._options_score(_options_ev(0.75, 0.60, "full")) == pytest.approx(9.0)


def test_options_score_proxy_mode_reduced():
    # proxy → mode_factor=0.75 → 0.75 * 0.60 * 0.75 * 20 = 6.75
    assert SignalScorer._options_score(_options_ev(0.75, 0.60, "proxy")) == pytest.approx(6.75)


def test_options_score_proxy_less_than_full():
    full = SignalScorer._options_score(_options_ev(0.75, 0.60, "full"))
    proxy = SignalScorer._options_score(_options_ev(0.75, 0.60, "proxy"))
    assert proxy < full


# ---------------------------------------------------------------------------
# Grade boundaries
# ---------------------------------------------------------------------------


def test_grade_a_at_threshold():
    assert SignalScorer._grade_from_score(_GRADE_A_MIN) == "A"


def test_grade_b_at_threshold():
    assert SignalScorer._grade_from_score(_GRADE_B_MIN) == "B"
    assert SignalScorer._grade_from_score(_GRADE_A_MIN - 0.01) == "B"


def test_grade_c_at_threshold():
    assert SignalScorer._grade_from_score(_GRADE_C_MIN) == "C"
    assert SignalScorer._grade_from_score(_GRADE_B_MIN - 0.01) == "C"


def test_grade_d_below_threshold():
    assert SignalScorer._grade_from_score(_GRADE_C_MIN - 0.01) == "D"
    assert SignalScorer._grade_from_score(0.0) == "D"


# ---------------------------------------------------------------------------
# Cap rules
# ---------------------------------------------------------------------------


def _high_score_inp(source_tier: int = 1, mode: str = "full") -> ScoringInput:
    """Input that scores ≥82 with no caps — used to verify cap downgrades."""
    return ScoringInput(
        news_event=_news_ev(confidence=0.95, importance=0.95, source_tier=source_tier),
        price_event=_price_ev(confidence=0.95, importance=0.95),
        options_event=_options_ev(confidence=0.95, importance=0.95, mode=mode),
        provider_confidence=0.95,
        liquidity_score=10.0,
    )


def test_cap_proxy_without_tier1_news_caps_at_b():
    # tier-2 news + proxy options, maxed-out scores → raw "A", capped to "B"
    # news(tier-2): 1.0*1.0*0.8*35=28 + price:30 + opts(proxy):15 + liq:10 + data:5 = 88 → A
    inp = ScoringInput(
        news_event=_news_ev(confidence=1.0, importance=1.0, source_tier=2),
        price_event=_price_ev(confidence=1.0, importance=1.0),
        options_event=_options_ev(confidence=1.0, importance=1.0, mode="proxy"),
        provider_confidence=1.0,
        liquidity_score=10.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "B"
    assert result.rejection_reason == "options data only suggestive"


def test_cap_proxy_exempt_when_tier1_and_strong_price():
    # Tier-1 news + proxy options + price_conf == STRONG_PRICE_CONF threshold → cap does NOT fire
    # news(tier-1):35 + price(0.70,1.0):21 + opts(proxy,1.0,1.0):15 + liq:10 + data:5 = 86 → A
    inp = ScoringInput(
        news_event=_news_ev(confidence=1.0, importance=1.0, source_tier=1),
        price_event=_price_ev(confidence=_STRONG_PRICE_CONF, importance=1.0),
        options_event=_options_ev(confidence=1.0, importance=1.0, mode="proxy"),
        provider_confidence=1.0,
        liquidity_score=10.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "A"
    assert result.rejection_reason is None


def test_cap_tier3_news_caps_at_c():
    # tier-3 news + weak price (conf=0.79 ≤ 0.80) → raw "B" capped to "C"
    # news(tier-3):17.5 + price(0.79,1.0):23.7 + opts(full,1.0,1.0):20 + liq:10 + data:5 = 76.2 → B
    inp = ScoringInput(
        news_event=_news_ev(confidence=1.0, importance=1.0, source_tier=3),
        price_event=_price_ev(confidence=0.79, importance=1.0),
        options_event=_options_ev(confidence=1.0, importance=1.0, mode="full"),
        provider_confidence=1.0,
        liquidity_score=10.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "C"
    assert result.rejection_reason == "weak catalyst"


def test_cap_tier3_exempt_when_exceptional_evidence():
    # price_conf > 0.80 AND opts_conf > 0.70 → tier-3 cap does NOT fire;
    # grade is "C" from the raw score (tier-3 news weight is 0.5x), no cap_reason
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.95, importance=0.95, source_tier=3),
        price_event=_price_ev(confidence=0.85, importance=0.95),
        options_event=_options_ev(confidence=0.75, importance=0.95, mode="full"),
        provider_confidence=0.95,
        liquidity_score=10.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "C"
    assert result.rejection_reason is None


def test_cap_weak_provider_confidence_caps_at_b():
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.95, importance=0.95, source_tier=1),
        price_event=_price_ev(confidence=0.95, importance=0.95),
        options_event=_options_ev(confidence=0.95, importance=0.95, mode="full"),
        provider_confidence=_WEAK_PROVIDER_THRESHOLD - 0.01,  # just below threshold
        liquidity_score=10.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "B"
    assert result.rejection_reason == "provider confidence too low"


def test_cap_most_restrictive_wins():
    # Both proxy cap (→B) and weak-conf cap (→B) fire; result should be "B"
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.95, importance=0.95, source_tier=2),
        price_event=_price_ev(confidence=0.95, importance=0.95),
        options_event=_options_ev(confidence=0.95, importance=0.95, mode="proxy"),
        provider_confidence=0.30,  # weak
        liquidity_score=10.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "B"


# ---------------------------------------------------------------------------
# Status and rejection_reason
# ---------------------------------------------------------------------------


def test_status_promoted_for_grade_a():
    inp = _high_score_inp()
    result = SignalScorer().score(inp)
    assert result.grade == "A"
    assert result.status == "promoted"


def test_status_promoted_for_grade_b():
    # news(tier-1,0.85²):25.3 + price(0.85²):21.7 + opts(full,0.85²):14.5 + liq:8 + data:4.25 = 73.7 → B
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.85, importance=0.85, source_tier=1),
        price_event=_price_ev(confidence=0.85, importance=0.85),
        options_event=_options_ev(confidence=0.85, importance=0.85, mode="full"),
        provider_confidence=0.85,
        liquidity_score=8.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "B"
    assert result.status == "promoted"


def test_status_watch_for_grade_c():
    # news(tier-1,0.90²):28.4 + price(0.90²):24.3 + no opts + liq:8 + data:4.5 = 65.2 → C
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.90, importance=0.90, source_tier=1),
        price_event=_price_ev(confidence=0.90, importance=0.90),
        options_event=None,
        provider_confidence=0.90,
        liquidity_score=8.0,
    )
    result = SignalScorer().score(inp)
    assert result.grade == "C"
    assert result.status == "watch"


def test_status_rejected_for_grade_d():
    inp = _inp(provider_confidence=0.0)  # no price, no options, weak data confidence
    result = SignalScorer().score(inp)
    assert result.grade == "D"
    assert result.status == "rejected"
    assert result.rejection_reason is not None


def test_rejection_reason_no_price_confirmation():
    # Good news, no price event, no options event, provider weak
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.90, importance=0.90, source_tier=1),
        price_event=None,
        options_event=None,
        provider_confidence=0.0,
        liquidity_score=5.0,
    )
    result = SignalScorer().score(inp)
    if result.status == "rejected":
        # When score is D and price_event is None, reason should reflect missing price
        assert result.rejection_reason in {
            "no price confirmation",
            "weak catalyst",
            "provider confidence too low",
        }


def test_rejection_reason_weak_catalyst():
    # Very low news confidence → weak catalyst
    inp = ScoringInput(
        news_event=_news_ev(confidence=0.10, importance=0.10, source_tier=2),
        price_event=None,
        options_event=None,
        provider_confidence=0.0,
        liquidity_score=0.0,
    )
    result = SignalScorer().score(inp)
    assert result.status == "rejected"
    assert result.rejection_reason is not None


# ---------------------------------------------------------------------------
# ScoringWorker._build_signal_candidate
# ---------------------------------------------------------------------------


def test_build_sets_all_event_ids():
    inp = ScoringInput(
        news_event=_news_ev(id=1),
        price_event=_price_ev(id=2),
        options_event=_options_ev(id=3),
        provider_confidence=0.90,
    )
    result = ScoringResult(
        news_score=25.0,
        price_score=15.0,
        options_score=9.0,
        liquidity_score=5.0,
        data_confidence_score=4.5,
        score=58.5,
        grade="D",
        status="rejected",
        rejection_reason="no price confirmation",
    )
    sc = ScoringWorker._build_signal_candidate(inp, result, _T0)
    assert sc.news_event_id == 1
    assert sc.price_event_id == 2
    assert sc.options_event_id == 3


def test_build_sets_none_when_events_absent():
    inp = _inp(price=None, options=None)
    result = ScoringResult(
        news_score=20.0,
        price_score=0.0,
        options_score=0.0,
        liquidity_score=5.0,
        data_confidence_score=4.5,
        score=29.5,
        grade="D",
        status="rejected",
        rejection_reason="no price confirmation",
    )
    sc = ScoringWorker._build_signal_candidate(inp, result, _T0)
    assert sc.price_event_id is None
    assert sc.options_event_id is None


def test_build_sets_promoted_at_when_promoted():
    inp = _inp()
    result = ScoringResult(
        news_score=25.0,
        price_score=20.0,
        options_score=9.0,
        liquidity_score=8.0,
        data_confidence_score=4.5,
        score=66.5,
        grade="B",
        status="promoted",
        rejection_reason=None,
    )
    sc = ScoringWorker._build_signal_candidate(inp, result, _T0)
    assert sc.promoted_at == _T0
    assert sc.rejected_at is None


def test_build_sets_rejected_at_when_rejected():
    inp = _inp()
    result = ScoringResult(
        news_score=5.0,
        price_score=0.0,
        options_score=0.0,
        liquidity_score=0.0,
        data_confidence_score=0.0,
        score=5.0,
        grade="D",
        status="rejected",
        rejection_reason="weak catalyst",
    )
    sc = ScoringWorker._build_signal_candidate(inp, result, _T0)
    assert sc.rejected_at == _T0
    assert sc.promoted_at is None


def test_build_copies_scores_and_grade():
    inp = _inp(provider_confidence=0.88)
    result = ScoringResult(
        news_score=26.78,
        price_score=16.80,
        options_score=9.0,
        liquidity_score=8.0,
        data_confidence_score=4.40,
        score=65.0,
        grade="C",
        status="watch",
        rejection_reason=None,
    )
    sc = ScoringWorker._build_signal_candidate(inp, result, _T0)
    assert float(sc.score) == pytest.approx(65.0)
    assert float(sc.news_score) == pytest.approx(26.78)
    assert sc.grade == "C"
    assert float(sc.provider_confidence) == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# ScoringWorker.run_once — control flow
# ---------------------------------------------------------------------------


def test_run_once_writes_candidate_for_each_news_event():
    worker = ScoringWorker()
    worker._get_provider_confidence = lambda db: 0.90
    worker._fetch_unscored_news_events = lambda db, cutoff, **kw: [
        _news_ev(id=1, news_article_id=10),
        _news_ev(id=2, news_article_id=11),
    ]
    worker._fetch_price_event = lambda db, naid, sid: _price_ev()
    worker._fetch_options_event = lambda db, naid, sid: _options_ev()

    db = _db_mock()
    count = worker.run_once(db)

    assert count == 2
    assert db.add.call_count == 2
    db.commit.assert_called_once()


def test_run_once_returns_zero_when_no_events():
    worker = ScoringWorker()
    worker._get_provider_confidence = lambda db: 0.90
    worker._fetch_unscored_news_events = lambda db, cutoff, **kw: []

    db = _db_mock()
    count = worker.run_once(db)

    assert count == 0
    db.add.assert_not_called()


def test_run_once_scores_with_provider_confidence():
    # Low provider confidence → cap fires, candidate grade ≤ "B"
    worker = ScoringWorker()
    worker._get_provider_confidence = lambda db: 0.10  # very weak
    worker._fetch_unscored_news_events = lambda db, cutoff, **kw: [_news_ev()]
    worker._fetch_price_event = lambda db, naid, sid: _price_ev(confidence=0.95, importance=0.95)
    worker._fetch_options_event = lambda db, naid, sid: _options_ev(
        confidence=0.95, importance=0.95, mode="full"
    )

    db = _db_mock()
    worker.run_once(db)

    added: SignalCandidate = db.add.call_args[0][0]
    assert added.grade in {"B", "C", "D"}  # A is not achievable with weak conf


def test_run_once_writes_rejected_candidate_when_no_evidence():
    worker = ScoringWorker()
    worker._get_provider_confidence = lambda db: 0.0
    worker._fetch_unscored_news_events = lambda db, cutoff, **kw: [_news_ev()]
    worker._fetch_price_event = lambda db, naid, sid: None
    worker._fetch_options_event = lambda db, naid, sid: None

    db = _db_mock()
    count = worker.run_once(db)

    assert count == 1
    added: SignalCandidate = db.add.call_args[0][0]
    assert added.status == "rejected"
    assert added.rejection_reason is not None


# ---------------------------------------------------------------------------
# _get_provider_confidence — tier weighting
# ---------------------------------------------------------------------------


def test_get_provider_confidence_applies_tradier_weight():
    """Tradier (tier 1) multiplier is 1.0 — result equals raw confidence."""
    worker = ScoringWorker(market_provider="tradier")
    row = MagicMock()
    row.provider_confidence = 0.80

    db = _db_mock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = row

    result = worker._get_provider_confidence(db)
    assert result == pytest.approx(0.80 * _PROVIDER_TIER_WEIGHT["tradier"])


def test_get_provider_confidence_applies_alpaca_weight():
    """Alpaca (tier 2 fallback) multiplier is 0.75 — result is discounted."""
    worker = ScoringWorker(market_provider="alpaca")
    row = MagicMock()
    row.provider_confidence = 0.80

    db = _db_mock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = row

    result = worker._get_provider_confidence(db)
    assert result == pytest.approx(0.80 * _PROVIDER_TIER_WEIGHT["alpaca"])


def test_get_provider_confidence_returns_zero_when_no_healthy_row():
    worker = ScoringWorker(market_provider="tradier")
    db = _db_mock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    assert worker._get_provider_confidence(db) == 0.0


# ---------------------------------------------------------------------------
# ScoringWorker async loop
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    worker = ScoringWorker(interval_seconds=0.01)
    worker._get_provider_confidence = lambda db: 0.0
    worker._fetch_unscored_news_events = lambda db, cutoff, **kw: []

    import app.signals.scoring as scoring_mod

    original = scoring_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *_):
            pass

    scoring_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        scoring_mod.SessionLocal = original
