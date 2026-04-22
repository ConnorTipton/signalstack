"""Bar aggregator worker.

Every 60 seconds, rolls up the previous completed 1-minute window of
underlying_quotes into underlying_bars_1m rows (one row per symbol).

OHLC is derived from the `last` price field.  VWAP is approximated as
the mean of the bid/ask midpoint across quotes in the window — a reasonable
proxy when per-trade volume is not available from the streaming feed.

Bars are skipped for any symbol that has no quotes with a non-null `last`
in the window.  Duplicate inserts (same bar_time + symbol_id) are ignored
via ON CONFLICT DO NOTHING so the worker is safe to restart.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_SOURCE_NAME = "tradier"


class BarAggregatorWorker:
    """Async worker that builds 1-minute bars from streaming quotes.

    Parameters
    ----------
    interval_seconds:
        How often to run. Should match the bar width (default 60).
    """

    def __init__(self, *, interval_seconds: float = 60.0) -> None:
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: wait for the next minute boundary, aggregate, repeat."""
        while True:
            now = datetime.now(UTC)
            # Sleep until the start of the next whole minute
            next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            await asyncio.sleep((next_minute - now).total_seconds())

            window_end = next_minute
            window_start = window_end - timedelta(minutes=1)
            try:
                await asyncio.to_thread(self._aggregate, window_start, window_end)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("BarAggregator error for window %s: %s", window_start, exc)

    def _aggregate(self, window_start: datetime, window_end: datetime) -> None:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    INSERT INTO underlying_bars_1m
                        (bar_time, symbol_id, open, high, low, close,
                         volume, vwap, trade_count, source_name)
                    SELECT
                        :bar_time,
                        symbol_id,
                        -- OHLC from last price (ordered by quote_time)
                        (ARRAY_AGG(last ORDER BY quote_time))[1]          AS open,
                        MAX(last)                                          AS high,
                        MIN(last)                                          AS low,
                        (ARRAY_AGG(last ORDER BY quote_time DESC))[1]     AS close,
                        0                                                  AS volume,
                        -- VWAP proxy: mean of bid/ask midpoint
                        AVG((bid + ask) / 2.0)                            AS vwap,
                        COUNT(*)                                           AS trade_count,
                        :source_name
                    FROM underlying_quotes
                    WHERE quote_time >= :window_start
                      AND quote_time <  :window_end
                      AND last IS NOT NULL
                    GROUP BY symbol_id
                    ON CONFLICT (bar_time, symbol_id) DO NOTHING
                """),
                {
                    "bar_time": window_start,
                    "window_start": window_start,
                    "window_end": window_end,
                    "source_name": _SOURCE_NAME,
                },
            )
            db.commit()
            if rows.rowcount:
                log.info(
                    "BarAggregator: built %d bar(s) for %s",
                    rows.rowcount,
                    window_start.strftime("%H:%M"),
                )
