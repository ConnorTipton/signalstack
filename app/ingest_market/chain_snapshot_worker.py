"""Periodic Tradier option-chain snapshot worker.

Polls option expirations for each configured symbol, fetches the chain for
the nearest two expirations (next weekly + front monthly), and persists:

  raw_tradier_events       — full Tradier response payload (replay source)
  option_chain_snapshots   — per-expiry aggregate stats (OI, volume, count)
  option_quotes            — one row per contract in the chain

Option trades streaming (subscribing to individual contract symbols) is
deferred until live Tradier account verification is complete.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.db.models.market import OptionChainSnapshot, OptionQuote
from app.db.models.raw_events import RawTradierEvent
from app.db.models.symbols import Symbol
from app.db.session import SessionLocal
from app.providers.base import OptionContractQuote
from app.providers.tradier.client import TradierClient
from app.providers.tradier.normalizer import normalize_option_chain

log = logging.getLogger(__name__)

_NORMALIZATION_VERSION = "1"
_DEFAULT_INTERVAL = 300.0  # seconds between full snapshot cycles
_DEFAULT_MAX_EXPIRATIONS = 2  # next weekly + front monthly


class ChainSnapshotWorker:
    """Async worker that periodically snapshots option chains via Tradier REST.

    Parameters
    ----------
    symbols:
        Underlying tickers to monitor (must exist in the symbols table).
    client:
        A ``TradierClient`` instance. Injected for testing.
    interval_seconds:
        Seconds between full snapshot cycles. Default 300 (5 min).
    max_expirations:
        Number of expirations to fetch per symbol per cycle. Default 2.
    """

    def __init__(
        self,
        symbols: list[str],
        client: TradierClient,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        max_expirations: int = _DEFAULT_MAX_EXPIRATIONS,
    ) -> None:
        self._symbols = symbols
        self._client = client
        self._interval = interval_seconds
        self._max_expirations = max_expirations

    async def run(self) -> None:
        """Main loop: snapshot all symbols, sleep, repeat until cancelled."""
        symbol_ids = await asyncio.to_thread(self._load_symbol_ids)
        while True:
            cycle_start = datetime.now(UTC)
            await self._snapshot_all(symbol_ids)
            elapsed = (datetime.now(UTC) - cycle_start).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    async def _snapshot_all(self, symbol_ids: dict[str, int]) -> None:
        for symbol in self._symbols:
            try:
                await self._snapshot_symbol(symbol, symbol_ids)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Chain snapshot failed for %s: %s", symbol, exc)

    async def _snapshot_symbol(self, symbol: str, symbol_ids: dict[str, int]) -> None:
        symbol_id = symbol_ids.get(symbol)
        if symbol_id is None:
            log.warning("Symbol %s not found in DB — skipping snapshot", symbol)
            return

        expirations = await self._client.get_option_expirations(symbol)
        targets = pick_expirations(expirations, self._max_expirations)
        if not targets:
            log.debug("No active expirations found for %s", symbol)
            return

        for expiry in targets:
            received_at = datetime.now(UTC)
            raw = await self._client.fetch_option_chain_raw(symbol, expiry)
            contracts = normalize_option_chain(raw)
            if not contracts:
                log.debug("Empty chain for %s %s — skipping", symbol, expiry)
                continue
            await asyncio.to_thread(
                self._persist_chain, raw, contracts, symbol, symbol_id, expiry, received_at
            )
            log.info(
                "Snapshot: %s %s — %d contracts stored",
                symbol,
                expiry,
                len(contracts),
            )

    # ------------------------------------------------------------------
    # DB operations — run in thread pool; _write_chain takes a session
    # directly so integration tests can inject db_session
    # ------------------------------------------------------------------

    def _persist_chain(
        self,
        raw: dict,
        contracts: list[OptionContractQuote],
        symbol: str,
        symbol_id: int,
        expiry: date,
        received_at: datetime,
    ) -> None:
        with SessionLocal() as db:
            self._write_chain(db, raw, contracts, symbol, symbol_id, expiry, received_at)
            db.commit()

    @staticmethod
    def _write_chain(
        db: Session,
        raw: dict,
        contracts: list[OptionContractQuote],
        symbol: str,
        symbol_id: int,
        expiry: date,
        received_at: datetime,
    ) -> None:
        db.add(
            RawTradierEvent(
                received_at=received_at,
                provider_event_id=f"{symbol}:{expiry.isoformat()}",
                normalization_version=_NORMALIZATION_VERSION,
                payload=raw,
            )
        )

        calls = [c for c in contracts if c.option_type == "call"]
        puts = [c for c in contracts if c.option_type == "put"]
        db.add(
            OptionChainSnapshot(
                snapshot_time=received_at,
                symbol_id=symbol_id,
                expiration_date=expiry,
                contract_count=len(contracts),
                total_call_oi=sum(c.open_interest or 0 for c in calls),
                total_put_oi=sum(c.open_interest or 0 for c in puts),
                total_call_volume=sum(c.volume or 0 for c in calls),
                total_put_volume=sum(c.volume or 0 for c in puts),
                source_name="tradier",
            )
        )

        for contract in contracts:
            db.add(
                OptionQuote(
                    quote_time=received_at,
                    symbol_id=symbol_id,
                    contract_symbol=contract.contract_symbol,
                    expiration_date=contract.expiration_date,
                    strike=contract.strike,
                    option_type=contract.option_type,
                    bid=contract.bid,
                    ask=contract.ask,
                    bid_size=contract.bid_size,
                    ask_size=contract.ask_size,
                    last=contract.last,
                    open_interest=contract.open_interest,
                    volume=contract.volume,
                    implied_volatility=contract.implied_volatility,
                    delta=contract.delta,
                    source_name="tradier",
                )
            )

    def _load_symbol_ids(self) -> dict[str, int]:
        with SessionLocal() as db:
            rows = db.query(Symbol).filter(Symbol.ticker.in_(self._symbols)).all()
            return {r.ticker: r.id for r in rows}


def pick_expirations(expirations: list[date], max_count: int) -> list[date]:
    """Return the nearest ``max_count`` expirations that are today or later."""
    today = date.today()
    return sorted(e for e in expirations if e >= today)[:max_count]
