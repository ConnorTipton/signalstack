"""Periodic Marketaux news ingestion worker (Tier 2).

Polls Marketaux for all monitored symbols and persists new articles:

  raw_marketaux_events  — full API payload (replay source)
  news_articles         — normalized article (source_tier=2)
  news_article_tickers  — one row per matched equity symbol

Dedup passes (in order):
  1. UUID idempotency  — skip if (source_name, provider_event_id) already exists
  2. Cross-source URL  — flag is_duplicate if a Tier 1 article has the same URL
  3. Same-title hash   — flag is_duplicate if another article has the same content_hash

Ticker rows are skipped for duplicate articles (the Tier 1 version already has them).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawMarketauxEvent
from app.db.session import SessionLocal
from app.ingest_news.symbol_lookup import resolve_symbol_ids
from app.providers.marketaux.client import MarketauxArticle, MarketauxClient

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 900.0  # 15 min — well within Marketaux free-tier limits
_SOURCE_NAME = "marketaux"
_NORMALIZATION_VERSION = "1"


class MarketauxWorker:
    """Async worker that periodically fetches articles from Marketaux.

    Parameters
    ----------
    symbols:
        Ticker symbols to pass to the Marketaux API.
    client:
        MarketauxClient instance. Injected for testing.
    interval_seconds:
        Seconds between poll cycles. Default 900 (15 min).
    """

    def __init__(
        self,
        symbols: list[str],
        client: MarketauxClient,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._symbols = symbols
        self._client = client
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: fetch articles, sleep, repeat until cancelled."""
        while True:
            cycle_start = datetime.now(UTC)
            await self._poll()
            elapsed = (datetime.now(UTC) - cycle_start).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    async def _poll(self) -> None:
        try:
            received_at = datetime.now(UTC)
            articles = await self._client.fetch_articles(self._symbols)
            for article in articles:
                await asyncio.to_thread(self._persist_article, article, received_at)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Marketaux poll failed: %s", exc)

    @staticmethod
    def _persist_article(article: MarketauxArticle, received_at: datetime) -> None:
        with SessionLocal() as db:
            MarketauxWorker._write_article(db, article, received_at)
            db.commit()

    @staticmethod
    def _write_article(db: Session, article: MarketauxArticle, received_at: datetime) -> None:
        """Persist one article with dedup. No-op if the UUID was already stored."""
        # Pass 1: UUID idempotency
        existing = (
            db.query(NewsArticle)
            .filter_by(source_name=_SOURCE_NAME, provider_event_id=article.uuid)
            .first()
        )
        if existing is not None:
            return

        # Write raw payload before normalized writes. Raw idempotency is keyed
        # by provider_event_id so same-title articles are still preserved.
        db.add(
            RawMarketauxEvent(
                source_name=_SOURCE_NAME,
                source_tier=2,
                provider_event_id=article.uuid,
                provider_published_at=article.published_at,
                received_at=received_at,
                content_hash=article.content_hash,
                related_url=article.url,
                normalization_version=_NORMALIZATION_VERSION,
                payload=article.raw,
            )
        )

        # Pass 2: cross-source URL dedup — Tier 1 article at same URL
        dupe: NewsArticle | None = None
        if article.url:
            dupe = (
                db.query(NewsArticle)
                .filter(NewsArticle.source_tier == 1, NewsArticle.url == article.url)
                .first()
            )

        # Pass 3: same-title dedup — another article (any tier) with same content_hash
        if dupe is None and article.content_hash:
            dupe = db.query(NewsArticle).filter_by(content_hash=article.content_hash).first()

        norm = NewsArticle(
            source_name=_SOURCE_NAME,
            source_tier=2,
            provider_event_id=article.uuid,
            provider_published_at=article.published_at,
            received_at=received_at,
            # Null out content_hash for duplicates: the partial unique index
            # (WHERE content_hash IS NOT NULL) would otherwise block the insert
            # when a same-title article already exists.
            content_hash=article.content_hash if dupe is None else None,
            related_url=article.url,
            url=article.url,
            normalization_version=_NORMALIZATION_VERSION,
            title=article.title,
            body=article.summary,
            author=article.source,
            is_duplicate=dupe is not None,
            duplicate_of_id=dupe.id if dupe else None,
        )
        db.add(norm)
        db.flush()

        # Ticker rows only for non-duplicates
        if dupe is None:
            symbol_ids = resolve_symbol_ids(db, article.tickers)
            for ticker in article.tickers:
                normalized = ticker.upper()
                db.add(
                    NewsArticleTicker(
                        article_id=norm.id,
                        symbol_id=symbol_ids.get(normalized),
                        ticker=normalized,
                    )
                )
