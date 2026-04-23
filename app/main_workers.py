"""Worker orchestrator — starts all ingestion workers as concurrent asyncio tasks.

Usage:
    uv run python -m app.main_workers

Workers started:
    - EdgarWorker         (SEC EDGAR RSS, Tier 1 news)
    - RssWorker           (IR feeds + wire services, Tier 1 news)
    - MarketauxWorker     (Marketaux API, Tier 2 news; when configured)
    - LabelWorker         (LLM labeling of unlabeled articles; when configured)
    - Market data worker  (Tradier stream, or Alpaca bars fallback)
    - ChainSnapshotWorker (Tradier option chains — only when TRADIER_API_TOKEN is set)
    - News/price/options detectors, scorer, contract selector, alerts, metrics

Press Ctrl-C to stop all workers gracefully.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from app.alerts.telegram import TelegramClient
from app.alerts.worker import AlertWorker
from app.contracts.selector import ContractSelectorWorker
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.watchlist import DEFAULT_SYMBOL_NAMES, parse_rss_feeds, parse_tickers
from app.execution.metrics_worker import DailyMetricsWorker
from app.ingest_market.alpaca_bar_worker import AlpacaBarWorker
from app.ingest_market.alpaca_chain_snapshot_worker import AlpacaChainSnapshotWorker
from app.ingest_market.bar_aggregator import BarAggregatorWorker
from app.ingest_market.tradier_worker import TradierWorker
from app.ingest_news.edgar_worker import EdgarWorker
from app.ingest_news.label_worker import LabelWorker
from app.ingest_news.marketaux_worker import MarketauxWorker
from app.ingest_news.rss_worker import RssWorker
from app.providers.marketaux.client import MarketauxClient
from app.signals.news import NewsDetectorWorker
from app.signals.options import OptionsDetectorWorker
from app.signals.price import PriceDetectorWorker
from app.signals.scoring import ScoringWorker

log = logging.getLogger(__name__)


async def _supervised(factory: Callable[[], Any], name: str, max_backoff: float = 60.0) -> None:
    """Run factory() in a restart loop with exponential backoff on crash."""
    delay = min(1.0, max_backoff)
    while True:
        try:
            await factory()
            log.warning("Worker '%s' exited normally — restarting in %.1fs", name, delay)
        except asyncio.CancelledError:
            log.info("Worker '%s' cancelled", name)
            raise
        except Exception:
            log.exception("Worker '%s' crashed — restarting in %.1fs", name, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_backoff)


def _ensure_db_ready(tickers: list[str]) -> None:
    """Check DB is migrated and seed any missing monitored symbols."""
    from sqlalchemy import inspect

    from app.db.models.symbols import Symbol
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        tables = inspect(db.get_bind()).get_table_names()
        if "news_articles" not in tables:
            raise RuntimeError("Database tables are missing. Run: uv run alembic upgrade head")
        log.info("Database schema verified")

        existing = {
            row[0] for row in db.query(Symbol.ticker).filter(Symbol.ticker.in_(tickers)).all()
        }
        missing = [ticker for ticker in tickers if ticker not in existing]
        if missing:
            log.info("Seeding %d missing monitored symbol(s)", len(missing))
            db.add_all(
                [
                    Symbol(ticker=ticker, name=DEFAULT_SYMBOL_NAMES.get(ticker, ticker))
                    for ticker in missing
                ]
            )
            db.commit()
            log.info("Seeded missing symbols: %s", ", ".join(missing))


async def main() -> None:
    setup_logging(settings.log_level)
    log.info("Starting SignalStack workers (mode=%s)", settings.runtime_mode.value)
    tickers = parse_tickers(settings.monitored_tickers)
    rss_feeds = parse_rss_feeds(settings.rss_feeds)
    alpaca_configured = bool(settings.alpaca_api_key and settings.alpaca_secret_key)
    if alpaca_configured and not settings.alpaca_paper:
        raise RuntimeError("Live Alpaca trading is disabled in V1; set ALPACA_PAPER=true")
    await asyncio.to_thread(_ensure_db_ready, tickers)

    alpaca_broker = None
    alpaca_market = None
    marketaux_client = None
    tradier_rest = None
    tasks: list[asyncio.Task] = []

    def add_task(factory: Callable, name: str) -> None:
        tasks.append(asyncio.create_task(_supervised(factory, name), name=name))

    try:
        add_task(lambda: EdgarWorker(tickers=tickers).run(), "edgar")
        add_task(lambda: RssWorker(feeds=rss_feeds, monitored_tickers=set(tickers)).run(), "rss")

        if settings.marketaux_api_token:
            marketaux_client = MarketauxClient(api_token=settings.marketaux_api_token)
            add_task(
                lambda: MarketauxWorker(symbols=tickers, client=marketaux_client).run(),
                "marketaux",
            )
            log.info("MarketauxWorker: configured — starting")
        else:
            log.info("MarketauxWorker: no MARKETAUX_API_TOKEN — skipped")

        if settings.cloud_llm_api_key:
            add_task(lambda: LabelWorker().run(), "label")
            log.info("LabelWorker: Anthropic configured — starting")
        else:
            log.info("LabelWorker: no CLOUD_LLM_API_KEY — skipped")

        market_provider = "tradier"

        if settings.tradier_api_token:
            from app.ingest_market.chain_snapshot_worker import ChainSnapshotWorker
            from app.providers.tradier.client import TradierClient

            add_task(lambda: TradierWorker(symbols=tickers).run(), "tradier_quotes")
            add_task(lambda: BarAggregatorWorker().run(), "bar_aggregator")
            tradier_rest = TradierClient(
                api_token=settings.tradier_api_token,
                environment=settings.tradier_environment,
            )
            add_task(
                lambda: ChainSnapshotWorker(symbols=tickers, client=tradier_rest).run(),
                "chain_snapshot",
            )
            log.info("Tradier market data configured — starting stream + chain snapshots")
        elif alpaca_configured:
            from app.providers.alpaca.client import AlpacaMarketClient

            market_provider = "alpaca"
            alpaca_market = AlpacaMarketClient(
                api_key=settings.alpaca_api_key or "",
                secret_key=settings.alpaca_secret_key or "",
            )
            add_task(
                lambda: AlpacaBarWorker(symbols=tickers, client=alpaca_market).run(), "alpaca_bars"
            )
            add_task(
                lambda: AlpacaChainSnapshotWorker(symbols=tickers, client=alpaca_market).run(),
                "alpaca_chain_snapshot",
            )
            log.info("Alpaca market data configured — starting bars + chain snapshots")
        else:
            log.warning("No market data credentials configured — price/options signals unavailable")

        add_task(lambda: NewsDetectorWorker().run(), "news_detector")
        add_task(lambda: PriceDetectorWorker().run(), "price_detector")
        add_task(
            lambda: OptionsDetectorWorker(options_provider=market_provider).run(),
            "options_detector",
        )
        add_task(lambda: ScoringWorker(market_provider=market_provider).run(), "scoring")
        add_task(lambda: ContractSelectorWorker().run(), "contract_selector")

        telegram = None
        if settings.telegram_bot_token and settings.telegram_chat_id:
            telegram = TelegramClient(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
        else:
            log.warning("Telegram not configured — alerts will be persisted but not sent")

        add_task(
            lambda: AlertWorker(
                telegram_client=telegram,
                dry_run=settings.alerts_dry_run,
            ).run(),
            "alert_worker",
        )
        add_task(lambda: DailyMetricsWorker().run(), "daily_metrics")

        if alpaca_configured:
            from app.execution.alpaca_broker import AlpacaBrokerClient
            from app.execution.order_router import OrderRouter
            from app.execution.position_manager import PositionManager
            from app.execution.worker import ExecutionWorker

            alpaca_broker = AlpacaBrokerClient(
                api_key=settings.alpaca_api_key or "",
                secret_key=settings.alpaca_secret_key or "",
                paper=settings.alpaca_paper,
            )
            add_task(
                lambda: ExecutionWorker(
                    order_router=OrderRouter(broker_client=alpaca_broker, dry_run=False),
                    position_manager=PositionManager(broker_client=alpaca_broker),
                ).run(),
                "execution",
            )
            log.info(
                "ExecutionWorker: Alpaca paper trading enabled (paper=%s)", settings.alpaca_paper
            )
        else:
            log.info("ExecutionWorker: no ALPACA credentials — skipped")

        log.info(
            "Running %d workers: %s",
            len(tasks),
            ", ".join(t.get_name() for t in tasks),
        )
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("Shutdown signal received")
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if marketaux_client is not None:
            await marketaux_client.aclose()
        if tradier_rest is not None:
            await tradier_rest.aclose()
        if alpaca_market is not None:
            await alpaca_market.aclose()
        if alpaca_broker is not None:
            alpaca_broker.close()
        log.info("All workers stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
