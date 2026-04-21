"""
Alpaca market-data client tests — HTTP is mocked with a path-routing fake transport.

Alpaca credentials are available for development; these tests use fixture
responses so CI never needs live credentials.
"""

from datetime import UTC, date, datetime

import httpx
import pytest

from app.providers.alpaca.client import AlpacaAPIError, AlpacaMarketClient
from app.providers.alpaca.normalizer import _parse_occ
from app.providers.base import MarketDataProvider

_DATA = "https://data.alpaca.markets"

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


def _client(routes: dict[str, httpx.Response]) -> AlpacaMarketClient:
    transport = _FakeTransport(routes)
    http = httpx.AsyncClient(base_url=_DATA, transport=transport)
    return AlpacaMarketClient(api_key="key", secret_key="secret", http_client=http)


# ---------------------------------------------------------------------------
# Fixture responses (Alpaca market-data API shapes)
# ---------------------------------------------------------------------------

_QUOTES = {
    "quotes": {
        "AAPL": {
            "t": "2024-12-06T15:30:00.123456789Z",
            "ax": "C",
            "ap": 189.35,
            "as": 3,
            "bx": "C",
            "bp": 189.25,
            "bs": 2,
            "c": ["R"],
            "z": "C",
        },
        "MSFT": {
            "t": "2024-12-06T15:30:00.000000000Z",
            "ap": 420.60,
            "as": 5,
            "bp": 420.40,
            "bs": 4,
        },
    }
}

_BARS = {
    "bars": {
        "AAPL": [
            {
                "t": "2024-12-06T14:30:00Z",
                "o": 188.00,
                "h": 189.50,
                "l": 187.80,
                "c": 189.00,
                "v": 500000,
                "n": 1200,
                "vw": 188.85,
            },
            {
                "t": "2024-12-06T14:31:00Z",
                "o": 189.00,
                "h": 189.80,
                "l": 188.90,
                "c": 189.70,
                "v": 320000,
                "n": 800,
                "vw": 189.35,
            },
        ]
    },
    "next_page_token": None,
}

_OPTION_SNAPSHOTS = {
    "snapshots": {
        "AAPL241206C00180000": {
            "greeks": {"delta": 0.65, "gamma": 0.02, "theta": -0.08, "vega": 0.15},
            "impliedVolatility": 0.255,
            "latestQuote": {
                "ap": 9.60,
                "as": 10,
                "bp": 9.50,
                "bs": 10,
                "t": "2024-12-06T15:30:00Z",
            },
            "latestTrade": {"p": 9.55, "s": 5, "t": "2024-12-06T15:25:00Z"},
        },
        "AAPL241206P00180000": {
            "greeks": {"delta": -0.35},
            "impliedVolatility": 0.275,
            "latestQuote": {"ap": 0.60, "as": 25, "bp": 0.50, "bs": 20},
            "latestTrade": {"p": 0.55, "s": 2},
        },
    },
    "next_page_token": None,
}

_EXPIRATIONS = {"expirations": ["2024-12-06", "2024-12-13", "2024-12-20"]}

_EXPIRY = date(2024, 12, 6)
_START = datetime(2024, 12, 6, 9, 30, tzinfo=UTC)
_END = datetime(2024, 12, 6, 16, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_alpaca_satisfies_protocol():
    client = AlpacaMarketClient(api_key="key", secret_key="secret")
    assert isinstance(client, MarketDataProvider)


# ---------------------------------------------------------------------------
# OCC symbol parser (pure unit — no HTTP needed)
# ---------------------------------------------------------------------------


def test_parse_occ_call():
    result = _parse_occ("AAPL241206C00180000")
    assert result is not None
    underlying, expiry, option_type, strike = result
    assert underlying == "AAPL"
    assert expiry == date(2024, 12, 6)
    assert option_type == "call"
    assert strike == 180.0


def test_parse_occ_put():
    result = _parse_occ("SPY260117P00560000")
    assert result is not None
    _, expiry, option_type, strike = result
    assert expiry == date(2026, 1, 17)
    assert option_type == "put"
    assert strike == 560.0


def test_parse_occ_invalid():
    assert _parse_occ("INVALID") is None


# ---------------------------------------------------------------------------
# get_quotes
# ---------------------------------------------------------------------------


async def test_get_quotes():
    async with _client({"/v2/stocks/quotes/latest": httpx.Response(200, json=_QUOTES)}) as c:
        quotes = await c.get_quotes(["AAPL", "MSFT"])

    assert len(quotes) == 2
    aapl = next(q for q in quotes if q.symbol == "AAPL")
    assert aapl.bid == 189.25
    assert aapl.ask == 189.35
    assert aapl.bid_size == 2
    assert aapl.ask_size == 3
    assert aapl.source_name == "alpaca"
    assert aapl.timestamp == datetime(2024, 12, 6, 15, 30, 0, 123456, tzinfo=UTC)


async def test_get_quotes_api_error():
    async with _client({"/v2/stocks/quotes/latest": httpx.Response(403, text="Forbidden")}) as c:
        with pytest.raises(AlpacaAPIError) as exc_info:
            await c.get_quotes(["AAPL"])

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_bars
# ---------------------------------------------------------------------------


async def test_get_bars():
    async with _client({"/v2/stocks/bars": httpx.Response(200, json=_BARS)}) as c:
        bars = await c.get_bars("AAPL", _START, _END)

    assert len(bars) == 2
    b = bars[0]
    assert b.symbol == "AAPL"
    assert b.open == 188.00
    assert b.high == 189.50
    assert b.volume == 500000
    assert b.vwap == 188.85
    assert b.trade_count == 1200
    assert b.bar_time == datetime(2024, 12, 6, 14, 30, tzinfo=UTC)
    assert b.source_name == "alpaca"


# ---------------------------------------------------------------------------
# get_option_chain
# ---------------------------------------------------------------------------


async def test_get_option_chain():
    async with _client(
        {"/v1beta1/options/snapshots/AAPL": httpx.Response(200, json=_OPTION_SNAPSHOTS)}
    ) as c:
        chain = await c.get_option_chain("AAPL", _EXPIRY)

    assert len(chain) == 2
    call = next(c for c in chain if c.option_type == "call")
    assert call.underlying == "AAPL"
    assert call.strike == 180.0
    assert call.bid == 9.50
    assert call.ask == 9.60
    assert call.last == 9.55
    assert call.delta == 0.65
    assert call.implied_volatility == 0.255
    assert call.source_name == "alpaca"


async def test_get_option_chain_403_returns_empty():
    """Free-tier Alpaca returns 403 for options; client returns [] not raises."""
    async with _client(
        {"/v1beta1/options/snapshots/AAPL": httpx.Response(403, text="Forbidden")}
    ) as c:
        chain = await c.get_option_chain("AAPL", _EXPIRY)

    assert chain == []


# ---------------------------------------------------------------------------
# get_option_expirations
# ---------------------------------------------------------------------------


async def test_get_option_expirations():
    async with _client(
        {"/v1beta1/options/expirations/AAPL": httpx.Response(200, json=_EXPIRATIONS)}
    ) as c:
        expirations = await c.get_option_expirations("AAPL")

    assert expirations == [date(2024, 12, 6), date(2024, 12, 13), date(2024, 12, 20)]


async def test_get_option_expirations_403_returns_empty():
    async with _client(
        {"/v1beta1/options/expirations/AAPL": httpx.Response(403, text="Forbidden")}
    ) as c:
        expirations = await c.get_option_expirations("AAPL")

    assert expirations == []
