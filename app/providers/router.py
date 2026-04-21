"""Provider router: picks Tradier (primary) or Alpaca (fallback) per request.

Mode A — no TRADIER_API_TOKEN configured: Alpaca-only, no health check.
Mode B — Tradier configured: Tradier primary; falls back to Alpaca when the
most recent provider_health record for "tradier" within the TTL window is
absent or marks Tradier as unhealthy.

The router implements the full MarketDataProvider protocol so callers never
need to know which concrete adapter is active.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from app.core.config import settings
from app.db.models.provider import ProviderHealth
from app.db.session import SessionLocal
from app.providers.alpaca.client import AlpacaMarketClient
from app.providers.base import Bar, MarketDataProvider, OptionContractQuote, Quote
from app.providers.tradier.client import TradierClient

_DEFAULT_HEALTH_TTL = 120.0  # seconds; Tradier is "unknown" if no record within this window


class ProviderRouter:
    """Routes MarketDataProvider calls to Tradier or Alpaca based on health state.

    Parameters
    ----------
    primary:
        The preferred provider (Tradier). ``None`` forces Mode A (Alpaca-only).
    fallback:
        The fallback provider (Alpaca). Always used in Mode A; used in Mode B
        when Tradier has no recent healthy record.
    health_ttl_seconds:
        How recent a provider_health record must be to count as evidence that
        Tradier is healthy. Older records are treated as absent.
    """

    def __init__(
        self,
        *,
        primary: MarketDataProvider | None,
        fallback: MarketDataProvider,
        health_ttl_seconds: float = _DEFAULT_HEALTH_TTL,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._health_ttl = health_ttl_seconds

    @property
    def source_name(self) -> str:
        return (
            self._primary.source_name if self._primary is not None else self._fallback.source_name
        )

    async def aclose(self) -> None:
        for p in (self._primary, self._fallback):
            if p is not None and hasattr(p, "aclose"):
                await p.aclose()  # type: ignore[union-attr]

    async def __aenter__(self) -> ProviderRouter:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    async def _active(self) -> MarketDataProvider:
        if self._primary is None:
            return self._fallback
        healthy = await asyncio.to_thread(
            _check_health, self._primary.source_name, self._health_ttl
        )
        return self._primary if healthy else self._fallback

    # ------------------------------------------------------------------
    # MarketDataProvider protocol
    # ------------------------------------------------------------------

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        provider = await self._active()
        return await provider.get_quotes(symbols)

    async def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        provider = await self._active()
        return await provider.get_bars(symbol, start, end, timeframe)

    async def get_option_chain(
        self,
        symbol: str,
        expiration: date,
    ) -> list[OptionContractQuote]:
        provider = await self._active()
        return await provider.get_option_chain(symbol, expiration)

    async def get_option_expirations(self, symbol: str) -> list[date]:
        provider = await self._active()
        return await provider.get_option_expirations(symbol)


def _check_health(provider_name: str, ttl_seconds: float) -> bool:
    """Return True iff provider has a healthy record within the TTL window."""
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
    with SessionLocal() as db:
        row = (
            db.query(ProviderHealth)
            .filter(
                ProviderHealth.provider_name == provider_name,
                ProviderHealth.checked_at >= cutoff,
            )
            .order_by(ProviderHealth.checked_at.desc())
            .first()
        )
        return bool(row and row.is_healthy)


def build_router(health_ttl_seconds: float = _DEFAULT_HEALTH_TTL) -> ProviderRouter:
    """Construct a ProviderRouter from the current settings.

    Mode A (no ``TRADIER_API_TOKEN``): primary=None, Alpaca-only.
    Mode B (Tradier configured): Tradier primary, Alpaca fallback.
    """
    fallback = AlpacaMarketClient(
        api_key=settings.alpaca_api_key or "",
        secret_key=settings.alpaca_secret_key or "",
    )

    if not settings.tradier_api_token:
        return ProviderRouter(
            primary=None,
            fallback=fallback,
            health_ttl_seconds=health_ttl_seconds,
        )

    primary = TradierClient(
        api_token=settings.tradier_api_token,
        environment=settings.tradier_environment,
    )
    return ProviderRouter(
        primary=primary,
        fallback=fallback,
        health_ttl_seconds=health_ttl_seconds,
    )
