"""Integration tests for TradierWorker persistence methods.

Tests _insert_raw and _insert_quote directly with the transactional test
DB session (rolls back after each test). The stream/session factories are
not exercised here; those are covered in the unit tests.
"""

from datetime import UTC, datetime

from app.db.models.market import UnderlyingQuote
from app.db.models.raw_events import RawTradierEvent
from app.db.models.symbols import Symbol
from app.ingest_market.tradier_worker import TradierWorker

_NOW = datetime(2024, 12, 6, 14, 30, tzinfo=UTC)

_QUOTE_EVENT = {
    "type": "quote",
    "symbol": "AAPL",
    "bid": 189.25,
    "bidsz": 200,
    "biddate": "1733490000000",
    "ask": 189.35,
    "asksz": 300,
    "askdate": "1733490001000",
}


def _add_symbol(db_session, ticker: str) -> Symbol:
    sym = Symbol(ticker=ticker, name=f"{ticker} Inc.", active=True)
    db_session.add(sym)
    db_session.flush()
    return sym


# ---------------------------------------------------------------------------
# _insert_raw
# ---------------------------------------------------------------------------


def test_insert_raw_stores_payload(db_session):
    TradierWorker._insert_raw(db_session, _QUOTE_EVENT, _NOW)
    db_session.flush()

    row = db_session.query(RawTradierEvent).one()
    assert row.payload == _QUOTE_EVENT
    assert row.received_at == _NOW
    assert row.provider_event_id == "AAPL"
    assert row.normalization_version == "1"


def test_insert_raw_stores_event_timestamp(db_session):
    TradierWorker._insert_raw(db_session, _QUOTE_EVENT, _NOW)
    db_session.flush()

    row = db_session.query(RawTradierEvent).one()
    # biddate is 1733490000000 ms → 2024-12-06T...
    assert row.provider_published_at is not None
    assert row.provider_published_at.tzinfo is not None


def test_insert_raw_non_quote_event(db_session):
    event = {"type": "summary", "symbol": "AAPL"}
    TradierWorker._insert_raw(db_session, event, _NOW)
    db_session.flush()

    row = db_session.query(RawTradierEvent).one()
    assert row.payload["type"] == "summary"
    assert row.provider_published_at is None  # no date fields


# ---------------------------------------------------------------------------
# _insert_quote
# ---------------------------------------------------------------------------


def test_insert_quote_stores_normalized(db_session):
    sym = _add_symbol(db_session, "AAPL")
    TradierWorker._insert_quote(db_session, _QUOTE_EVENT, _NOW, {"AAPL": sym.id})
    db_session.flush()

    row = db_session.query(UnderlyingQuote).one()
    assert row.symbol_id == sym.id
    assert float(row.bid) == 189.25
    assert float(row.ask) == 189.35
    assert row.bid_size == 200
    assert row.ask_size == 300
    assert row.source_name == "tradier"


def test_insert_quote_uses_later_timestamp(db_session):
    sym = _add_symbol(db_session, "AAPL")
    TradierWorker._insert_quote(db_session, _QUOTE_EVENT, _NOW, {"AAPL": sym.id})
    db_session.flush()

    row = db_session.query(UnderlyingQuote).one()
    # askdate (1733490001000) is later than biddate (1733490000000)
    expected = datetime.fromtimestamp(1733490001, tz=UTC)
    assert row.quote_time == expected


def test_insert_quote_skips_unknown_symbol(db_session):
    TradierWorker._insert_quote(db_session, _QUOTE_EVENT, _NOW, {})
    db_session.flush()

    assert db_session.query(UnderlyingQuote).count() == 0


def test_insert_quote_skips_missing_symbol_field(db_session):
    sym = _add_symbol(db_session, "AAPL")
    bad_event = {"type": "quote", "bid": 189.0}  # no "symbol" key
    TradierWorker._insert_quote(db_session, bad_event, _NOW, {"AAPL": sym.id})
    db_session.flush()

    assert db_session.query(UnderlyingQuote).count() == 0
