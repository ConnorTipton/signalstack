from datetime import date, datetime

import httpx

from app.providers.alpaca.normalizer import (
    normalize_bars,
    normalize_expirations,
    normalize_option_chain,
    normalize_quotes,
)
from app.providers.base import Bar, OptionContractQuote, ProviderError, Quote

_DATA_URL = "https://data.alpaca.markets"

# Free IEX feed; switch to "sip" with a paid data subscription.
_DEFAULT_FEED = "iex"


class AlpacaAPIError(ProviderError):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        super().__init__(f"Alpaca API {status_code}: {body[:200]}")


class AlpacaMarketClient:
    """
    Async REST client for Alpaca market/options data.

    Uses the free IEX feed by default. Options chain endpoints require an
    Alpaca options data subscription; they will raise AlpacaAPIError 403
    on the free tier. Streaming (WebSocket) is implemented in Phase 3b.
    """

    SOURCE_NAME = "alpaca"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str = _DEFAULT_FEED,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._feed = feed
        self._own_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=_DATA_URL,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=10.0,
        )

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    async def aclose(self) -> None:
        if self._own_client:
            await self._http.aclose()

    async def __aenter__(self) -> "AlpacaMarketClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> dict:
        response = await self._http.get(path, params=params)
        if response.status_code != 200:
            raise AlpacaAPIError(response.status_code, response.text)
        return response.json()

    # ------------------------------------------------------------------
    # MarketDataProvider protocol methods
    # ------------------------------------------------------------------

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        raw = await self._get(
            "/v2/stocks/quotes/latest",
            params={"symbols": ",".join(symbols), "feed": self._feed},
        )
        return normalize_quotes(raw)

    async def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        raw = await self._get(
            "/v2/stocks/bars",
            params={
                "symbols": symbol,
                "timeframe": timeframe,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "feed": self._feed,
                "limit": 10_000,
            },
        )
        return normalize_bars(raw)

    async def get_option_chain(
        self,
        symbol: str,
        expiration: date,
    ) -> list[OptionContractQuote]:
        """
        Requires an Alpaca options data subscription.
        Returns an empty list (not an error) on 403 so the router can fall back
        to proxy mode without crashing.
        """
        try:
            raw = await self._get(
                f"/v1beta1/options/snapshots/{symbol}",
                params={"expiration_date": expiration.isoformat()},
            )
        except AlpacaAPIError as exc:
            if exc.status_code == 403:
                return []
            raise
        return normalize_option_chain(raw)

    async def get_option_expirations(self, symbol: str) -> list[date]:
        try:
            raw = await self._get(
                f"/v1beta1/options/expirations/{symbol}",
            )
        except AlpacaAPIError as exc:
            if exc.status_code == 403:
                return []
            raise
        return normalize_expirations(raw)
