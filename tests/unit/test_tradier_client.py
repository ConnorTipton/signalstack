"""
Tradier client tests — HTTP is mocked with a path-routing fake transport.

Live Tradier account verification is pending account approval; these tests
cover the full REST path using recorded fixture responses.
"""

from datetime import UTC, date, datetime

import httpx
import pytest

from app.providers.base import MarketDataProvider
from app.providers.tradier.client import TradierAPIError, TradierClient

_SANDBOX = "https://sandbox.tradier.com"

# ---------------------------------------------------------------------------
# Fake transport (path-based routing; query params are ignored)
# ---------------------------------------------------------------------------


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self._routes:
            return self._routes[path]
        raise AssertionError(f"No mock registered for {request.url}")


def _client(routes: dict[str, httpx.Response]) -> TradierClient:
    transport = _FakeTransport(routes)
    http = httpx.AsyncClient(base_url=_SANDBOX, transport=transport)
    return TradierClient(api_token="test", environment="sandbox", http_client=http)


# ---------------------------------------------------------------------------
# Fixture responses (recorded from Tradier sandbox shape)
# ---------------------------------------------------------------------------

_QUOTES_SINGLE = {
    "quotes": {
        "quote": {
            "symbol": "AAPL",
            "last": 189.30,
            "bid": 189.25,
            "ask": 189.35,
            "bidsize": 200,
            "asksize": 300,
            "trade_date": 1733490000000,
            "bid_date": 1733490000000,
        }
    }
}

_QUOTES_MULTI = {
    "quotes": {
        "quote": [
            {
                "symbol": "AAPL",
                "last": 189.30,
                "bid": 189.25,
                "ask": 189.35,
                "bidsize": 200,
                "asksize": 300,
                "trade_date": 1733490000000,
                "bid_date": 1733490000000,
            },
            {
                "symbol": "MSFT",
                "last": 420.50,
                "bid": 420.40,
                "ask": 420.60,
                "bidsize": 100,
                "asksize": 150,
                "trade_date": 1733490000000,
                "bid_date": 1733490000000,
            },
        ]
    }
}

_BARS = {
    "history": {
        "day": [
            {
                "date": "2024-12-06",
                "time": "09:30:00",
                "open": 188.50,
                "high": 189.50,
                "low": 188.00,
                "close": 189.00,
                "volume": 500000,
                "vwap": 188.85,
            },
            {
                "date": "2024-12-06",
                "time": "09:31:00",
                "open": 189.00,
                "high": 189.80,
                "low": 188.90,
                "close": 189.70,
                "volume": 320000,
            },
        ]
    }
}

_OPTION_CHAIN = {
    "options": {
        "option": [
            {
                "symbol": "AAPL241206C00180000",
                "underlying": "AAPL",
                "expiration_date": "2024-12-06",
                "strike": 180.0,
                "option_type": "call",
                "bid": 9.50,
                "ask": 9.60,
                "bidsize": 10,
                "asksize": 10,
                "last": 9.55,
                "open_interest": 5000,
                "volume": 1234,
                "greeks": {"delta": 0.65, "mid_iv": 0.255},
            },
            {
                "symbol": "AAPL241206P00180000",
                "underlying": "AAPL",
                "expiration_date": "2024-12-06",
                "strike": 180.0,
                "option_type": "put",
                "bid": 0.50,
                "ask": 0.60,
                "bidsize": 20,
                "asksize": 25,
                "last": 0.55,
                "open_interest": 3000,
                "volume": 500,
                "greeks": {"delta": -0.35, "mid_iv": 0.275},
            },
        ]
    }
}

_EXPIRATIONS = {"expirations": {"date": ["2024-12-06", "2024-12-13", "2024-12-20"]}}

_EXPIRY = date(2024, 12, 6)
_START = datetime(2024, 12, 6, 9, 30, tzinfo=UTC)
_END = datetime(2024, 12, 6, 16, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Protocol conformance (sync — no transport needed)
# ---------------------------------------------------------------------------


def test_tradier_satisfies_protocol():
    client = TradierClient(api_token="test", environment="sandbox")
    assert isinstance(client, MarketDataProvider)


# ---------------------------------------------------------------------------
# get_quotes
# ---------------------------------------------------------------------------


async def test_get_quotes_single_symbol():
    async with _client({"/v1/markets/quotes": httpx.Response(200, json=_QUOTES_SINGLE)}) as c:
        quotes = await c.get_quotes(["AAPL"])

    assert len(quotes) == 1
    q = quotes[0]
    assert q.symbol == "AAPL"
    assert q.bid == 189.25
    assert q.ask == 189.35
    assert q.last == 189.30
    assert q.bid_size == 200
    assert q.ask_size == 300
    assert q.source_name == "tradier"


async def test_get_quotes_multiple_symbols():
    async with _client({"/v1/markets/quotes": httpx.Response(200, json=_QUOTES_MULTI)}) as c:
        quotes = await c.get_quotes(["AAPL", "MSFT"])

    assert len(quotes) == 2
    assert {q.symbol for q in quotes} == {"AAPL", "MSFT"}


async def test_get_quotes_api_error():
    async with _client({"/v1/markets/quotes": httpx.Response(401, text="Unauthorized")}) as c:
        with pytest.raises(TradierAPIError) as exc_info:
            await c.get_quotes(["AAPL"])

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_bars
# ---------------------------------------------------------------------------


async def test_get_bars():
    async with _client({"/v1/markets/history": httpx.Response(200, json=_BARS)}) as c:
        bars = await c.get_bars("AAPL", _START, _END)

    assert len(bars) == 2
    b = bars[0]
    assert b.symbol == "AAPL"
    assert b.open == 188.50
    assert b.high == 189.50
    assert b.volume == 500000
    assert b.vwap == 188.85
    assert b.bar_time == datetime(2024, 12, 6, 9, 30, tzinfo=UTC)
    assert b.source_name == "tradier"


async def test_get_bars_empty_history():
    async with _client({"/v1/markets/history": httpx.Response(200, json={"history": None})}) as c:
        bars = await c.get_bars("AAPL", _START, _END)

    assert bars == []


# ---------------------------------------------------------------------------
# get_option_chain
# ---------------------------------------------------------------------------


async def test_get_option_chain():
    async with _client(
        {"/v1/markets/options/chains": httpx.Response(200, json=_OPTION_CHAIN)}
    ) as c:
        chain = await c.get_option_chain("AAPL", _EXPIRY)

    assert len(chain) == 2
    call = next(x for x in chain if x.option_type == "call")
    assert call.contract_symbol == "AAPL241206C00180000"
    assert call.strike == 180.0
    assert call.bid == 9.50
    assert call.delta == 0.65
    assert call.implied_volatility == 0.255
    assert call.source_name == "tradier"


async def test_get_option_chain_empty():
    async with _client(
        {"/v1/markets/options/chains": httpx.Response(200, json={"options": None})}
    ) as c:
        chain = await c.get_option_chain("AAPL", _EXPIRY)

    assert chain == []


# ---------------------------------------------------------------------------
# get_option_expirations
# ---------------------------------------------------------------------------


async def test_get_option_expirations():
    async with _client(
        {"/v1/markets/options/expirations": httpx.Response(200, json=_EXPIRATIONS)}
    ) as c:
        expirations = await c.get_option_expirations("AAPL")

    assert len(expirations) == 3
    assert expirations[0] == date(2024, 12, 6)
    assert expirations[1] == date(2024, 12, 13)
