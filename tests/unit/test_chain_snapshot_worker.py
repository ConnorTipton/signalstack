"""Unit tests for the chain snapshot worker."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest_market.chain_snapshot_worker import ChainSnapshotWorker, pick_expirations

# ---------------------------------------------------------------------------
# pick_expirations
# ---------------------------------------------------------------------------

_TODAY = date(2024, 12, 6)

_DATES = [
    date(2024, 12, 1),  # past
    date(2024, 12, 6),  # today — included
    date(2024, 12, 13),
    date(2024, 12, 20),
    date(2025, 1, 17),
]


def test_pick_expirations_excludes_past(monkeypatch):
    monkeypatch.setattr("app.ingest_market.chain_snapshot_worker.date", _FakeDate)
    result = pick_expirations(_DATES, 3)
    assert date(2024, 12, 1) not in result
    assert len(result) == 3


def test_pick_expirations_returns_nearest_first(monkeypatch):
    monkeypatch.setattr("app.ingest_market.chain_snapshot_worker.date", _FakeDate)
    result = pick_expirations(_DATES, 2)
    assert result == [date(2024, 12, 6), date(2024, 12, 13)]


def test_pick_expirations_fewer_than_max(monkeypatch):
    monkeypatch.setattr("app.ingest_market.chain_snapshot_worker.date", _FakeDate)
    result = pick_expirations([date(2024, 12, 13)], 2)
    assert result == [date(2024, 12, 13)]


def test_pick_expirations_empty_list(monkeypatch):
    monkeypatch.setattr("app.ingest_market.chain_snapshot_worker.date", _FakeDate)
    assert pick_expirations([], 2) == []


def test_pick_expirations_all_past(monkeypatch):
    monkeypatch.setattr("app.ingest_market.chain_snapshot_worker.date", _FakeDate)
    result = pick_expirations([date(2024, 11, 1), date(2024, 12, 5)], 2)
    assert result == []


class _FakeDate(date):
    """Subclass of date that fixes today() for deterministic tests."""

    @classmethod
    def today(cls) -> date:
        return _TODAY


# ---------------------------------------------------------------------------
# ChainSnapshotWorker.run — stops on CancelledError
# ---------------------------------------------------------------------------

_EXPIRY = date(2024, 12, 13)
_CONTRACTS = [
    MagicMock(
        contract_symbol="AAPL241213C00190000",
        underlying="AAPL",
        expiration_date=_EXPIRY,
        strike=190.0,
        option_type="call",
        bid=2.50,
        ask=2.60,
        bid_size=10,
        ask_size=15,
        last=2.55,
        open_interest=5000,
        volume=500,
        implied_volatility=0.25,
        delta=0.45,
    ),
]


def _make_client(expirations=None, raw=None, contracts=None):
    client = MagicMock()
    client.get_option_expirations = AsyncMock(return_value=expirations or [_EXPIRY])
    client.fetch_option_chain_raw = AsyncMock(return_value=raw or {"options": {}})
    return client


async def test_worker_run_cancels_cleanly():
    client = _make_client(expirations=[])
    worker = ChainSnapshotWorker(
        ["AAPL"],
        client,
        interval_seconds=0.01,
        max_expirations=2,
    )
    worker._load_symbol_ids = lambda: {"AAPL": 1}
    worker._persist_chain = lambda *args, **kwargs: None

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_worker_skips_unknown_symbol():
    client = _make_client()
    worker = ChainSnapshotWorker(["AAPL", "MSFT"], client, interval_seconds=9999)
    worker._load_symbol_ids = lambda: {"AAPL": 1}  # MSFT not in DB

    calls: list[str] = []
    original = worker._snapshot_symbol

    async def spy(symbol, symbol_ids):
        calls.append(symbol)
        await original(symbol, symbol_ids)

    worker._snapshot_symbol = spy
    worker._persist_chain = lambda *args, **kwargs: None

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Both symbols attempted; MSFT skipped silently (no persist call for it)
    assert "AAPL" in calls
    assert "MSFT" in calls


async def test_worker_error_per_symbol_does_not_abort_others():
    """A failure on one symbol should not prevent the next from being attempted."""
    client = MagicMock()
    client.get_option_expirations = AsyncMock(side_effect=RuntimeError("Tradier down"))

    snapshot_attempts: list[str] = []

    async def fake_snapshot(symbol, symbol_ids):
        snapshot_attempts.append(symbol)
        exps = await client.get_option_expirations(symbol)  # will raise
        _ = exps

    worker = ChainSnapshotWorker(["AAPL", "MSFT"], client, interval_seconds=9999)
    worker._load_symbol_ids = lambda: {"AAPL": 1, "MSFT": 2}
    worker._snapshot_symbol = fake_snapshot

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "AAPL" in snapshot_attempts
    assert "MSFT" in snapshot_attempts
