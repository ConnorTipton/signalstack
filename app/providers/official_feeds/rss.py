"""Generic RSS/Atom feed adapter for issuer IR feeds and financial wire services.

Handles any feed URL with ETag + If-Modified-Since caching. Ticker assignment:

  - IR feeds (FeedConfig.ticker set): all entries are attributed to that ticker.
  - Wire feeds (FeedConfig.ticker is None): entries are matched against a set of
    monitored tickers via word-boundary search in title + summary.

All feeds are Tier 1 (official issuer or major newswire). Source differentiation
is carried by FeedConfig.source_name (e.g. "ir_apple", "globenewswire").
"""

from __future__ import annotations

import hashlib
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

import feedparser
import httpx

log = logging.getLogger(__name__)

_USER_AGENT = "SignalStack/1.0 connor.brent.tipton@gmail.com"
_NORMALIZATION_VERSION = "1"


@dataclass
class FeedConfig:
    """Configuration for a single RSS/Atom feed endpoint.

    Parameters
    ----------
    url:
        Full feed URL.
    source_name:
        Short label stored in source_name columns (e.g. "ir_apple", "globenewswire").
    ticker:
        For issuer IR feeds: the ticker this feed exclusively covers.
        For wire feeds: leave None; tickers are extracted from entry content.
    """

    url: str
    source_name: str
    ticker: str | None = None


@dataclass
class RssEntry:
    """Normalized representation of one RSS/Atom entry."""

    provider_event_id: str
    source_name: str
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


class RssPoller:
    """Fetches any RSS/Atom feed URL with conditional-GET caching.

    Parameters
    ----------
    http_client:
        Injected httpx.AsyncClient for testing. When None, a default client
        is created and owned by this instance.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
        self._cache: dict[str, _FeedState] = {}

    async def poll(self, config: FeedConfig) -> list[RssEntry]:
        """Return new entries from the feed since the last successful poll.

        Returns an empty list when the feed is unchanged (HTTP 304) or on error.
        """
        state = self._cache.get(config.url, _FeedState())

        headers: dict[str, str] = {}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        resp = await self._http.get(config.url, headers=headers)

        if resp.status_code == 304:
            log.debug("Feed %s unchanged (304)", config.url)
            return []
        if resp.status_code != 200:
            log.warning("RSS poll for %s returned HTTP %d", config.url, resp.status_code)
            return []

        self._cache[config.url] = _FeedState(
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        feed = feedparser.parse(resp.text)
        return _parse_entries(feed.entries, config.source_name)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> RssPoller:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def _parse_entries(entries: list, source_name: str) -> list[RssEntry]:
    """Convert feedparser entry dicts to RssEntry objects.

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
            RssEntry(
                provider_event_id=provider_event_id,
                source_name=source_name,
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
                    "source_name": source_name,
                },
            )
        )
    return result


def extract_tickers(entry: RssEntry, config: FeedConfig, monitored: set[str]) -> list[str]:
    """Return the list of monitored tickers associated with this entry.

    For IR feeds (config.ticker set): always returns [config.ticker].
    For wire feeds (config.ticker is None): scans title + summary for whole-word
    ticker matches against the monitored set. Returns sorted matches.
    """
    if config.ticker is not None:
        return [config.ticker]

    text = f"{entry.title} {entry.summary or ''}"
    return sorted(t for t in monitored if re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE))
