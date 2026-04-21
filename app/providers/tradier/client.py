from datetime import date, datetime

import httpx

from app.providers.base import Bar, OptionContractQuote, ProviderError, Quote
from app.providers.tradier.normalizer import (
    normalize_bars,
    normalize_expirations,
    normalize_option_chain,
    normalize_quotes,
)

_SANDBOX_URL = "https://sandbox.tradier.com"
_PRODUCTION_URL = "https://api.tradier.com"


class TradierAPIError(ProviderError):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        super().__init__(f"Tradier API {status_code}: {body[:200]}")


class TradierClient:
    """
    Async REST client for Tradier market/options data.

    Live verification is pending account approval. All paths are covered
    by fixture-based tests. Streaming (WebSocket) is implemented in Phase 3b.
    """

    SOURCE_NAME = "tradier"

    def __init__(
        self,
        api_token: str,
        environment: str = "sandbox",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        base_url = _SANDBOX_URL if environment == "sandbox" else _PRODUCTION_URL
        self._own_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
            },
            timeout=10.0,
        )

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    async def aclose(self) -> None:
        if self._own_client:
            await self._http.aclose()

    async def __aenter__(self) -> "TradierClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> dict:
        response = await self._http.get(path, params=params)
        if response.status_code != 200:
            raise TradierAPIError(response.status_code, response.text)
        return response.json()

    # ------------------------------------------------------------------
    # MarketDataProvider protocol methods
    # ------------------------------------------------------------------

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        raw = await self._get("/v1/markets/quotes", params={"symbols": ",".join(symbols)})
        return normalize_quotes(raw)

    async def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        # Tradier interval names: "1min", "5min", "15min", "daily"
        interval = timeframe.lower().replace("min", "min")
        raw = await self._get(
            "/v1/markets/history",
            params={
                "symbol": symbol,
                "interval": interval,
                "start": start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
            },
        )
        return normalize_bars(symbol, raw)

    async def fetch_option_chain_raw(self, symbol: str, expiration: date) -> dict:
        """Return the raw Tradier response dict for payload storage."""
        return await self._get(
            "/v1/markets/options/chains",
            params={
                "symbol": symbol,
                "expiration": expiration.isoformat(),
                "greeks": "true",
            },
        )

    async def get_option_chain(
        self,
        symbol: str,
        expiration: date,
    ) -> list[OptionContractQuote]:
        raw = await self.fetch_option_chain_raw(symbol, expiration)
        return normalize_option_chain(raw)

    async def get_option_expirations(self, symbol: str) -> list[date]:
        raw = await self._get(
            "/v1/markets/options/expirations",
            params={"symbol": symbol, "includeAllRoots": "false"},
        )
        return normalize_expirations(raw)
