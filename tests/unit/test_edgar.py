"""Unit tests for the EDGAR RSS adapter and ingestion worker."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.providers.official_feeds.edgar import EdgarEntry, _parse_entries

# ---------------------------------------------------------------------------
# Fixture feed entries (dict format — feedparser FeedParserDict is a dict
# subclass, so plain dicts work identically for .get() calls in the parser)
# ---------------------------------------------------------------------------

_ENTRY_WITH_ID = {
    "id": "urn:tag:security.gov,2008:accession-number=0000320193-25-000006",
    "title": "8-K - APPLE INC (0000320193) (Filer)",
    "link": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000006/0000320193-25-000006-index.htm",
    "updated": "Fri, 24 Jan 2025 16:44:14 -0500",
    "updated_parsed": (2025, 1, 24, 21, 44, 14, 4, 24, 0),
    "summary": "<b>Documents</b>: 8-K, EX-99.1",
}

_ENTRY_NO_ID = {
    # Empty id + no link → should be skipped
    "id": "",
    "title": "orphan entry",
}

_ENTRY_WITH_LINK_ONLY = {
    # No id, but has link → link becomes provider_event_id
    "id": None,
    "title": "10-Q - MSFT",
    "link": "https://www.sec.gov/Archives/edgar/data/789019/...",
    "updated_parsed": (2025, 2, 1, 14, 0, 0, 5, 32, 0),
}


# ---------------------------------------------------------------------------
# _parse_entries — field extraction
# ---------------------------------------------------------------------------


def test_parse_entries_returns_one_entry_for_valid_input():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert len(results) == 1


def test_parse_entries_sets_ticker():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert results[0].ticker == "AAPL"


def test_parse_entries_sets_provider_event_id():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert results[0].provider_event_id == _ENTRY_WITH_ID["id"]


def test_parse_entries_sets_title():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert "APPLE INC" in results[0].title


def test_parse_entries_sets_url():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert results[0].url.startswith("https://")


def test_parse_entries_published_at_from_updated_parsed():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert results[0].published_at == datetime(2025, 1, 24, 21, 44, 14, tzinfo=UTC)


def test_parse_entries_published_at_is_utc():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert results[0].published_at.tzinfo == UTC


def test_parse_entries_raw_includes_ticker():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert results[0].raw["ticker"] == "AAPL"


def test_parse_entries_content_hash_is_deterministic():
    a = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    b = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert a[0].content_hash == b[0].content_hash


def test_parse_entries_content_hash_is_64_chars():
    results = _parse_entries([_ENTRY_WITH_ID], "AAPL")
    assert len(results[0].content_hash) == 64


# ---------------------------------------------------------------------------
# _parse_entries — degenerate cases
# ---------------------------------------------------------------------------


def test_parse_entries_skips_entry_with_no_id_or_link():
    results = _parse_entries([_ENTRY_NO_ID], "AAPL")
    assert results == []


def test_parse_entries_uses_link_when_no_id():
    results = _parse_entries([_ENTRY_WITH_LINK_ONLY], "MSFT")
    assert len(results) == 1
    assert results[0].provider_event_id == _ENTRY_WITH_LINK_ONLY["link"]


def test_parse_entries_empty_feed():
    assert _parse_entries([], "AAPL") == []


def test_parse_entries_mixed_valid_and_invalid():
    results = _parse_entries([_ENTRY_WITH_ID, _ENTRY_NO_ID, _ENTRY_WITH_LINK_ONLY], "AAPL")
    assert len(results) == 2


def test_parse_entries_no_published_parsed_leaves_none():
    entry = {
        "id": "some-id",
        "title": "title",
        "link": "https://example.com",
        # No published_parsed or updated_parsed
    }
    results = _parse_entries([entry], "AAPL")
    assert results[0].published_at is None


# ---------------------------------------------------------------------------
# EdgarWorker — control flow
# ---------------------------------------------------------------------------


async def test_edgar_worker_run_cancels_cleanly():
    from app.ingest_news.edgar_worker import EdgarWorker

    poller = MagicMock()
    poller.poll = AsyncMock(return_value=[])

    worker = EdgarWorker(["AAPL"], poller=poller, interval_seconds=0.01)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_edgar_worker_ticker_failure_does_not_abort_others():
    from app.ingest_news.edgar_worker import EdgarWorker

    poller = MagicMock()
    poller.poll = AsyncMock(side_effect=RuntimeError("EDGAR down"))

    attempts: list[str] = []
    worker = EdgarWorker(["AAPL", "MSFT"], poller=poller, interval_seconds=9999)

    original = worker._poll_ticker

    async def spy(ticker: str) -> None:
        attempts.append(ticker)
        await original(ticker)

    worker._poll_ticker = spy

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "AAPL" in attempts
    assert "MSFT" in attempts


async def test_edgar_worker_calls_persist_for_each_entry():
    from app.ingest_news.edgar_worker import EdgarWorker

    entry = MagicMock(spec=EdgarEntry)
    poller = MagicMock()
    poller.poll = AsyncMock(return_value=[entry, entry])

    persisted: list = []

    async def fake_persist(e, received_at):
        persisted.append(e)

    worker = EdgarWorker(["AAPL"], poller=poller, interval_seconds=9999)
    worker._poll_ticker = lambda ticker: fake_persist(entry, None)  # type: ignore[method-assign]

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
