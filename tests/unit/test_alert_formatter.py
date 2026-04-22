"""Unit tests for AlertFormatter and helpers (Phase 7)."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.alerts.formatter import (
    AlertFormatter,
    _data_note,
    _grade_display,
    _liquidity_note,
)
from app.db.models.execution import Alert
from app.db.models.signals import SignalCandidate


def _candidate(
    id: int = 1,
    symbol_id: int = 2,
    ticker: str = "AAPL",
    status: str = "promoted",
    grade: str = "A",
    rejection_reason: str | None = None,
    score: float = 85.0,
    contract_type: str = "call",
    contract_symbol: str = "AAPL250501C00190000",
    contract_expiration: date = date(2025, 5, 1),
    contract_strike: float = 190.0,
    contract_spread_pct: float | None = 0.08,
    contract_oi: int | None = 500,
    contract_volume: int | None = 100,
    price_score: float = 25.0,
    options_score: float = 15.0,
    news_event_id: int | None = 10,
) -> MagicMock:
    c = MagicMock(spec=SignalCandidate)
    c.id = id
    c.symbol_id = symbol_id
    c.ticker = ticker
    c.status = status
    c.grade = grade
    c.rejection_reason = rejection_reason
    c.score = score
    c.contract_type = contract_type
    c.contract_symbol = contract_symbol
    c.contract_expiration = contract_expiration
    c.contract_strike = contract_strike
    c.contract_spread_pct = contract_spread_pct
    c.contract_oi = contract_oi
    c.contract_volume = contract_volume
    c.price_score = price_score
    c.options_score = options_score
    c.news_event_id = news_event_id
    return c


# ---------------------------------------------------------------------------
# _grade_display
# ---------------------------------------------------------------------------


def test_grade_display_no_cap():
    assert _grade_display(_candidate(grade="A", rejection_reason=None)) == "A"


def test_grade_display_cap_on_promoted():
    c = _candidate(grade="B", rejection_reason="options data only suggestive", status="promoted")
    assert _grade_display(c) == "B-"


def test_grade_display_cap_on_watch():
    c = _candidate(grade="C", rejection_reason="weak catalyst", status="watch")
    assert _grade_display(c) == "C-"


def test_grade_display_no_dash_on_rejected():
    # rejected status: rejection_reason is a true rejection, not a cap
    c = _candidate(grade="D", rejection_reason="weak catalyst", status="rejected")
    assert _grade_display(c) == "D"


# ---------------------------------------------------------------------------
# _liquidity_note
# ---------------------------------------------------------------------------


def test_liquidity_note_tight_spread():
    note = _liquidity_note(_candidate(contract_spread_pct=0.05, contract_oi=200))
    assert "tight" in note
    assert "OI 200" in note


def test_liquidity_note_acceptable_spread():
    note = _liquidity_note(
        _candidate(contract_spread_pct=0.15, contract_oi=None, contract_volume=None)
    )
    assert "acceptable" in note


def test_liquidity_note_wide_spread():
    note = _liquidity_note(_candidate(contract_spread_pct=0.28))
    assert "wide" in note


def test_liquidity_note_no_data():
    note = _liquidity_note(
        _candidate(contract_spread_pct=None, contract_oi=None, contract_volume=None)
    )
    assert note == "N/A"


def test_liquidity_note_includes_volume():
    note = _liquidity_note(
        _candidate(contract_spread_pct=None, contract_oi=None, contract_volume=75)
    )
    assert "vol 75" in note


# ---------------------------------------------------------------------------
# _data_note
# ---------------------------------------------------------------------------


def test_data_note_no_cap():
    assert _data_note(_candidate(rejection_reason=None)) == "no caveats"


def test_data_note_with_cap():
    note = _data_note(_candidate(rejection_reason="options data only suggestive"))
    assert "options data only suggestive" in note


# ---------------------------------------------------------------------------
# AlertFormatter.build
# ---------------------------------------------------------------------------


def test_build_returns_alert_instance():
    assert isinstance(AlertFormatter().build(_candidate()), Alert)


def test_build_direction_bullish_for_call():
    assert AlertFormatter().build(_candidate(contract_type="call")).direction == "bullish"


def test_build_direction_bearish_for_put():
    assert AlertFormatter().build(_candidate(contract_type="put")).direction == "bearish"


def test_build_grade_display_includes_dash_when_capped():
    c = _candidate(grade="B", rejection_reason="options data only suggestive")
    assert AlertFormatter().build(c).grade == "B-"


def test_build_reason_uses_news_summary():
    alert = AlertFormatter().build(_candidate(), news_summary="Apple beats earnings")
    assert "Apple beats earnings" in alert.reason


def test_build_reason_fallback_without_summary():
    assert "catalyst detected" in AlertFormatter().build(_candidate()).reason


def test_build_reason_includes_price_confirmation():
    assert "price confirmed" in AlertFormatter().build(_candidate(price_score=20.0)).reason


def test_build_reason_no_price_when_score_zero():
    assert "price confirmed" not in AlertFormatter().build(_candidate(price_score=0.0)).reason


def test_build_reason_includes_options_when_nonzero():
    assert (
        "options activity elevated" in AlertFormatter().build(_candidate(options_score=5.0)).reason
    )


def test_build_dry_run_default_true():
    assert AlertFormatter().build(_candidate()).dry_run is True


def test_build_dry_run_false():
    assert AlertFormatter().build(_candidate(), dry_run=False).dry_run is False


def test_build_sets_send_attempts_zero():
    assert AlertFormatter().build(_candidate()).send_attempts == 0


def test_build_sets_signal_candidate_id():
    assert AlertFormatter().build(_candidate(id=42)).signal_candidate_id == 42


def test_build_sets_contract_fields():
    alert = AlertFormatter().build(
        _candidate(
            contract_expiration=date(2025, 5, 1),
            contract_strike=190.0,
            contract_type="call",
            contract_symbol="AAPL250501C00190000",
        )
    )
    assert alert.expiration_date == date(2025, 5, 1)
    assert alert.strike == pytest.approx(190.0)
    assert alert.option_type == "call"
    assert alert.contract_symbol == "AAPL250501C00190000"


def test_build_entry_condition_uses_direction():
    bullish = AlertFormatter().build(_candidate(contract_type="call", ticker="AAPL"))
    assert "above" in bullish.entry_condition
    bearish = AlertFormatter().build(_candidate(contract_type="put", ticker="AAPL"))
    assert "below" in bearish.entry_condition


# ---------------------------------------------------------------------------
# AlertFormatter.render
# ---------------------------------------------------------------------------


def _alert(ticker="AAPL", direction="bullish", score=85.0, grade="A", dry_run=True) -> Alert:
    return Alert(
        ticker=ticker,
        direction=direction,
        score=score,
        grade=grade,
        dry_run=dry_run,
        send_attempts=0,
        reason="Apple beats earnings; price confirmed",
        entry_condition="only if AAPL holds above breakout level",
        invalidation="lose breakout level / VWAP",
        target1="Trim at +25% option premium",
        target2="Exit remainder at +50% or end-of-day",
        time_stop="Close by 3:30 PM ET if no follow-through",
        liquidity_note="spread 8% (tight); OI 500",
        data_note="no caveats",
        expiration_date=date(2025, 5, 1),
        strike=190.0,
        option_type="call",
    )


def test_render_dry_run_prefix():
    assert AlertFormatter.render(_alert(dry_run=True)).startswith("[DRY RUN]")


def test_render_no_dry_run_prefix():
    assert not AlertFormatter.render(_alert(dry_run=False)).startswith("[DRY RUN]")


def test_render_includes_ticker_and_direction():
    assert "AAPL BULLISH" in AlertFormatter.render(_alert())


def test_render_includes_all_template_fields():
    text = AlertFormatter.render(_alert())
    for label in [
        "Reason:",
        "Contract:",
        "Entry:",
        "Invalidation:",
        "Target 1:",
        "Target 2:",
        "Time stop:",
        "Liquidity:",
        "Data note:",
    ]:
        assert label in text, f"Missing: {label}"


def test_render_contract_line_format():
    text = AlertFormatter.render(_alert())
    assert "2025-05-01" in text
    assert "$190.00" in text
    assert "call" in text


def test_render_score_formatted_as_integer():
    assert "Score 85" in AlertFormatter.render(_alert(score=85.4))
