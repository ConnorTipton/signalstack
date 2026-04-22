"""Integration tests for AlpacaChainSnapshotWorker persistence helpers."""

from datetime import UTC, date, datetime

from app.db.models.market import OptionChainSnapshot, OptionQuote
from app.db.models.raw_events import RawAlpacaMarketEvent
from app.db.models.symbols import Symbol
from app.ingest_market.alpaca_chain_snapshot_worker import AlpacaChainSnapshotWorker
from app.providers.base import OptionContractQuote

_NOW = datetime(2026, 4, 22, 14, 0, tzinfo=UTC)
_EXPIRY = date(2026, 5, 1)


def test_write_chain_stores_alpaca_raw_snapshot_and_quotes(db_session):
    sym = Symbol(ticker="AAPL", name="Apple Inc.")
    db_session.add(sym)
    db_session.flush()
    contracts = [
        OptionContractQuote(
            contract_symbol="AAPL260501C00190000",
            underlying="AAPL",
            expiration_date=_EXPIRY,
            strike=190.0,
            option_type="call",
            bid=1.0,
            ask=1.1,
            open_interest=100,
            volume=20,
            source_name="alpaca",
        )
    ]
    raw = {"snapshots": {"AAPL260501C00190000": {}}}

    AlpacaChainSnapshotWorker._write_chain(
        db_session,
        raw,
        contracts,
        "AAPL",
        sym.id,
        _EXPIRY,
        _NOW,
    )
    db_session.flush()

    assert db_session.query(RawAlpacaMarketEvent).one().payload == raw
    snap = db_session.query(OptionChainSnapshot).one()
    assert snap.total_call_oi == 100
    assert snap.total_call_volume == 20
    quote = db_session.query(OptionQuote).one()
    assert quote.contract_symbol == "AAPL260501C00190000"
    assert quote.source_name == "alpaca"
