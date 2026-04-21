"""Integration tests for ChainSnapshotWorker persistence.

Tests _write_chain directly with the transactional test DB session.
The Tradier client is not exercised here.
"""

from datetime import UTC, date, datetime

from app.db.models.market import OptionChainSnapshot, OptionQuote
from app.db.models.raw_events import RawTradierEvent
from app.db.models.symbols import Symbol
from app.ingest_market.chain_snapshot_worker import ChainSnapshotWorker
from app.providers.base import OptionContractQuote

_NOW = datetime(2024, 12, 6, 14, 30, tzinfo=UTC)
_EXPIRY = date(2024, 12, 13)

_RAW = {
    "options": {
        "option": [
            {
                "symbol": "AAPL241213C00190000",
                "underlying": "AAPL",
                "expiration_date": "2024-12-13",
                "strike": 190.0,
                "option_type": "call",
                "bid": 2.50,
                "ask": 2.60,
                "bidsize": 10,
                "asksize": 15,
                "last": 2.55,
                "open_interest": 5000,
                "volume": 500,
                "greeks": {"delta": 0.45, "mid_iv": 0.25},
            },
            {
                "symbol": "AAPL241213P00190000",
                "underlying": "AAPL",
                "expiration_date": "2024-12-13",
                "strike": 190.0,
                "option_type": "put",
                "bid": 1.80,
                "ask": 1.90,
                "bidsize": 20,
                "asksize": 25,
                "last": 1.85,
                "open_interest": 3000,
                "volume": 300,
                "greeks": {"delta": -0.55, "mid_iv": 0.28},
            },
        ]
    }
}

_CONTRACTS = [
    OptionContractQuote(
        contract_symbol="AAPL241213C00190000",
        underlying="AAPL",
        expiration_date=_EXPIRY,
        strike=190.0,
        option_type="call",
        bid=2.50,
        ask=2.60,
        bid_size=10,
        ask_size=15,
        last=2.55,
        open_interest=5000,
        volume=500,
        implied_volatility=0.25,
        delta=0.45,
        source_name="tradier",
    ),
    OptionContractQuote(
        contract_symbol="AAPL241213P00190000",
        underlying="AAPL",
        expiration_date=_EXPIRY,
        strike=190.0,
        option_type="put",
        bid=1.80,
        ask=1.90,
        bid_size=20,
        ask_size=25,
        last=1.85,
        open_interest=3000,
        volume=300,
        implied_volatility=0.28,
        delta=-0.55,
        source_name="tradier",
    ),
]


def _add_symbol(db_session, ticker: str) -> Symbol:
    sym = Symbol(ticker=ticker, name=f"{ticker} Inc.", active=True)
    db_session.add(sym)
    db_session.flush()
    return sym


# ---------------------------------------------------------------------------
# Raw event
# ---------------------------------------------------------------------------


def test_write_chain_stores_raw_event(db_session):
    sym = _add_symbol(db_session, "AAPL")
    ChainSnapshotWorker._write_chain(db_session, _RAW, _CONTRACTS, "AAPL", sym.id, _EXPIRY, _NOW)
    db_session.flush()

    raw = db_session.query(RawTradierEvent).one()
    assert raw.payload == _RAW
    assert raw.received_at == _NOW
    assert raw.provider_event_id == "AAPL:2024-12-13"
    assert raw.normalization_version == "1"


# ---------------------------------------------------------------------------
# Snapshot summary
# ---------------------------------------------------------------------------


def test_write_chain_stores_snapshot_summary(db_session):
    sym = _add_symbol(db_session, "AAPL")
    ChainSnapshotWorker._write_chain(db_session, _RAW, _CONTRACTS, "AAPL", sym.id, _EXPIRY, _NOW)
    db_session.flush()

    snap = db_session.query(OptionChainSnapshot).one()
    assert snap.symbol_id == sym.id
    assert snap.expiration_date == _EXPIRY
    assert snap.contract_count == 2
    assert snap.total_call_oi == 5000
    assert snap.total_put_oi == 3000
    assert snap.total_call_volume == 500
    assert snap.total_put_volume == 300
    assert snap.source_name == "tradier"


# ---------------------------------------------------------------------------
# Option quotes
# ---------------------------------------------------------------------------


def test_write_chain_stores_option_quotes(db_session):
    sym = _add_symbol(db_session, "AAPL")
    ChainSnapshotWorker._write_chain(db_session, _RAW, _CONTRACTS, "AAPL", sym.id, _EXPIRY, _NOW)
    db_session.flush()

    rows = db_session.query(OptionQuote).all()
    assert len(rows) == 2
    call = next(r for r in rows if r.option_type == "call")
    assert call.contract_symbol == "AAPL241213C00190000"
    assert float(call.strike) == 190.0
    assert float(call.bid) == 2.50
    assert float(call.ask) == 2.60
    assert call.bid_size == 10
    assert call.open_interest == 5000
    assert call.volume == 500
    assert call.source_name == "tradier"
    assert call.symbol_id == sym.id


def test_write_chain_option_quote_timestamp(db_session):
    sym = _add_symbol(db_session, "AAPL")
    ChainSnapshotWorker._write_chain(db_session, _RAW, _CONTRACTS, "AAPL", sym.id, _EXPIRY, _NOW)
    db_session.flush()

    rows = db_session.query(OptionQuote).all()
    for row in rows:
        assert row.quote_time == _NOW
