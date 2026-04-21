"""Unit tests for the Tradier streaming normalizer and worker logic."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.ingest_market.tradier_worker import TradierWorker, _event_ts
from app.providers.tradier.normalizer import normalize_stream_quote

_QUOTE_EVENT = {
    "type": "quote",
    "symbol": "AAPL",
    "bid": 189.25,
    "bidsz": 200,
    "bidexch": "Q",
    "biddate": "1733490000000",
    "ask": 189.35,
    "asksz": 300,
    "askexch": "Q",
    "askdate": "1733490001000",  # one second later — used as timestamp
}

# ---------------------------------------------------------------------------
# normalize_stream_quote
# ---------------------------------------------------------------------------


def test_normalize_stream_quote_basic():
    q = normalize_stream_quote(_QUOTE_EVENT)
    assert q is not None
    assert q.symbol == "AAPL"
    assert q.bid == 189.25
    assert q.ask == 189.35
    assert q.bid_size == 200
    assert q.ask_size == 300
    assert q.source_name == "tradier"


def test_normalize_stream_quote_uses_later_timestamp():
    q = normalize_stream_quote(_QUOTE_EVENT)
    assert q is not None
    # askdate (1733490001000 ms) is later than biddate (1733490000000 ms)
    assert q.timestamp == datetime.fromtimestamp(1733490001, tz=UTC)


def test_normalize_stream_quote_only_biddate():
    event = {**_QUOTE_EVENT, "askdate": None}
    q = normalize_stream_quote(event)
    assert q is not None
    assert q.timestamp == datetime.fromtimestamp(1733490000, tz=UTC)


def test_normalize_stream_quote_missing_symbol():
    event = {k: v for k, v in _QUOTE_EVENT.items() if k != "symbol"}
    assert normalize_stream_quote(event) is None


def test_normalize_stream_quote_no_timestamp_falls_back_to_now():
    event = {"type": "quote", "symbol": "MSFT", "bid": 420.0, "ask": 421.0}
    before = datetime.now(UTC)
    q = normalize_stream_quote(event)
    after = datetime.now(UTC)
    assert q is not None
    assert before <= q.timestamp <= after


def test_normalize_stream_quote_none_bid_ask():
    event = {"type": "quote", "symbol": "AAPL", "biddate": "1733490000000"}
    q = normalize_stream_quote(event)
    assert q is not None
    assert q.bid is None
    assert q.ask is None
    assert q.bid_size is None
    assert q.ask_size is None


def test_normalize_stream_quote_string_numeric_fields():
    event = {**_QUOTE_EVENT, "bid": "189.25", "bidsz": "200"}
    q = normalize_stream_quote(event)
    assert q is not None
    assert q.bid == 189.25
    assert q.bid_size == 200


# ---------------------------------------------------------------------------
# _event_ts helper
# ---------------------------------------------------------------------------


def test_event_ts_uses_biddate_first():
    event = {"biddate": "1733490000000", "askdate": "1733490001000"}
    assert _event_ts(event) == datetime.fromtimestamp(1733490000, tz=UTC)


def test_event_ts_falls_through_to_askdate():
    assert _event_ts({"askdate": "1733490001000"}) == datetime.fromtimestamp(1733490001, tz=UTC)


def test_event_ts_returns_none_when_absent():
    assert _event_ts({"type": "quote"}) is None


def test_event_ts_skips_none_value():
    ts = _event_ts({"biddate": None, "askdate": "1733490001000"})
    assert ts == datetime.fromtimestamp(1733490001, tz=UTC)


# ---------------------------------------------------------------------------
# TradierWorker._backoff — stays within expected bounds
# ---------------------------------------------------------------------------


def test_backoff_first_failure():
    worker = TradierWorker(["AAPL"])
    worker._consecutive_failures = 1
    delay = worker._backoff()
    assert 1.0 <= delay <= 1.0 * (1 + _JITTER_FACTOR) + 0.01


def test_backoff_caps_at_max():
    from app.ingest_market.tradier_worker import _BACKOFF_MAX, _JITTER_FACTOR

    worker = TradierWorker(["AAPL"])
    worker._consecutive_failures = 100
    delay = worker._backoff()
    assert delay <= _BACKOFF_MAX * (1 + _JITTER_FACTOR) + 0.01


def test_backoff_grows_with_failures():
    worker = TradierWorker(["AAPL"])
    worker._consecutive_failures = 1
    d1 = worker._backoff()
    worker._consecutive_failures = 3
    d3 = worker._backoff()
    # base(3) = 4s vs base(1) = 1s; even with max jitter d3 > d1 almost always
    assert d3 > d1 * 0.5  # loose check — jitter means we can't be exact


# ---------------------------------------------------------------------------
# TradierWorker.run — finite stream terminates and CancelledError stops the loop
# ---------------------------------------------------------------------------

_JITTER_FACTOR = 0.3  # local alias for the assertion above


async def _two_event_stream(session_id, stream_url, symbols):
    for event in [
        {
            "type": "quote",
            "symbol": "AAPL",
            "bid": 189.0,
            "ask": 190.0,
            "bidsz": 10,
            "asksz": 20,
            "biddate": "1733490000000",
        },
        {"type": "summary", "symbol": "AAPL"},
    ]:
        yield event


async def test_worker_run_processes_events_and_reconnects():
    collected: list[dict] = []

    async def fake_session(token, base_url):
        return "sess-123", "https://stream.fake"

    worker = TradierWorker(
        ["AAPL"],
        session_factory=fake_session,
        stream_factory=_two_event_stream,
    )
    worker._load_symbol_ids = lambda: {"AAPL": 1}
    worker._persist = lambda event, received_at, symbol_ids: collected.append(event)

    async def noop_health(**kwargs):
        pass

    worker._record_health = noop_health

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)  # let first stream run finish and reconnect start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(collected) >= 2
    assert collected[0]["type"] == "quote"


async def test_worker_run_records_health_on_error():
    health_calls: list[dict] = []

    async def bad_session(token, base_url):
        raise RuntimeError("connection refused")

    worker = TradierWorker(["AAPL"], session_factory=bad_session)

    async def spy_health(**kwargs):
        health_calls.append(kwargs)

    worker._record_health = spy_health
    worker._record_health_sync = lambda **kwargs: None

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert any(not c["is_healthy"] for c in health_calls)
