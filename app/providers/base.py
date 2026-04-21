"""
Shared data classes and structural protocol for all market-data adapters.

Detector logic imports from here only — never from concrete adapters.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """Base error raised by any market-data provider adapter."""


@dataclass
class Quote:
    symbol: str
    timestamp: datetime
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    source_name: str = ""


@dataclass
class Bar:
    symbol: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None
    trade_count: int | None = None
    source_name: str = ""


@dataclass
class OptionContractQuote:
    contract_symbol: str
    underlying: str
    expiration_date: date
    strike: float
    option_type: str  # "call" or "put"
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    last: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    source_name: str = ""


@runtime_checkable
class MarketDataProvider(Protocol):
    """
    Structural protocol every market-data adapter must satisfy.

    Concrete adapters live under app/providers/{tradier,alpaca}/client.py.
    Detector logic should depend on this protocol and these data classes only.
    """

    @property
    def source_name(self) -> str: ...

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        """Return the latest snapshot quote for each symbol."""
        ...

    async def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        """Return historical 1-minute bars for a single symbol."""
        ...

    async def get_option_chain(
        self,
        symbol: str,
        expiration: date,
    ) -> list[OptionContractQuote]:
        """Return the full option chain for one underlying + expiration."""
        ...

    async def get_option_expirations(self, symbol: str) -> list[date]:
        """Return available option expiration dates for a symbol."""
        ...
