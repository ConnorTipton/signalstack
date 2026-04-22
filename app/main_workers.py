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

from app.alerts.telegram import TelegramClient
from app.alerts.worker import AlertWorker
from app.core.config import settings
from app.ingest_market.bar_aggregator import BarAggregatorWorker
from app.ingest_market.tradier_worker import TradierWorker
from app.ingest_news.edgar_worker import EdgarWorker
from app.ingest_news.label_worker import LabelWorker
from app.ingest_news.marketaux_worker import MarketauxWorker
from app.ingest_news.rss_worker import RssWorker
from app.providers.marketaux.client import MarketauxClient
from app.providers.official_feeds.rss import FeedConfig
from app.signals.news import NewsDetectorWorker
from app.signals.options import OptionsDetectorWorker
from app.signals.price import PriceDetectorWorker

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
    "IWM",
    "NFLX",
    "AVGO",
    "PLTR",
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


def _ensure_db_ready() -> None:
    """Check DB is migrated and seed symbols if the table is empty."""
    from sqlalchemy import inspect

    from app.db.models.symbols import Symbol
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        tables = inspect(db.get_bind()).get_table_names()
        if "news_articles" not in tables:
            raise RuntimeError(
                "Database tables are missing. Run: uv run alembic upgrade head"
            )
        log.info("Database schema verified")

        if db.query(Symbol).count() == 0:
            log.info("Symbols table empty — seeding")
            symbols_to_seed: list[tuple[str, str]] = [
                ("SPY", "SPDR S&P 500 ETF Trust"),
                ("QQQ", "Invesco QQQ Trust"),
                ("IWM", "iShares Russell 2000 ETF"),
                ("AAPL", "Apple Inc."),
                ("MSFT", "Microsoft Corporation"),
                ("NVDA", "NVIDIA Corporation"),
                ("AMZN", "Amazon.com Inc."),
                ("META", "Meta Platforms Inc."),
                ("TSLA", "Tesla Inc."),
                ("AMD", "Advanced Micro Devices Inc."),
                ("NFLX", "Netflix Inc."),
                ("GOOGL", "Alphabet Inc."),
                ("AVGO", "Broadcom Inc."),
                ("PLTR", "Palantir Technologies Inc."),
            ]
            db.add_all([Symbol(ticker=t, name=n) for t, n in symbols_to_seed])
            db.commit()
            log.info("Seeded %d symbols", len(symbols_to_seed))


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    log.info("Starting SignalStack workers (mode=%s)", settings.runtime_mode.value)
    await asyncio.to_thread(_ensure_db_ready)

    edgar = EdgarWorker(tickers=TICKERS)
    rss = RssWorker(feeds=RSS_FEEDS, monitored_tickers=set(TICKERS))
    label = LabelWorker()

    async with MarketauxClient(api_token=settings.marketaux_api_token or "") as mktaux_client:
        marketaux = MarketauxWorker(symbols=TICKERS, client=mktaux_client)

        alpaca_broker = None
        telegram = None
        if settings.telegram_bot_token and settings.telegram_chat_id:
            telegram = TelegramClient(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
        else:
            log.warning("Telegram not configured — alerts will be persisted but not sent")

        tasks: list[asyncio.Task] = [
            asyncio.create_task(edgar.run(), name="edgar"),
            asyncio.create_task(rss.run(), name="rss"),
            asyncio.create_task(marketaux.run(), name="marketaux"),
            asyncio.create_task(label.run(), name="label"),
            asyncio.create_task(TradierWorker(symbols=TICKERS).run(), name="tradier_quotes"),
            asyncio.create_task(BarAggregatorWorker().run(), name="bar_aggregator"),
            asyncio.create_task(NewsDetectorWorker().run(), name="news_detector"),
            asyncio.create_task(PriceDetectorWorker().run(), name="price_detector"),
            asyncio.create_task(OptionsDetectorWorker().run(), name="options_detector"),
            asyncio.create_task(
                AlertWorker(
                    telegram_client=telegram,
                    dry_run=settings.alerts_dry_run,
                ).run(),
                name="alert_worker",
            ),
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

        if settings.alpaca_api_key and settings.alpaca_secret_key:
            from app.execution.alpaca_broker import AlpacaBrokerClient
            from app.execution.order_router import OrderRouter
            from app.execution.position_manager import PositionManager
            from app.execution.worker import ExecutionWorker

            alpaca_broker = AlpacaBrokerClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
                paper=settings.alpaca_paper,
            )
            tasks.append(
                asyncio.create_task(
                    ExecutionWorker(
                        order_router=OrderRouter(broker_client=alpaca_broker, dry_run=False),
                        position_manager=PositionManager(broker_client=alpaca_broker),
                    ).run(),
                    name="execution",
                )
            )
            log.info("ExecutionWorker: Alpaca paper trading enabled (paper=%s)", settings.alpaca_paper)
        else:
            log.info("ExecutionWorker: no ALPACA credentials — skipped")

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
            if alpaca_broker is not None:
                alpaca_broker.close()
            log.info("All workers stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
