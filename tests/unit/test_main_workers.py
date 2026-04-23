"""Unit tests for worker startup helpers."""

import asyncio

import pytest

from app.db.models.symbols import Symbol
from app.main_workers import _ensure_db_ready, _supervised


class _Inspector:
    def get_table_names(self):
        return ["news_articles"]


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_):
        return self

    def all(self):
        return [(row,) for row in self._rows]


class _Session:
    def __init__(self, existing):
        self._existing = existing
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_bind(self):
        return object()

    def query(self, *_):
        return _Query(self._existing)

    def add_all(self, rows):
        self.added.extend(rows)

    def commit(self):
        self.committed = True


# ---------------------------------------------------------------------------
# _supervised — crash-restart loop
# ---------------------------------------------------------------------------


async def test_supervised_restarts_after_crash():
    call_count = 0

    async def _flaky():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    task = asyncio.create_task(_supervised(_flaky, "test", max_backoff=0.01))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert call_count >= 3


async def test_supervised_cancel_propagates():
    async def _forever():
        await asyncio.sleep(1000)

    task = asyncio.create_task(_supervised(_forever, "test"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# _ensure_db_ready
# ---------------------------------------------------------------------------


def test_ensure_db_ready_seeds_only_missing_symbols(monkeypatch):
    session = _Session(existing=["AAPL"])
    monkeypatch.setattr("sqlalchemy.inspect", lambda _: _Inspector())
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: session)

    _ensure_db_ready(["AAPL", "MSFT"])

    assert [row.ticker for row in session.added] == ["MSFT"]
    assert all(isinstance(row, Symbol) for row in session.added)
    assert session.committed is True
