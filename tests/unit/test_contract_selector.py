"""Unit tests for ContractSelector (Phase 6).

All selector tests use plain OptionContractRow lists — no DB.
Worker tests mock the DB fetch methods.
"""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.contracts.selector import (
    ContractSelection,
    ContractSelector,
    ContractSelectorWorker,
    OptionContractRow,
    _next_week_friday,
    _spread_pct,
)
from app.db.models.signals import SignalCandidate

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Tuesday — next-week Friday is 6+4=10 days away: May 1
_TODAY = date(2026, 4, 21)
_NEXT_FRI = date(2026, 5, 1)
_FALLBACK_FRI = date(2026, 5, 8)
_UNDERLYING = 100.0


def _contract(
    strike: float,
    option_type: str = "call",
    expiration_date: date = _NEXT_FRI,
    bid: float | None = 2.00,
    ask: float | None = 2.20,
    oi: int | None = 500,
    volume: int | None = 100,
    symbol: str | None = None,
) -> OptionContractRow:
    sym = symbol or f"SYM{option_type[0].upper()}{int(strike)}"
    return OptionContractRow(
        contract_symbol=sym,
        expiration_date=expiration_date,
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        open_interest=oi,
        volume=volume,
    )


# ---------------------------------------------------------------------------
# _next_week_friday
# ---------------------------------------------------------------------------


def test_next_week_friday_from_tuesday():
    # Tue April 21, 2026 → next Monday April 27 → Friday May 1
    assert _next_week_friday(date(2026, 4, 21)) == date(2026, 5, 1)


def test_next_week_friday_from_monday():
    # Mon April 20 → next Monday April 27 → Friday May 1
    assert _next_week_friday(date(2026, 4, 20)) == date(2026, 5, 1)


def test_next_week_friday_from_friday():
    # Fri April 24 → next Monday April 27 → Friday May 1
    assert _next_week_friday(date(2026, 4, 24)) == date(2026, 5, 1)


def test_next_week_friday_from_sunday():
    # Sun April 26 → next Monday April 27 → Friday May 1
    assert _next_week_friday(date(2026, 4, 26)) == date(2026, 5, 1)


# ---------------------------------------------------------------------------
# _spread_pct
# ---------------------------------------------------------------------------


def test_spread_pct_typical():
    c = _contract(100.0, bid=2.00, ask=2.20)
    assert _spread_pct(c) == pytest.approx(0.20 / 2.10, rel=1e-4)


def test_spread_pct_returns_none_when_bid_none():
    c = _contract(100.0, bid=None, ask=2.20)
    assert _spread_pct(c) is None


def test_spread_pct_returns_none_when_zero_mid():
    c = _contract(100.0, bid=0.0, ask=0.0)
    assert _spread_pct(c) is None


# ---------------------------------------------------------------------------
# ContractSelector — empty / direction
# ---------------------------------------------------------------------------


def test_select_returns_none_with_empty_contracts():
    assert ContractSelector().select([], _UNDERLYING, "positive", _TODAY) is None


def test_select_returns_none_when_no_matching_direction():
    # Only puts available for a positive (call) signal
    contracts = [_contract(100.0, option_type="put")]
    assert ContractSelector().select(contracts, _UNDERLYING, "positive", _TODAY) is None


def test_select_calls_for_positive_polarity():
    calls = [_contract(100.0, option_type="call")]
    result = ContractSelector().select(calls, _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.option_type == "call"


def test_select_puts_for_negative_polarity():
    puts = [_contract(100.0, option_type="put")]
    result = ContractSelector().select(puts, _UNDERLYING, "negative", _TODAY)
    assert result is not None
    assert result.option_type == "put"


# ---------------------------------------------------------------------------
# ContractSelector — expiration
# ---------------------------------------------------------------------------


def test_select_returns_none_when_no_target_expiration():
    # Only far-future expiration — not next week or the week after
    far = date(2026, 6, 19)
    contracts = [_contract(100.0, expiration_date=far)]
    assert ContractSelector().select(contracts, _UNDERLYING, "positive", _TODAY) is None


def test_select_uses_target_expiration_first():
    c_target = _contract(100.0, expiration_date=_NEXT_FRI)
    c_fallback = _contract(100.0, expiration_date=_FALLBACK_FRI, symbol="SYMCFALLBACK")
    result = ContractSelector().select([c_target, c_fallback], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.expiration_date == _NEXT_FRI


def test_select_falls_back_to_second_next_friday_when_target_empty():
    c_fallback = _contract(100.0, expiration_date=_FALLBACK_FRI)
    result = ContractSelector().select([c_fallback], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.expiration_date == _FALLBACK_FRI


# ---------------------------------------------------------------------------
# ContractSelector — dead chain filter
# ---------------------------------------------------------------------------


def test_select_rejects_dead_chain_when_live_exists():
    dead = _contract(100.0, oi=0, volume=0, symbol="DEAD")
    live = _contract(100.0, oi=200, volume=50, symbol="LIVE")
    result = ContractSelector().select([dead, live], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol == "LIVE"
    dead_reasons = [r["reason"] for r in result.rejected if r["contract"] == "DEAD"]
    assert any("dead chain" in r for r in dead_reasons)


def test_select_uses_dead_chain_as_fallback_when_all_dead():
    # All contracts are dead — selector should still return a result rather than None
    contracts = [_contract(100.0, oi=0, volume=0)]
    result = ContractSelector().select(contracts, _UNDERLYING, "positive", _TODAY)
    assert result is not None


# ---------------------------------------------------------------------------
# ContractSelector — strike band
# ---------------------------------------------------------------------------


def test_select_excludes_strikes_far_from_atm():
    # With 6 strikes [90, 95, 100, 105, 110, 120] and ATM=100 (idx=2),
    # band = indices 0..4 → {90, 95, 100, 105, 110}.  Strike 120 is outside.
    in_band = [_contract(float(s), symbol=f"S{s}") for s in (90, 95, 100, 105, 110)]
    out_of_band = _contract(120.0, symbol="FAR")
    result = ContractSelector().select(in_band + [out_of_band], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol != "FAR"
    far_reasons = [r["reason"] for r in result.rejected if r["contract"] == "FAR"]
    assert any("strike too far from ATM" in r for r in far_reasons)


def test_select_considers_atm_band_of_two_strikes():
    # Five strikes: 90, 95, 100, 105, 110; underlying=100 → ATM=100, band=[90..110]
    contracts = [_contract(float(s)) for s in (90, 95, 100, 105, 110)]
    result = ContractSelector().select(contracts, _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.strike in (90, 95, 100, 105, 110)


# ---------------------------------------------------------------------------
# ContractSelector — spread filter
# ---------------------------------------------------------------------------


def test_select_returns_none_when_all_spreads_too_wide():
    # spread_pct = (4.00 - 0.50) / 2.25 ≈ 1.56 → way above 0.30
    contracts = [_contract(100.0, bid=0.50, ask=4.00)]
    assert ContractSelector().select(contracts, _UNDERLYING, "positive", _TODAY) is None


def test_select_accepts_contract_at_spread_boundary():
    # spread_pct just at threshold: bid=1.55, ask=2.45 → mid=2.0, spread=0.90/2.0=0.45 > 0.30 → rejected
    # Use bid=1.70, ask=2.30 → mid=2.0, spread=0.60/2.0=0.30 → accepted (== threshold)
    contracts = [_contract(100.0, bid=1.70, ask=2.30)]
    result = ContractSelector().select(contracts, _UNDERLYING, "positive", _TODAY)
    assert result is not None


def test_select_records_rejected_wide_spread():
    wide = _contract(100.0, bid=0.50, ask=4.00, symbol="WIDE")
    tight = _contract(100.0, bid=2.00, ask=2.20, symbol="TIGHT")
    result = ContractSelector().select([wide, tight], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol == "TIGHT"
    wide_reasons = [r["reason"] for r in result.rejected if r["contract"] == "WIDE"]
    assert any("wide spread" in r for r in wide_reasons)


# ---------------------------------------------------------------------------
# ContractSelector — ranking
# ---------------------------------------------------------------------------


def test_select_prefers_itm_call_over_atm():
    # For calls: ITM = strike < underlying (100).  ATM strike == underlying is not ITM.
    atm = _contract(100.0, oi=500, symbol="ATM")  # strike == underlying → not ITM
    itm = _contract(98.0, oi=400, symbol="ITM")  # strike < underlying → ITM wins despite lower OI
    result = ContractSelector().select([atm, itm], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol == "ITM"


def test_select_prefers_itm_put_over_atm():
    # For puts: ITM = strike > underlying (100).  ATM strike == underlying is not ITM.
    atm = _contract(100.0, option_type="put", oi=500, symbol="ATM")  # not ITM
    itm = _contract(102.0, option_type="put", oi=400, symbol="ITM")  # ITM wins despite lower OI
    result = ContractSelector().select([atm, itm], _UNDERLYING, "negative", _TODAY)
    assert result is not None
    assert result.contract_symbol == "ITM"


def test_select_prefers_higher_oi_among_same_position():
    # Both ATM; higher OI should win
    low_oi = _contract(100.0, oi=100, volume=0, symbol="LOW")
    high_oi = _contract(100.0, oi=800, volume=0, symbol="HIGH")
    result = ContractSelector().select([low_oi, high_oi], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol == "HIGH"


def test_select_combined_oi_and_volume_rank():
    # OI=300 vol=300 vs OI=500 vol=0 → equal total 600 vs 500 → first wins
    c1 = _contract(100.0, oi=300, volume=300, symbol="C1")
    c2 = _contract(100.0, oi=500, volume=0, symbol="C2")
    result = ContractSelector().select([c1, c2], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol == "C1"


# ---------------------------------------------------------------------------
# ContractSelector — liquidity score
# ---------------------------------------------------------------------------


def test_select_liquidity_score_high_with_tight_spread_and_good_oi():
    c = _contract(100.0, bid=2.00, ask=2.10, oi=500)  # spread_pct ≈ 4.9%, OI = full
    result = ContractSelector().select([c], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.liquidity_score > 8.0


def test_select_liquidity_score_lower_with_wide_spread():
    # tight ≈ 5% spread vs wide = 30% spread (exactly at the gate, still accepted)
    tight = _contract(100.0, bid=2.00, ask=2.10, oi=500, symbol="TIGHT")
    wide = _contract(100.0, bid=1.70, ask=2.30, oi=500, symbol="WIDE")  # spread=0.60/2.0=30%
    r_tight = ContractSelector().select([tight], _UNDERLYING, "positive", _TODAY)
    r_wide = ContractSelector().select([wide], _UNDERLYING, "positive", _TODAY)
    assert r_tight is not None and r_wide is not None
    assert r_tight.liquidity_score > r_wide.liquidity_score


def test_select_liquidity_score_bounded_0_to_10():
    c = _contract(100.0, bid=2.00, ask=2.10, oi=1000)
    result = ContractSelector().select([c], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert 0.0 <= result.liquidity_score <= 10.0


# ---------------------------------------------------------------------------
# ContractSelector — result fields
# ---------------------------------------------------------------------------


def test_select_populates_all_result_fields():
    c = _contract(100.0, bid=2.00, ask=2.20, oi=400, volume=80)
    result = ContractSelector().select([c], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    assert result.contract_symbol == c.contract_symbol
    assert result.expiration_date == _NEXT_FRI
    assert result.strike == 100.0
    assert result.option_type == "call"
    assert result.bid == pytest.approx(2.00)
    assert result.ask == pytest.approx(2.20)
    assert result.spread_pct is not None
    assert result.open_interest == 400
    assert result.volume == 80
    assert isinstance(result.selection_reason, str)
    assert isinstance(result.rejected, list)


def test_select_records_rejected_alternatives():
    wrong_dir = _contract(100.0, option_type="put", symbol="PUT100")
    good = _contract(100.0, option_type="call")
    result = ContractSelector().select([wrong_dir, good], _UNDERLYING, "positive", _TODAY)
    assert result is not None
    reject_syms = [r["contract"] for r in result.rejected]
    assert "PUT100" in reject_syms


# ---------------------------------------------------------------------------
# ContractSelectorWorker._apply_selection
# ---------------------------------------------------------------------------


def _candidate_mock() -> MagicMock:
    c = MagicMock(spec=SignalCandidate)
    c.news_event_id = 1
    c.symbol_id = 2
    c.status = "promoted"
    c.contract_symbol = None
    c.created_at = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
    return c


def _selection() -> ContractSelection:
    return ContractSelection(
        contract_symbol="AAPL260501C00100000",
        expiration_date=_NEXT_FRI,
        strike=100.0,
        option_type="call",
        bid=2.00,
        ask=2.20,
        spread_pct=0.095,
        open_interest=500,
        volume=80,
        liquidity_score=8.5,
        selection_reason="ATM call 2026-05-01 $100.00; OI=500 vol=80 spread=10%",
        rejected=[],
    )


def test_apply_selection_sets_contract_fields():
    candidate = _candidate_mock()
    sel = _selection()
    ContractSelectorWorker._apply_selection(candidate, sel, datetime.now(UTC))
    assert candidate.contract_symbol == sel.contract_symbol
    assert candidate.contract_strike == sel.strike
    assert candidate.contract_type == sel.option_type
    assert candidate.liquidity_score == sel.liquidity_score
    assert candidate.contract_selection_reason == sel.selection_reason


def test_apply_selection_sets_contract_selected_at():
    candidate = _candidate_mock()
    now = datetime(2026, 4, 21, 15, 0, tzinfo=UTC)
    ContractSelectorWorker._apply_selection(candidate, _selection(), now)
    assert candidate.contract_selected_at == now


def test_apply_selection_none_downgrades_to_watch():
    candidate = _candidate_mock()
    ContractSelectorWorker._apply_selection(candidate, None, datetime.now(UTC))
    assert candidate.status == "watch"
    assert candidate.rejection_reason == "no liquid contract found"


def test_apply_selection_none_does_not_set_contract_symbol():
    candidate = _candidate_mock()
    ContractSelectorWorker._apply_selection(candidate, None, datetime.now(UTC))
    # contract_symbol should remain unset (MagicMock: attribute not explicitly assigned)
    assert candidate.contract_symbol is None


# ---------------------------------------------------------------------------
# ContractSelectorWorker.run_once — control flow
# ---------------------------------------------------------------------------


def _db_mock() -> MagicMock:
    db = MagicMock()
    db.commit = MagicMock()
    return db


def test_run_once_returns_zero_when_no_candidates():
    worker = ContractSelectorWorker()
    worker._fetch_uncontracted_candidates = lambda db, **kw: []

    db = _db_mock()
    assert worker.run_once(db) == 0
    db.commit.assert_called_once()


def test_run_once_skips_candidate_when_no_price_data():
    worker = ContractSelectorWorker()
    worker._fetch_uncontracted_candidates = lambda db, **kw: [_candidate_mock()]
    worker._fetch_underlying_price = lambda db, symbol_id: None

    db = _db_mock()
    count = worker.run_once(db)
    assert count == 0


def test_run_once_updates_candidate_when_selection_found():
    candidate = _candidate_mock()
    worker = ContractSelectorWorker()
    worker._fetch_uncontracted_candidates = lambda db, **kw: [candidate]
    worker._fetch_underlying_price = lambda db, symbol_id: 100.0
    worker._fetch_option_quotes = lambda db, symbol_id: [_contract(100.0, oi=500, volume=100)]
    worker._get_polarity = lambda db, candidate: "positive"

    db = _db_mock()
    count = worker.run_once(db)
    assert count == 1
    assert candidate.contract_symbol is not None
    db.commit.assert_called_once()


def test_run_once_downgrades_when_no_liquid_contract():
    candidate = _candidate_mock()
    worker = ContractSelectorWorker()
    worker._fetch_uncontracted_candidates = lambda db, **kw: [candidate]
    worker._fetch_underlying_price = lambda db, symbol_id: 100.0
    # Only far-future expiration → selector returns None
    worker._fetch_option_quotes = lambda db, symbol_id: [
        _contract(100.0, expiration_date=date(2026, 6, 19))
    ]
    worker._get_polarity = lambda db, candidate: "positive"

    db = _db_mock()
    count = worker.run_once(db)
    assert count == 1
    assert candidate.status == "watch"
    assert candidate.rejection_reason == "no liquid contract found"


def test_run_once_processes_multiple_candidates():
    candidates = [_candidate_mock(), _candidate_mock()]
    worker = ContractSelectorWorker()
    worker._fetch_uncontracted_candidates = lambda db, **kw: candidates
    worker._fetch_underlying_price = lambda db, symbol_id: 100.0
    worker._fetch_option_quotes = lambda db, symbol_id: [_contract(100.0)]
    worker._get_polarity = lambda db, candidate: "positive"

    db = _db_mock()
    count = worker.run_once(db)
    assert count == 2


# ---------------------------------------------------------------------------
# ContractSelectorWorker async loop
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    worker = ContractSelectorWorker(interval_seconds=0.01)
    worker._fetch_uncontracted_candidates = lambda db, **kw: []

    import app.contracts.selector as selector_mod

    original = selector_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *_):
            pass

    selector_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        selector_mod.SessionLocal = original
