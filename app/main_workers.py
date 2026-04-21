"""Worker orchestrator — starts all ingestion workers as concurrent asyncio tasks.

Usage:
    uv run python -m app.main_workers

Workers started:
    - EdgarWorker         (SEC EDGAR RSS, Tier 1 news)
    - RssWorker           (IR feeds + wire services, Tier 1 news)
    - MarketauxWorker     (Marketaux API, Tier 2 news)
    - LabelWorker         (LLM labeling of unlabeled articles)
    - ChainSnapshotWorker (Tradier option chains — only when TRADIER_API_TOKEN is set)

Press Ctrl-C to stop all workers gracefully.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.config import settings
from app.ingest_news.edgar_worker import EdgarWorker
from app.ingest_news.label_worker import LabelWorker
from app.ingest_news.marketaux_worker import MarketauxWorker
from app.ingest_news.rss_worker import RssWorker
from app.providers.marketaux.client import MarketauxClient
from app.providers.official_feeds.rss import FeedConfig

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monitored tickers — edit to add/remove symbols
# ---------------------------------------------------------------------------
TICKERS: list[str] = [
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMZN",
    "META",
    "GOOGL",
    "AMD",
    "SPY",
    "QQQ",
]

# ---------------------------------------------------------------------------
# RSS / wire feeds — add issuer IR feeds here as coverage expands
# ---------------------------------------------------------------------------
RSS_FEEDS: list[FeedConfig] = [
    FeedConfig(
        url="https://feeds.businesswire.com/rss/home/?rss=G22",
        source_name="businesswire",
    ),
    FeedConfig(
        url="https://www.globenewswire.com/RssFeed/subjectcode/15-Major+Periodic+Reports",
        source_name="globenewswire",
    ),
    FeedConfig(
        url="https://prnewswire.com/rss/news-releases-list.rss",
        source_name="prnewswire",
    ),
]


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    log.info("Starting SignalStack workers (mode=%s)", settings.runtime_mode.value)

    edgar = EdgarWorker(tickers=TICKERS)
    rss = RssWorker(feeds=RSS_FEEDS, monitored_tickers=set(TICKERS))
    label = LabelWorker()

    async with MarketauxClient(api_token=settings.marketaux_api_token or "") as mktaux_client:
        marketaux = MarketauxWorker(symbols=TICKERS, client=mktaux_client)

        tasks: list[asyncio.Task] = [
            asyncio.create_task(edgar.run(), name="edgar"),
            asyncio.create_task(rss.run(), name="rss"),
            asyncio.create_task(marketaux.run(), name="marketaux"),
            asyncio.create_task(label.run(), name="label"),
        ]

        if settings.tradier_api_token:
            from app.ingest_market.chain_snapshot_worker import ChainSnapshotWorker
            from app.providers.tradier.client import TradierClient

            tradier = TradierClient(
                api_token=settings.tradier_api_token,
                environment=settings.tradier_environment,
            )
            tasks.append(
                asyncio.create_task(
                    ChainSnapshotWorker(symbols=TICKERS, client=tradier).run(),
                    name="chain_snapshot",
                )
            )
            log.info("ChainSnapshotWorker: Tradier configured — starting")
        else:
            log.info("ChainSnapshotWorker: no TRADIER_API_TOKEN — skipped (Alpaca-only mode)")

        log.info(
            "Running %d workers: %s",
            len(tasks),
            ", ".join(t.get_name() for t in tasks),
        )

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Shutdown signal received")
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            log.info("All workers stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
