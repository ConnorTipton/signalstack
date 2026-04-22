"""Integration coverage for stale quote/bar guards."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.contracts.selector import ContractSelectorWorker
from app.core.market_data_freshness import market_data_cutoff
from app.db.models.market import OptionQuote, UnderlyingBar1m
from app.execution.order_router import _fetch_ask_price as fetch_order_ask
from app.execution.position_manager import _fetch_bid_price as fetch_position_bid

pytestmark = pytest.mark.usefixtures("db_engine")

EXPIRY = date(2026, 5, 15)


def test_contract_selector_ignores_stale_underlying_bars(db_session):
    symbol_id = 901
    stale_time = market_data_cutoff() - timedelta(minutes=1)
    db_session.add(
        UnderlyingBar1m(
            bar_time=stale_time,
            symbol_id=symbol_id,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source_name="test",
        )
    )
    db_session.flush()

    assert ContractSelectorWorker._fetch_underlying_price(db_session, symbol_id) is None

    db_session.add(
        UnderlyingBar1m(
            bar_time=datetime.now(UTC),
            symbol_id=symbol_id,
            open=101.0,
            high=102.0,
            low=100.0,
            close=101.5,
            volume=1000,
            source_name="test",
        )
    )
    db_session.flush()

    assert ContractSelectorWorker._fetch_underlying_price(db_session, symbol_id) == 101.5


def test_contract_selector_ignores_stale_option_snapshots(db_session):
    symbol_id = 902
    stale_time = market_data_cutoff() - timedelta(minutes=1)
    db_session.add(
        OptionQuote(
            quote_time=stale_time,
            symbol_id=symbol_id,
            contract_symbol="STL260515C00100000",
            expiration_date=EXPIRY,
            strike=100.0,
            option_type="call",
            bid=1.0,
            ask=1.1,
            source_name="test",
        )
    )
    db_session.flush()

    assert ContractSelectorWorker._fetch_option_quotes(db_session, symbol_id) == []

    db_session.add(
        OptionQuote(
            quote_time=datetime.now(UTC),
            symbol_id=symbol_id,
            contract_symbol="STL260515C00100000",
            expiration_date=EXPIRY,
            strike=100.0,
            option_type="call",
            bid=1.2,
            ask=1.3,
            source_name="test",
        )
    )
    db_session.flush()

    rows = ContractSelectorWorker._fetch_option_quotes(db_session, symbol_id)
    assert len(rows) == 1
    assert rows[0].ask == 1.3


def test_execution_helpers_ignore_stale_option_quotes(db_session):
    contract_symbol = "EXE260515C00100000"
    stale_time = market_data_cutoff() - timedelta(minutes=1)
    db_session.add(
        OptionQuote(
            quote_time=stale_time,
            symbol_id=903,
            contract_symbol=contract_symbol,
            expiration_date=EXPIRY,
            strike=100.0,
            option_type="call",
            bid=1.0,
            ask=1.1,
            source_name="test",
        )
    )
    db_session.flush()

    assert fetch_order_ask(db_session, contract_symbol) is None
    assert fetch_position_bid(db_session, contract_symbol) is None

    db_session.add(
        OptionQuote(
            quote_time=datetime.now(UTC),
            symbol_id=903,
            contract_symbol=contract_symbol,
            expiration_date=EXPIRY,
            strike=100.0,
            option_type="call",
            bid=1.2,
            ask=1.3,
            source_name="test",
        )
    )
    db_session.flush()

    assert fetch_order_ask(db_session, contract_symbol) == 1.3
    assert fetch_position_bid(db_session, contract_symbol) == 1.2
