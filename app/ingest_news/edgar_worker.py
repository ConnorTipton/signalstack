"""Periodic SEC EDGAR filings ingestion worker.

Polls the EDGAR Atom feed for each configured ticker and persists:

  raw_official_news_events  — full feed entry payload (replay source)
  news_articles             — normalized filing record
  news_article_tickers      — ticker association for the article

Idempotent: a second write for the same provider_event_id is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawOfficialNewsEvent
from app.db.session import SessionLocal
from app.providers.official_feeds.edgar import EdgarEntry, EdgarPoller

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 300.0  # seconds between full poll cycles
_SOURCE_NAME = "edgar"
_NORMALIZATION_VERSION = "1"


class EdgarWorker:
    """Async worker that polls EDGAR RSS for all monitored tickers.

    Parameters
    ----------
    tickers:
        Ticker symbols to monitor. EDGAR accepts tickers directly in place
        of CIK numbers.
    poller:
        Injected EdgarPoller for testing. When None, a default poller is created.
    interval_seconds:
        Seconds between full poll cycles. Default 300 (5 min).
    """

    def __init__(
        self,
        tickers: list[str],
        *,
        poller: EdgarPoller | None = None,
        interval_seconds: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._tickers = tickers
        self._poller = poller or EdgarPoller()
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: poll all tickers, sleep, repeat until cancelled."""
        while True:
            cycle_start = datetime.now(UTC)
            await self._poll_all()
            elapsed = (datetime.now(UTC) - cycle_start).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    async def _poll_all(self) -> None:
        for ticker in self._tickers:
            try:
                await self._poll_ticker(ticker)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("EDGAR poll failed for %s: %s", ticker, exc)

    async def _poll_ticker(self, ticker: str) -> None:
        received_at = datetime.now(UTC)
        entries = await self._poller.poll(ticker)
        for entry in entries:
            await asyncio.to_thread(self._persist_entry, entry, received_at)

    @staticmethod
    def _persist_entry(entry: EdgarEntry, received_at: datetime) -> None:
        with SessionLocal() as db:
            EdgarWorker._write_entry(db, entry, received_at)
            db.commit()

    @staticmethod
    def _write_entry(db: Session, entry: EdgarEntry, received_at: datetime) -> None:
        """Write one EDGAR entry to the DB; no-op if already present."""
        existing = (
            db.query(NewsArticle)
            .filter_by(source_name=_SOURCE_NAME, provider_event_id=entry.provider_event_id)
            .first()
        )
        if existing is not None:
            return

        db.add(
            RawOfficialNewsEvent(
                source_name=_SOURCE_NAME,
                source_tier=1,
                provider_event_id=entry.provider_event_id,
                provider_published_at=entry.published_at,
                received_at=received_at,
                content_hash=entry.content_hash,
                related_url=entry.url,
                normalization_version=_NORMALIZATION_VERSION,
                payload=entry.raw,
            )
        )

        article = NewsArticle(
            source_name=_SOURCE_NAME,
            source_tier=1,
            provider_event_id=entry.provider_event_id,
            provider_published_at=entry.published_at,
            received_at=received_at,
            content_hash=entry.content_hash,
            related_url=entry.url,
            url=entry.url,
            normalization_version=_NORMALIZATION_VERSION,
            title=entry.title,
            body=entry.summary,
        )
        db.add(article)
        db.flush()

        db.add(
            NewsArticleTicker(
                article_id=article.id,
                ticker=entry.ticker,
            )
        )
