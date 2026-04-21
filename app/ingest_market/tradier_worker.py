"""Long-lived Tradier market-data streaming worker.

Connects to Tradier's HTTP streaming endpoint, writes raw payloads to
raw_tradier_events first, then normalizes quotes into underlying_quotes.
Tracks connection health in provider_health on every state change.

Live end-to-end verification is pending Tradier account approval. The
session_factory and stream_factory parameters are injectable so tests can
run the full worker loop without real HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.market import UnderlyingQuote
from app.db.models.provider import ProviderHealth
from app.db.models.raw_events import RawTradierEvent
from app.db.models.symbols import Symbol
from app.db.session import SessionLocal
from app.providers.tradier.normalizer import normalize_stream_quote
from app.providers.tradier.stream import (
    create_session,
    stream_market_events,
)

log = logging.getLogger(__name__)

_NORMALIZATION_VERSION = "1"
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_JITTER_FACTOR = 0.3


class TradierWorker:
    """Async worker that streams Tradier market events and persists them.

    Parameters
    ----------
    symbols:
        Tickers to subscribe to (must exist in the symbols table).
    session_factory:
        ``async (api_token, base_url) -> (session_id, stream_url)``.
        Defaults to :func:`~app.providers.tradier.stream.create_session`.
    stream_factory:
        ``async (session_id, stream_url, symbols) -> AsyncIterator[dict]``.
        Defaults to :func:`~app.providers.tradier.stream.stream_market_events`.
    """

    def __init__(
        self,
        symbols: list[str],
        *,
        session_factory: Callable | None = None,
        stream_factory: Callable | None = None,
    ) -> None:
        self._symbols = symbols
        self._session_factory = session_factory or create_session
        self._stream_factory = stream_factory or stream_market_events
        self._consecutive_failures = 0
        self._last_success_at: datetime | None = None

    async def run(self) -> None:
        """Main reconnect loop. Runs until cancelled."""
        while True:
            try:
                await self._connect_and_consume()
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consecutive_failures += 1
                await self._record_health(is_healthy=False, error=str(exc))
                delay = self._backoff()
                log.warning(
                    "Tradier stream error (failure #%d): %s — reconnecting in %.1fs",
                    self._consecutive_failures,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _connect_and_consume(self) -> None:
        api_token = settings.tradier_api_token or ""
        base_url = (
            "https://sandbox.tradier.com"
            if settings.tradier_environment == "sandbox"
            else "https://api.tradier.com"
        )

        session_id, stream_url = await self._session_factory(api_token, base_url)
        symbol_ids = await asyncio.to_thread(self._load_symbol_ids)
        await self._record_health(is_healthy=True)
        log.info(
            "Tradier stream connected — subscribed to %d symbols",
            len(self._symbols),
        )

        async for event in self._stream_factory(session_id, stream_url, self._symbols):
            received_at = datetime.now(UTC)
            await asyncio.to_thread(self._persist, event, received_at, symbol_ids)
            self._last_success_at = received_at

    # ------------------------------------------------------------------
    # DB operations — run in thread pool to avoid blocking the event loop
    # ------------------------------------------------------------------

    def _load_symbol_ids(self) -> dict[str, int]:
        with SessionLocal() as db:
            rows = db.query(Symbol).filter(Symbol.ticker.in_(self._symbols)).all()
            return {r.ticker: r.id for r in rows}

    def _persist(
        self,
        event: dict,
        received_at: datetime,
        symbol_ids: dict[str, int],
    ) -> None:
        with SessionLocal() as db:
            self._insert_raw(db, event, received_at)
            if event.get("type") == "quote":
                self._insert_quote(db, event, received_at, symbol_ids)
            db.commit()

    @staticmethod
    def _insert_raw(db: Session, event: dict, received_at: datetime) -> None:
        db.add(
            RawTradierEvent(
                received_at=received_at,
                provider_event_id=event.get("symbol"),
                provider_published_at=_event_ts(event),
                normalization_version=_NORMALIZATION_VERSION,
                payload=event,
            )
        )

    @staticmethod
    def _insert_quote(
        db: Session,
        event: dict,
        received_at: datetime,
        symbol_ids: dict[str, int],
    ) -> None:
        quote = normalize_stream_quote(event)
        if quote is None:
            return
        symbol_id = symbol_ids.get(quote.symbol)
        if symbol_id is None:
            return
        db.add(
            UnderlyingQuote(
                quote_time=quote.timestamp,
                symbol_id=symbol_id,
                bid=quote.bid,
                ask=quote.ask,
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
                last=quote.last,
                source_name="tradier",
            )
        )

    async def _record_health(
        self,
        *,
        is_healthy: bool,
        error: str | None = None,
        lag_seconds: float | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._record_health_sync,
            is_healthy=is_healthy,
            error=error,
            lag_seconds=lag_seconds,
        )

    def _record_health_sync(
        self,
        *,
        is_healthy: bool,
        error: str | None,
        lag_seconds: float | None,
    ) -> None:
        failures = self._consecutive_failures
        confidence = 1.0 if is_healthy else max(0.0, 1.0 - 0.2 * failures)
        with SessionLocal() as db:
            db.add(
                ProviderHealth(
                    checked_at=datetime.now(UTC),
                    provider_name="tradier",
                    is_healthy=is_healthy,
                    provider_confidence=round(confidence, 3),
                    last_success_at=self._last_success_at,
                    consecutive_failures=failures,
                    lag_seconds=lag_seconds,
                    error_message=error,
                )
            )
            db.commit()

    def _backoff(self) -> float:
        """Exponential backoff with jitter, capped at _BACKOFF_MAX."""
        base = min(_BACKOFF_BASE * (2 ** (self._consecutive_failures - 1)), _BACKOFF_MAX)
        return base + random.uniform(0, base * _JITTER_FACTOR)


def _event_ts(event: dict) -> datetime | None:
    """Extract the event's own timestamp from biddate/askdate (epoch ms strings)."""
    for key in ("biddate", "askdate", "date"):
        raw = event.get(key)
        if raw is None:
            continue
        try:
            return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)
        except (ValueError, TypeError):
            continue
    return None
