"""Periodic RSS/Atom feed ingestion worker for IR feeds and financial wire services.

Polls all configured feeds and persists new entries:

  raw_official_news_events  — full feed entry payload (replay source)
  news_articles             — normalized article record
  news_article_tickers      — one row per matched ticker

Wire feed entries with no ticker match are dropped. Idempotent: a second write
for the same (source_name, provider_event_id) is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawOfficialNewsEvent
from app.db.session import SessionLocal
from app.providers.official_feeds.rss import FeedConfig, RssEntry, RssPoller, extract_tickers

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 300.0
_NORMALIZATION_VERSION = "1"


class RssWorker:
    """Async worker that polls a configurable list of RSS/Atom feeds.

    Parameters
    ----------
    feeds:
        List of FeedConfig objects describing every feed to poll.
    monitored_tickers:
        Set of ticker symbols used for wire-feed ticker extraction. Not needed
        for IR feeds (where FeedConfig.ticker is already set).
    poller:
        Injected RssPoller for testing. When None, a default poller is created.
    interval_seconds:
        Seconds between full poll cycles. Default 300 (5 min).
    """

    def __init__(
        self,
        feeds: list[FeedConfig],
        monitored_tickers: set[str],
        *,
        poller: RssPoller | None = None,
        interval_seconds: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._feeds = feeds
        self._monitored = monitored_tickers
        self._poller = poller or RssPoller()
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: poll all feeds, sleep, repeat until cancelled."""
        while True:
            cycle_start = datetime.now(UTC)
            await self._poll_all()
            elapsed = (datetime.now(UTC) - cycle_start).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    async def _poll_all(self) -> None:
        for config in self._feeds:
            try:
                await self._poll_feed(config)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("RSS poll failed for %s: %s", config.url, exc)

    async def _poll_feed(self, config: FeedConfig) -> None:
        received_at = datetime.now(UTC)
        entries = await self._poller.poll(config)
        for entry in entries:
            tickers = extract_tickers(entry, config, self._monitored)
            if not tickers:
                log.debug("No ticker match — skipping: %s", entry.title)
                continue
            await asyncio.to_thread(self._persist_entry, entry, tickers, received_at)

    @staticmethod
    def _persist_entry(entry: RssEntry, tickers: list[str], received_at: datetime) -> None:
        with SessionLocal() as db:
            RssWorker._write_entry(db, entry, tickers, received_at)
            db.commit()

    @staticmethod
    def _write_entry(
        db: Session,
        entry: RssEntry,
        tickers: list[str],
        received_at: datetime,
    ) -> None:
        """Write one RSS entry to the DB; no-op if already present."""
        existing = (
            db.query(NewsArticle)
            .filter_by(source_name=entry.source_name, provider_event_id=entry.provider_event_id)
            .first()
        )
        if existing is not None:
            return

        db.add(
            RawOfficialNewsEvent(
                source_name=entry.source_name,
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
            source_name=entry.source_name,
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

        for ticker in tickers:
            db.add(NewsArticleTicker(article_id=article.id, ticker=ticker))
