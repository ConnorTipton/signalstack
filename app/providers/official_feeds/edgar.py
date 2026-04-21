"""SEC EDGAR company filings RSS adapter.

Polls the EDGAR Atom feed per ticker. Uses ETag + If-Modified-Since headers
to avoid re-fetching unchanged feeds. Returns normalized EdgarEntry objects;
the raw dict is preserved so the caller can write it to raw_official_news_events.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

import feedparser
import httpx

log = logging.getLogger(__name__)

_EDGAR_BASE = "https://www.sec.gov"
_FILINGS_PATH = "/cgi-bin/browse-edgar"
# SEC requires User-Agent with contact info: https://www.sec.gov/os/accessing-edgar-data
_USER_AGENT = "SignalStack/1.0 connor.brent.tipton@gmail.com"
_SOURCE_NAME = "edgar"
_NORMALIZATION_VERSION = "1"


@dataclass
class EdgarEntry:
    """Normalized representation of one EDGAR filing Atom entry."""

    provider_event_id: str
    ticker: str
    title: str
    url: str
    published_at: datetime | None
    summary: str | None
    content_hash: str
    raw: dict = field(repr=False)


@dataclass
class _FeedState:
    etag: str | None = None
    last_modified: str | None = None


class EdgarPoller:
    """Fetches EDGAR filings Atom feed for each ticker with conditional-GET caching.

    Parameters
    ----------
    http_client:
        Injected httpx.AsyncClient for testing. When None, a default client
        pointing at SEC is created and owned by this instance.
    base_url:
        Override the SEC base URL (used in tests).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _EDGAR_BASE,
    ) -> None:
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
        self._cache: dict[str, _FeedState] = {}

    async def poll(self, ticker: str) -> list[EdgarEntry]:
        """Return new entries for ticker since the last successful poll.

        Returns an empty list when the feed is unchanged (HTTP 304).
        """
        state = self._cache.get(ticker, _FeedState())

        headers: dict[str, str] = {}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        resp = await self._http.get(
            _FILINGS_PATH,
            params={
                "action": "getcompany",
                "CIK": ticker,
                "type": "",
                "dateb": "",
                "owner": "include",
                "count": "40",
                "output": "atom",
            },
            headers=headers,
        )

        if resp.status_code == 304:
            log.debug("EDGAR feed for %s unchanged (304)", ticker)
            return []
        if resp.status_code != 200:
            log.warning("EDGAR poll for %s returned HTTP %d", ticker, resp.status_code)
            return []

        self._cache[ticker] = _FeedState(
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        feed = feedparser.parse(resp.text)
        return _parse_entries(feed.entries, ticker)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> EdgarPoller:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def _parse_entries(entries: list, ticker: str) -> list[EdgarEntry]:
    """Convert feedparser entry dicts to EdgarEntry objects.

    Skips any entry that has neither an id nor a link (no stable identifier).
    """
    result = []
    for e in entries:
        provider_event_id = e.get("id") or e.get("link")
        if not provider_event_id:
            continue

        title = e.get("title") or ""
        url = e.get("link") or ""
        summary = e.get("summary") or None

        published_at: datetime | None = None
        parsed = e.get("published_parsed") or e.get("updated_parsed")
        if parsed:
            with suppress(TypeError, ValueError):
                published_at = datetime(*parsed[:6], tzinfo=UTC)

        content_hash = hashlib.sha256(f"{title}\n{url}".encode()).hexdigest()

        result.append(
            EdgarEntry(
                provider_event_id=provider_event_id,
                ticker=ticker,
                title=title,
                url=url,
                published_at=published_at,
                summary=summary,
                content_hash=content_hash,
                raw={
                    "id": provider_event_id,
                    "title": title,
                    "link": url,
                    "summary": summary,
                    "published": e.get("published") or e.get("updated"),
                    "ticker": ticker,
                },
            )
        )
    return result
