"""Integration tests for AlpacaBarWorker persistence helpers."""

from datetime import UTC, datetime

from app.db.models.market import UnderlyingBar1m
from app.db.models.raw_events import RawAlpacaMarketEvent
from app.db.models.symbols import Symbol
from app.ingest_market.alpaca_bar_worker import AlpacaBarWorker
from app.providers.base import Bar

_START = datetime(2026, 4, 22, 14, 0, tzinfo=UTC)
_END = datetime(2026, 4, 22, 14, 1, tzinfo=UTC)


def test_write_bars_stores_raw_before_normalized_bars(db_session):
    sym = Symbol(ticker="AAPL", name="Apple Inc.")
    db_session.add(sym)
    db_session.flush()

    raw = {"bars": {"AAPL": [{"t": "2026-04-22T14:00:00Z"}]}}
    bars = [
        Bar(
            symbol="AAPL",
            bar_time=_START,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            vwap=100.25,
            trade_count=10,
            source_name="alpaca",
        )
    ]

    AlpacaBarWorker._write_bars(db_session, raw, bars, _END, {"AAPL": sym.id}, _START, _END)
    db_session.flush()

    assert db_session.query(RawAlpacaMarketEvent).one().payload == raw
    row = db_session.query(UnderlyingBar1m).one()
    assert row.symbol_id == sym.id
    assert float(row.close) == 100.5
    assert row.source_name == "alpaca"


def test_write_bars_ignores_duplicate_bar(db_session):
    sym = Symbol(ticker="AAPL", name="Apple Inc.")
    db_session.add(sym)
    db_session.flush()
    bars = [
        Bar(
            symbol="AAPL",
            bar_time=_START,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source_name="alpaca",
        )
    ]

    AlpacaBarWorker._write_bars(db_session, {}, bars, _END, {"AAPL": sym.id}, _START, _END)
    AlpacaBarWorker._write_bars(db_session, {}, bars, _END, {"AAPL": sym.id}, _START, _END)
    db_session.flush()

    assert db_session.query(UnderlyingBar1m).count() == 1
