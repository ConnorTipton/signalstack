"""Periodic Alpaca bar ingestion worker.

Used as the Mode A market-data path when Tradier streaming is unavailable.
Each poll stores the raw Alpaca bars response first, then upserts normalized
1-minute bars into ``underlying_bars_1m``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models.market import UnderlyingBar1m
from app.db.models.provider import ProviderHealth
from app.db.models.raw_events import RawAlpacaMarketEvent
from app.db.models.symbols import Symbol
from app.db.session import SessionLocal
from app.providers.alpaca.client import AlpacaMarketClient
from app.providers.alpaca.normalizer import normalize_bars
from app.providers.base import Bar

log = logging.getLogger(__name__)

_NORMALIZATION_VERSION = "1"
_DEFAULT_INTERVAL = 60.0
_DEFAULT_LOOKBACK_MINUTES = 10


class AlpacaBarWorker:
    """Async worker that polls Alpaca stock bars and stores normalized bars."""

    def __init__(
        self,
        symbols: list[str],
        client: AlpacaMarketClient,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        lookback_minutes: int = _DEFAULT_LOOKBACK_MINUTES,
    ) -> None:
        self._symbols = symbols
        self._client = client
        self._interval = interval_seconds
        self._lookback_minutes = lookback_minutes
        self._consecutive_failures = 0
        self._last_success_at: datetime | None = None

    async def run(self) -> None:
        """Main loop: poll bars, sleep, repeat until cancelled."""
        symbol_ids = await asyncio.to_thread(self._load_symbol_ids)
        while True:
            cycle_start = datetime.now(UTC)
            try:
                await self._poll(symbol_ids)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consecutive_failures += 1
                await self._record_health(is_healthy=False, error=str(exc))
                log.warning("Alpaca bar poll failed: %s", exc)
            elapsed = (datetime.now(UTC) - cycle_start).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    async def _poll(self, symbol_ids: dict[str, int]) -> None:
        end = datetime.now(UTC).replace(second=0, microsecond=0)
        start = end - timedelta(minutes=self._lookback_minutes)
        received_at = datetime.now(UTC)
        raw = await self._client.fetch_bars_raw(self._symbols, start, end)
        bars = normalize_bars(raw)
        await asyncio.to_thread(self._persist, raw, bars, received_at, symbol_ids, start, end)
        self._consecutive_failures = 0
        self._last_success_at = received_at
        await self._record_health(is_healthy=True)
        if bars:
            log.info("AlpacaBarWorker: stored %d bar(s)", len(bars))

    def _persist(
        self,
        raw: dict,
        bars: list[Bar],
        received_at: datetime,
        symbol_ids: dict[str, int],
        start: datetime,
        end: datetime,
    ) -> None:
        with SessionLocal() as db:
            self._write_bars(db, raw, bars, received_at, symbol_ids, start, end)
            db.commit()

    @staticmethod
    def _write_bars(
        db: Session,
        raw: dict,
        bars: list[Bar],
        received_at: datetime,
        symbol_ids: dict[str, int],
        start: datetime,
        end: datetime,
    ) -> None:
        db.add(
            RawAlpacaMarketEvent(
                received_at=received_at,
                provider_event_id=f"bars:{start.isoformat()}:{end.isoformat()}",
                provider_published_at=end,
                normalization_version=_NORMALIZATION_VERSION,
                payload=raw,
            )
        )

        rows = []
        for bar in bars:
            symbol_id = symbol_ids.get(bar.symbol)
            if symbol_id is None:
                continue
            rows.append(
                {
                    "bar_time": bar.bar_time,
                    "symbol_id": symbol_id,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "vwap": bar.vwap,
                    "trade_count": bar.trade_count,
                    "source_name": "alpaca",
                }
            )
        if rows:
            stmt = insert(UnderlyingBar1m).values(rows)
            db.execute(stmt.on_conflict_do_nothing(index_elements=["bar_time", "symbol_id"]))

    def _load_symbol_ids(self) -> dict[str, int]:
        with SessionLocal() as db:
            rows = db.query(Symbol).filter(Symbol.ticker.in_(self._symbols)).all()
            return {r.ticker: r.id for r in rows}

    async def _record_health(
        self,
        *,
        is_healthy: bool,
        error: str | None = None,
    ) -> None:
        await asyncio.to_thread(self._record_health_sync, is_healthy=is_healthy, error=error)

    def _record_health_sync(self, *, is_healthy: bool, error: str | None) -> None:
        confidence = 1.0 if is_healthy else max(0.0, 1.0 - 0.2 * self._consecutive_failures)
        with SessionLocal() as db:
            db.add(
                ProviderHealth(
                    checked_at=datetime.now(UTC),
                    provider_name="alpaca",
                    is_healthy=is_healthy,
                    provider_confidence=round(confidence, 3),
                    last_success_at=self._last_success_at,
                    consecutive_failures=self._consecutive_failures,
                    error_message=error,
                )
            )
            db.commit()
