"""Unit tests for the Marketaux client and MarketauxWorker control flow."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.providers.marketaux.client import MarketauxArticle, MarketauxClient, _normalize

# ---------------------------------------------------------------------------
# Sample API response payloads
# ---------------------------------------------------------------------------

_ARTICLE_RAW = {
    "uuid": "abc-123-def-456",
    "title": "Apple Reports Record Q1 Revenue",
    "description": "Apple Inc. today announced record Q1 2025 revenue of $120 billion.",
    "snippet": "Apple Q1 snippet",
    "url": "https://reuters.com/tech/apple-q1-2025",
    "image_url": None,
    "language": "en",
    "published_at": "2025-01-30T21:00:00.000000Z",
    "source": "Reuters",
    "relevance_score": None,
    "entities": [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "type": "equity",
            "match_score": 20.0,
            "sentiment_score": 0.12,
        },
        {
            "symbol": "AAPL",  # duplicate — should deduplicate in tickers list
            "name": "Apple Inc.",
            "type": "equity",
        },
    ],
}

_ARTICLE_NO_EQUITY = {
    "uuid": "no-equity-999",
    "title": "Fed Rate Decision",
    "description": "Federal Reserve holds rates steady.",
    "url": "https://wsj.com/fed-rate-2025",
    "published_at": "2025-01-30T18:00:00Z",
    "source": "WSJ",
    "entities": [
        {"symbol": "USD", "type": "currency"},
    ],
}

_API_RESPONSE = {
    "meta": {"found": 2, "returned": 2, "limit": 50, "page": 1},
    "data": [_ARTICLE_RAW],
}


# ---------------------------------------------------------------------------
# Fake HTTP transport
# ---------------------------------------------------------------------------


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self._routes:
            return self._routes[path]
        raise AssertionError(f"No mock for {request.url}")


def _client(routes: dict[str, httpx.Response]) -> MarketauxClient:
    transport = _FakeTransport(routes)
    http = httpx.AsyncClient(base_url="https://api.marketaux.com", transport=transport)
    return MarketauxClient(api_token="test-token", http_client=http)


def _json_resp(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# ---------------------------------------------------------------------------
# _normalize — field extraction
# ---------------------------------------------------------------------------


def test_normalize_sets_uuid():
    result = _normalize(_ARTICLE_RAW)
    assert result.uuid == "abc-123-def-456"


def test_normalize_sets_title():
    result = _normalize(_ARTICLE_RAW)
    assert result.title == "Apple Reports Record Q1 Revenue"


def test_normalize_sets_url():
    result = _normalize(_ARTICLE_RAW)
    assert result.url == "https://reuters.com/tech/apple-q1-2025"


def test_normalize_sets_published_at_utc():
    result = _normalize(_ARTICLE_RAW)
    assert result.published_at == datetime(2025, 1, 30, 21, 0, 0, tzinfo=UTC)
    assert result.published_at.tzinfo == UTC


def test_normalize_sets_source():
    result = _normalize(_ARTICLE_RAW)
    assert result.source == "Reuters"


def test_normalize_prefers_description_over_snippet():
    result = _normalize(_ARTICLE_RAW)
    assert "record Q1 2025 revenue" in result.summary


def test_normalize_falls_back_to_snippet_when_no_description():
    item = dict(_ARTICLE_RAW, description=None)
    result = _normalize(item)
    assert result.summary == "Apple Q1 snippet"


def test_normalize_summary_none_when_no_description_or_snippet():
    item = dict(_ARTICLE_RAW, description=None, snippet=None)
    result = _normalize(item)
    assert result.summary is None


def test_normalize_deduplicates_tickers():
    result = _normalize(_ARTICLE_RAW)
    assert result.tickers.count("AAPL") == 1


def test_normalize_tickers_sorted():
    item = dict(
        _ARTICLE_RAW,
        entities=[
            {"symbol": "MSFT", "type": "equity"},
            {"symbol": "AAPL", "type": "equity"},
        ],
    )
    result = _normalize(item)
    assert result.tickers == ["AAPL", "MSFT"]


def test_normalize_skips_non_equity_entities():
    result = _normalize(_ARTICLE_NO_EQUITY)
    assert result.tickers == []


def test_normalize_content_hash_is_64_chars():
    result = _normalize(_ARTICLE_RAW)
    assert len(result.content_hash) == 64


def test_normalize_content_hash_uses_normalized_title():
    upper = dict(_ARTICLE_RAW, title="APPLE REPORTS RECORD Q1 REVENUE")
    lower = dict(_ARTICLE_RAW, title="apple reports record q1 revenue")
    assert _normalize(upper).content_hash == _normalize(lower).content_hash


def test_normalize_content_hash_is_deterministic():
    a = _normalize(_ARTICLE_RAW)
    b = _normalize(_ARTICLE_RAW)
    assert a.content_hash == b.content_hash


def test_normalize_raw_is_original_dict():
    result = _normalize(_ARTICLE_RAW)
    assert result.raw is _ARTICLE_RAW


# ---------------------------------------------------------------------------
# MarketauxClient.fetch_articles
# ---------------------------------------------------------------------------


async def test_fetch_articles_returns_articles():
    c = _client({"/v1/news/all": _json_resp(_API_RESPONSE)})
    result = await c.fetch_articles(["AAPL"])
    assert len(result) == 1
    assert isinstance(result[0], MarketauxArticle)


async def test_fetch_articles_empty_symbols_returns_empty():
    # Should not make a network call at all
    c = _client({})
    result = await c.fetch_articles([])
    assert result == []


async def test_fetch_articles_non_200_returns_empty():
    c = _client({"/v1/news/all": httpx.Response(403, text="Unauthorized")})
    result = await c.fetch_articles(["AAPL"])
    assert result == []


async def test_fetch_articles_empty_data_returns_empty():
    c = _client({"/v1/news/all": _json_resp({"meta": {}, "data": []})})
    result = await c.fetch_articles(["AAPL"])
    assert result == []


# ---------------------------------------------------------------------------
# MarketauxWorker — control flow
# ---------------------------------------------------------------------------


async def test_marketaux_worker_run_cancels_cleanly():
    from app.ingest_news.marketaux_worker import MarketauxWorker

    client = MagicMock()
    client.fetch_articles = AsyncMock(return_value=[])

    worker = MarketauxWorker(["AAPL"], client, interval_seconds=0.01)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_marketaux_worker_poll_error_does_not_propagate():
    from app.ingest_news.marketaux_worker import MarketauxWorker

    client = MagicMock()
    client.fetch_articles = AsyncMock(side_effect=RuntimeError("Marketaux down"))

    worker = MarketauxWorker(["AAPL"], client, interval_seconds=0.01)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # No unhandled exception — test passes if task only raises CancelledError
