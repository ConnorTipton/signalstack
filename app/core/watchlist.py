"""Runtime watchlist and RSS feed parsing helpers."""

from __future__ import annotations

from app.providers.official_feeds.rss import FeedConfig

DEFAULT_SYMBOL_NAMES: dict[str, str] = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "IWM": "iShares Russell 2000 ETF",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "AMD": "Advanced Micro Devices Inc.",
    "NFLX": "Netflix Inc.",
    "GOOGL": "Alphabet Inc.",
    "AVGO": "Broadcom Inc.",
    "PLTR": "Palantir Technologies Inc.",
}


def parse_tickers(raw: str) -> list[str]:
    """Parse comma-separated ticker symbols, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for token in raw.split(","):
        ticker = token.strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        result.append(ticker)
    if not result:
        raise ValueError("MONITORED_TICKERS must contain at least one ticker")
    return result


def parse_rss_feeds(raw: str) -> list[FeedConfig]:
    """Parse semicolon-separated ``source|url`` or ``source|url|ticker`` entries."""
    feeds: list[FeedConfig] = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
            raise ValueError(
                "RSS_FEEDS entries must be 'source_name|url' or 'source_name|url|ticker'"
            )
        feeds.append(
            FeedConfig(
                source_name=parts[0],
                url=parts[1],
                ticker=parts[2].upper() if len(parts) == 3 and parts[2] else None,
            )
        )
    if not feeds:
        raise ValueError("RSS_FEEDS must contain at least one feed")
    return feeds
