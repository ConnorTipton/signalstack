"""Smoke tests: one INSERT per Phase 2a table to confirm schema is correct."""

from datetime import UTC, date, datetime

import pytest

from app.db.models.market import (
    OptionChainSnapshot,
    OptionQuote,
    OptionTrade,
    UnderlyingBar1m,
    UnderlyingQuote,
)
from app.db.models.provider import ProviderConfig, ProviderHealth
from app.db.models.symbols import Symbol

pytestmark = pytest.mark.usefixtures("db_engine")

NOW = datetime(2026, 4, 20, 14, 30, 0, tzinfo=UTC)
TODAY = date(2026, 4, 20)
EXPIRY = date(2026, 4, 25)


def test_symbols_insert(db_session):
    sym = Symbol(ticker="TEST", name="Test Corp")
    db_session.add(sym)
    db_session.flush()
    assert sym.id is not None


def test_provider_config_insert(db_session):
    cfg = ProviderConfig(provider_name="test_provider", priority_order=1)
    db_session.add(cfg)
    db_session.flush()
    assert cfg.id is not None


def test_provider_health_insert(db_session):
    row = ProviderHealth(
        checked_at=NOW,
        provider_name="test_provider",
        is_healthy=True,
        provider_confidence=0.95,
        consecutive_failures=0,
    )
    db_session.add(row)
    db_session.flush()
    assert row.id is not None


def test_underlying_bar1m_insert(db_session):
    bar = UnderlyingBar1m(
        bar_time=NOW,
        symbol_id=1,
        open=100.00,
        high=101.50,
        low=99.75,
        close=101.00,
        volume=500_000,
        source_name="test",
    )
    db_session.add(bar)
    db_session.flush()


def test_underlying_quote_insert(db_session):
    q = UnderlyingQuote(
        quote_time=NOW,
        symbol_id=1,
        bid=100.95,
        ask=101.05,
        bid_size=100,
        ask_size=100,
        source_name="test",
    )
    db_session.add(q)
    db_session.flush()
    assert q.id is not None


def test_option_quote_insert(db_session):
    oq = OptionQuote(
        quote_time=NOW,
        symbol_id=1,
        contract_symbol="TEST260425C00100000",
        expiration_date=EXPIRY,
        strike=100.00,
        option_type="call",
        bid=2.50,
        ask=2.60,
        source_name="test",
    )
    db_session.add(oq)
    db_session.flush()
    assert oq.id is not None


def test_option_trade_insert(db_session):
    ot = OptionTrade(
        trade_time=NOW,
        symbol_id=1,
        contract_symbol="TEST260425C00100000",
        expiration_date=EXPIRY,
        strike=100.00,
        option_type="call",
        price=2.55,
        size=10,
        source_name="test",
    )
    db_session.add(ot)
    db_session.flush()
    assert ot.id is not None


def test_option_chain_snapshot_insert(db_session):
    snap = OptionChainSnapshot(
        snapshot_time=NOW,
        symbol_id=1,
        expiration_date=EXPIRY,
        contract_count=120,
        total_call_oi=50_000,
        total_put_oi=40_000,
        source_name="test",
    )
    db_session.add(snap)
    db_session.flush()
    assert snap.id is not None
