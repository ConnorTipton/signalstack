"""Unit tests for the provider router."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

from app.providers.base import MarketDataProvider
from app.providers.router import ProviderRouter

_START = datetime(2024, 12, 6, 9, 30, tzinfo=UTC)
_END = datetime(2024, 12, 6, 16, 0, tzinfo=UTC)
_EXPIRY = date(2024, 12, 13)


def _mock_provider(source: str) -> MagicMock:
    p = MagicMock()
    p.source_name = source
    p.get_quotes = AsyncMock(return_value=[])
    p.get_bars = AsyncMock(return_value=[])
    p.get_option_chain = AsyncMock(return_value=[])
    p.get_option_expirations = AsyncMock(return_value=[])
    return p


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_router_satisfies_protocol():
    router = ProviderRouter(primary=None, fallback=_mock_provider("alpaca"))
    assert isinstance(router, MarketDataProvider)


def test_router_with_primary_satisfies_protocol():
    router = ProviderRouter(
        primary=_mock_provider("tradier"),
        fallback=_mock_provider("alpaca"),
    )
    assert isinstance(router, MarketDataProvider)


# ---------------------------------------------------------------------------
# source_name
# ---------------------------------------------------------------------------


def test_source_name_mode_a_is_fallback():
    router = ProviderRouter(primary=None, fallback=_mock_provider("alpaca"))
    assert router.source_name == "alpaca"


def test_source_name_mode_b_is_primary():
    router = ProviderRouter(
        primary=_mock_provider("tradier"),
        fallback=_mock_provider("alpaca"),
    )
    assert router.source_name == "tradier"


# ---------------------------------------------------------------------------
# Mode A — always uses fallback
# ---------------------------------------------------------------------------


async def test_mode_a_get_quotes_uses_fallback():
    fallback = _mock_provider("alpaca")
    router = ProviderRouter(primary=None, fallback=fallback)
    await router.get_quotes(["AAPL"])
    fallback.get_quotes.assert_awaited_once_with(["AAPL"])


async def test_mode_a_get_bars_uses_fallback():
    fallback = _mock_provider("alpaca")
    router = ProviderRouter(primary=None, fallback=fallback)
    await router.get_bars("AAPL", _START, _END)
    fallback.get_bars.assert_awaited_once_with("AAPL", _START, _END, "1Min")


async def test_mode_a_get_option_chain_uses_fallback():
    fallback = _mock_provider("alpaca")
    router = ProviderRouter(primary=None, fallback=fallback)
    await router.get_option_chain("AAPL", _EXPIRY)
    fallback.get_option_chain.assert_awaited_once_with("AAPL", _EXPIRY)


async def test_mode_a_get_option_expirations_uses_fallback():
    fallback = _mock_provider("alpaca")
    router = ProviderRouter(primary=None, fallback=fallback)
    await router.get_option_expirations("AAPL")
    fallback.get_option_expirations.assert_awaited_once_with("AAPL")


# ---------------------------------------------------------------------------
# Mode B — routes based on health
# ---------------------------------------------------------------------------


async def test_mode_b_healthy_tradier_uses_primary(monkeypatch):
    monkeypatch.setattr("app.providers.router._check_health", lambda name, ttl: True)
    primary = _mock_provider("tradier")
    fallback = _mock_provider("alpaca")
    router = ProviderRouter(primary=primary, fallback=fallback)

    await router.get_quotes(["AAPL"])

    primary.get_quotes.assert_awaited_once_with(["AAPL"])
    fallback.get_quotes.assert_not_awaited()


async def test_mode_b_unhealthy_tradier_uses_fallback(monkeypatch):
    monkeypatch.setattr("app.providers.router._check_health", lambda name, ttl: False)
    primary = _mock_provider("tradier")
    fallback = _mock_provider("alpaca")
    router = ProviderRouter(primary=primary, fallback=fallback)

    await router.get_quotes(["AAPL"])

    primary.get_quotes.assert_not_awaited()
    fallback.get_quotes.assert_awaited_once_with(["AAPL"])


async def test_mode_b_health_check_receives_primary_name(monkeypatch):
    checked: list[str] = []
    monkeypatch.setattr(
        "app.providers.router._check_health",
        lambda name, ttl: checked.append(name) or False,
    )
    primary = _mock_provider("tradier")
    router = ProviderRouter(primary=primary, fallback=_mock_provider("alpaca"))
    await router.get_quotes(["AAPL"])
    assert checked == ["tradier"]


async def test_mode_b_health_check_receives_configured_ttl(monkeypatch):
    received_ttl: list[float] = []
    monkeypatch.setattr(
        "app.providers.router._check_health",
        lambda name, ttl: received_ttl.append(ttl) or False,
    )
    router = ProviderRouter(
        primary=_mock_provider("tradier"),
        fallback=_mock_provider("alpaca"),
        health_ttl_seconds=60.0,
    )
    await router.get_quotes(["AAPL"])
    assert received_ttl == [60.0]


# ---------------------------------------------------------------------------
# build_router — mode selection from settings
# ---------------------------------------------------------------------------


def test_build_router_mode_a_when_no_tradier_token(monkeypatch):
    from app.providers.router import build_router

    monkeypatch.setattr("app.providers.router.settings.tradier_api_token", None)
    monkeypatch.setattr("app.providers.router.settings.alpaca_api_key", "key")
    monkeypatch.setattr("app.providers.router.settings.alpaca_secret_key", "secret")

    router = build_router()
    assert router._primary is None
    assert router.source_name == "alpaca"


def test_build_router_mode_b_when_tradier_configured(monkeypatch):
    from app.providers.router import build_router

    monkeypatch.setattr("app.providers.router.settings.tradier_api_token", "fake-token")
    monkeypatch.setattr("app.providers.router.settings.tradier_environment", "sandbox")
    monkeypatch.setattr("app.providers.router.settings.alpaca_api_key", "key")
    monkeypatch.setattr("app.providers.router.settings.alpaca_secret_key", "secret")

    router = build_router()
    assert router._primary is not None
    assert router.source_name == "tradier"
