"""Marketaux news API adapter (Tier 2).

Fetches recent financial news articles for a set of monitored ticker symbols.
Returns normalized MarketauxArticle objects along with the raw API payload.

Rate limiting is handled by the caller (MarketauxWorker) via its poll interval.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

log = logging.getLogger(__name__)

_BASE_URL = "https://api.marketaux.com"
_ARTICLES_PATH = "/v1/news/all"
_SOURCE_NAME = "marketaux"
_DEFAULT_LIMIT = 50


@dataclass
class MarketauxArticle:
    """Normalized representation of one Marketaux article."""

    uuid: str
    title: str
    url: str
    published_at: datetime
    source: str          # originating publication (e.g. "Reuters")
    summary: str | None
    tickers: list[str]   # equity symbols from entities, sorted
    content_hash: str    # sha256 of normalized title — used for same-title dedup
    raw: dict = field(repr=False)


class MarketauxClient:
    """HTTP client for the Marketaux v1/news/all endpoint.

    Parameters
    ----------
    api_token:
        Marketaux API token (MARKETAUX_API_TOKEN in settings).
    http_client:
        Injected httpx.AsyncClient for testing. When None, a default client
        pointing at the Marketaux API is created and owned by this instance.
    base_url:
        Override the API base URL (used in tests).
    """

    def __init__(
        self,
        api_token: str,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _BASE_URL,
    ) -> None:
        self._api_token = api_token
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
        )

    async def fetch_articles(
        self,
        symbols: list[str],
        *,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[MarketauxArticle]:
        """Fetch the most recent articles for the given ticker symbols.

        Returns an empty list for an empty symbol list or on API error.
        """
        if not symbols:
            return []

        resp = await self._http.get(
            _ARTICLES_PATH,
            params={
                "api_token": self._api_token,
                "symbols": ",".join(symbols),
                "filter_entities": "true",
                "language": "en",
                "limit": str(limit),
            },
        )

        if resp.status_code != 200:
            log.warning("Marketaux returned HTTP %d: %s", resp.status_code, resp.text[:200])
            return []

        data = resp.json()
        return [_normalize(item) for item in data.get("data", [])]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> MarketauxClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def _normalize(item: dict) -> MarketauxArticle:
    """Convert one raw Marketaux API item to a MarketauxArticle."""
    published_at = datetime.fromisoformat(
        item.get("published_at", "1970-01-01T00:00:00Z").replace("Z", "+00:00")
    ).astimezone(UTC)

    tickers = sorted(
        {
            e["symbol"]
            for e in item.get("entities", [])
            if e.get("type") == "equity" and e.get("symbol")
        }
    )

    title = item.get("title") or ""
    # summary: prefer description, fall back to snippet
    summary = item.get("description") or item.get("snippet") or None
    content_hash = hashlib.sha256(title.lower().strip().encode()).hexdigest()

    return MarketauxArticle(
        uuid=item.get("uuid", ""),
        title=title,
        url=item.get("url") or "",
        published_at=published_at,
        source=item.get("source") or "",
        summary=summary,
        tickers=tickers,
        content_hash=content_hash,
        raw=item,
    )
