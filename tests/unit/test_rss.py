"""Unit tests for the generic RSS adapter and RssWorker control flow."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.providers.official_feeds.rss import FeedConfig, RssEntry, _parse_entries, extract_tickers

# ---------------------------------------------------------------------------
# Fixture feed entries
# ---------------------------------------------------------------------------

_IR_CONFIG = FeedConfig(
    url="https://ir.apple.com/rss/news-releases.rss",
    source_name="ir_apple",
    ticker="AAPL",
)

_WIRE_CONFIG = FeedConfig(
    url="https://www.globenewswire.com/RssFeed/subjectcode/AALL-1",
    source_name="globenewswire",
    ticker=None,
)

_MONITORED = {"AAPL", "MSFT", "NVDA", "TSLA"}

_ENTRY_WITH_ID = {
    "id": "https://ir.apple.com/news-releases/2025/01/press-release-1",
    "title": "Apple Announces Q1 2025 Results",
    "link": "https://ir.apple.com/news-releases/2025/01/press-release-1",
    "updated_parsed": (2025, 1, 30, 21, 0, 0, 3, 30, 0),
    "summary": "Apple today announced financial results for Q1 2025.",
}

_ENTRY_NO_ID = {
    "id": "",
    "title": "orphan entry",
}

_ENTRY_WITH_LINK_ONLY = {
    "id": None,
    "title": "MSFT Reports Record Revenue",
    "link": "https://globenewswire.com/releases/2025/02/01/msft-q2.html",
    "updated_parsed": (2025, 2, 1, 14, 0, 0, 5, 32, 0),
    "summary": "Microsoft Corporation announces Q2 results.",
}


# ---------------------------------------------------------------------------
# _parse_entries
# ---------------------------------------------------------------------------


def test_parse_entries_returns_one_entry_for_valid_input():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert len(results) == 1


def test_parse_entries_sets_source_name():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].source_name == "ir_apple"


def test_parse_entries_sets_provider_event_id():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].provider_event_id == _ENTRY_WITH_ID["id"]


def test_parse_entries_sets_title():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].title == "Apple Announces Q1 2025 Results"


def test_parse_entries_sets_url():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].url.startswith("https://")


def test_parse_entries_published_at_from_updated_parsed():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].published_at == datetime(2025, 1, 30, 21, 0, 0, tzinfo=UTC)


def test_parse_entries_published_at_is_utc():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].published_at.tzinfo == UTC


def test_parse_entries_content_hash_is_deterministic():
    a = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    b = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert a[0].content_hash == b[0].content_hash


def test_parse_entries_content_hash_is_64_chars():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert len(results[0].content_hash) == 64


def test_parse_entries_skips_entry_with_no_id_or_link():
    results = _parse_entries([_ENTRY_NO_ID], "ir_apple")
    assert results == []


def test_parse_entries_uses_link_when_no_id():
    results = _parse_entries([_ENTRY_WITH_LINK_ONLY], "globenewswire")
    assert len(results) == 1
    assert results[0].provider_event_id == _ENTRY_WITH_LINK_ONLY["link"]


def test_parse_entries_empty_feed():
    assert _parse_entries([], "ir_apple") == []


def test_parse_entries_no_published_parsed_leaves_none():
    entry = {"id": "some-id", "title": "title", "link": "https://example.com"}
    results = _parse_entries([entry], "ir_apple")
    assert results[0].published_at is None


def test_parse_entries_raw_includes_source_name():
    results = _parse_entries([_ENTRY_WITH_ID], "ir_apple")
    assert results[0].raw["source_name"] == "ir_apple"


# ---------------------------------------------------------------------------
# extract_tickers — IR feeds
# ---------------------------------------------------------------------------


def test_extract_tickers_ir_feed_returns_configured_ticker():
    entry = _parse_entries([_ENTRY_WITH_ID], "ir_apple")[0]
    result = extract_tickers(entry, _IR_CONFIG, _MONITORED)
    assert result == ["AAPL"]


def test_extract_tickers_ir_feed_ignores_monitored_set():
    # Even if "MSFT" appears in body, IR feed always returns its own ticker
    entry_data = dict(_ENTRY_WITH_ID, summary="MSFT and NVDA mentioned here")
    entry = _parse_entries([entry_data], "ir_apple")[0]
    result = extract_tickers(entry, _IR_CONFIG, _MONITORED)
    assert result == ["AAPL"]


# ---------------------------------------------------------------------------
# extract_tickers — wire feeds
# ---------------------------------------------------------------------------


def test_extract_tickers_wire_feed_matches_ticker_in_title():
    entry_data = dict(_ENTRY_WITH_LINK_ONLY, title="MSFT Reports Record Revenue")
    entry = _parse_entries([entry_data], "globenewswire")[0]
    result = extract_tickers(entry, _WIRE_CONFIG, _MONITORED)
    assert "MSFT" in result


def test_extract_tickers_wire_feed_matches_ticker_in_summary():
    entry_data = {"id": "x", "link": "https://gnw.com/x", "title": "Quarterly Results", "summary": "NVDA beats estimates"}
    entry = _parse_entries([entry_data], "globenewswire")[0]
    result = extract_tickers(entry, _WIRE_CONFIG, _MONITORED)
    assert "NVDA" in result


def test_extract_tickers_wire_feed_no_match_returns_empty():
    entry_data = {"id": "y", "link": "https://gnw.com/y", "title": "Weather update", "summary": "Rain expected."}
    entry = _parse_entries([entry_data], "globenewswire")[0]
    result = extract_tickers(entry, _WIRE_CONFIG, _MONITORED)
    assert result == []


def test_extract_tickers_wire_feed_multiple_matches_sorted():
    entry_data = {"id": "z", "link": "https://gnw.com/z", "title": "TSLA and MSFT announce partnership", "summary": ""}
    entry = _parse_entries([entry_data], "globenewswire")[0]
    result = extract_tickers(entry, _WIRE_CONFIG, _MONITORED)
    assert result == sorted(result)
    assert "TSLA" in result
    assert "MSFT" in result


def test_extract_tickers_wire_feed_avoids_partial_match():
    # "MA" should not match inside "MAXIMUM"
    ma_config = FeedConfig(url="https://gnw.com", source_name="gnw", ticker=None)
    entry_data = {"id": "w", "link": "https://gnw.com/w", "title": "Maximum gain expected", "summary": ""}
    entry = _parse_entries([entry_data], "gnw")[0]
    result = extract_tickers(entry, ma_config, {"MA"})
    assert result == []


# ---------------------------------------------------------------------------
# RssWorker — control flow
# ---------------------------------------------------------------------------


async def test_rss_worker_run_cancels_cleanly():
    from app.ingest_news.rss_worker import RssWorker

    poller = MagicMock()
    poller.poll = AsyncMock(return_value=[])

    worker = RssWorker(
        [_IR_CONFIG],
        monitored_tickers={"AAPL"},
        poller=poller,
        interval_seconds=0.01,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_rss_worker_feed_failure_does_not_abort_others():
    from app.ingest_news.rss_worker import RssWorker

    poller = MagicMock()
    poller.poll = AsyncMock(side_effect=RuntimeError("feed down"))

    attempts: list[str] = []
    feed_a = FeedConfig(url="https://a.com/feed", source_name="a", ticker="AAPL")
    feed_b = FeedConfig(url="https://b.com/feed", source_name="b", ticker="MSFT")
    worker = RssWorker([feed_a, feed_b], monitored_tickers=set(), poller=poller, interval_seconds=9999)

    original = worker._poll_feed

    async def spy(config: FeedConfig) -> None:
        attempts.append(config.source_name)
        await original(config)

    worker._poll_feed = spy

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "a" in attempts
    assert "b" in attempts


async def test_rss_worker_skips_entry_with_no_ticker_match():
    from app.ingest_news.rss_worker import RssWorker

    entry = RssEntry(
        provider_event_id="no-match",
        source_name="globenewswire",
        title="Unrelated news about nothing",
        url="https://gnw.com/x",
        published_at=None,
        summary=None,
        content_hash="a" * 64,
        raw={},
    )

    poller = MagicMock()
    poller.poll = AsyncMock(return_value=[entry])

    persisted: list = []

    worker = RssWorker(
        [_WIRE_CONFIG],
        monitored_tickers={"AAPL"},
        poller=poller,
        interval_seconds=9999,
    )
    worker._persist_entry = lambda e, t, r: persisted.append(e)  # type: ignore[method-assign]

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert persisted == []
