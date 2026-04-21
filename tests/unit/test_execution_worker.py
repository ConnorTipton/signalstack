"""Unit tests for ExecutionWorker (Phase 8)."""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.db.models.execution import Alert, PaperOrder
from app.execution.order_router import OrderRouter
from app.execution.position_manager import PositionManager
from app.execution.worker import ExecutionWorker


def _alert(
    id: int = 1,
    ticker: str = "AAPL",
    symbol_id: int = 2,
    contract_symbol: str = "AAPL250501C00190000",
    option_type: str = "call",
    strike: float = 190.0,
    expiration_date: date = date(2025, 5, 1),
) -> MagicMock:
    a = MagicMock(spec=Alert)
    a.id = id
    a.ticker = ticker
    a.symbol_id = symbol_id
    a.contract_symbol = contract_symbol
    a.option_type = option_type
    a.strike = strike
    a.expiration_date = expiration_date
    a.sent_at = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
    return a


def _db_mock() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


def _worker(
    alerts: list | None = None,
    router: OrderRouter | None = None,
    pm: PositionManager | None = None,
) -> ExecutionWorker:
    w = ExecutionWorker(
        order_router=router or OrderRouter(dry_run=True),
        position_manager=pm or MagicMock(spec=PositionManager),
    )
    w._fetch_unrouted_alerts = lambda db: alerts or []
    return w


# ---------------------------------------------------------------------------
# run_once — basic control flow
# ---------------------------------------------------------------------------


def test_run_once_returns_zero_with_no_alerts():
    assert _worker().run_once(_db_mock()) == 0


def test_run_once_returns_count_of_routed_orders():
    router = MagicMock(spec=OrderRouter)
    router.route.return_value = MagicMock(spec=PaperOrder)
    w = _worker(alerts=[_alert(id=1), _alert(id=2, ticker="MSFT")], router=router)
    assert w.run_once(_db_mock()) == 2


def test_run_once_does_not_count_skipped_routes():
    router = MagicMock(spec=OrderRouter)
    router.route.return_value = None  # router skips all
    w = _worker(alerts=[_alert()], router=router)
    assert w.run_once(_db_mock()) == 0


def test_run_once_calls_position_manager_process():
    pm = MagicMock(spec=PositionManager)
    w = _worker(pm=pm)
    w.run_once(_db_mock())
    pm.process.assert_called_once()


def test_run_once_commits_once():
    db = _db_mock()
    _worker().run_once(db)
    db.commit.assert_called_once()


def test_run_once_routes_each_alert():
    router = MagicMock(spec=OrderRouter)
    router.route.return_value = MagicMock(spec=PaperOrder)
    alerts = [_alert(id=1), _alert(id=2, ticker="MSFT"), _alert(id=3, ticker="NVDA")]
    w = _worker(alerts=alerts, router=router)
    w.run_once(_db_mock())
    assert router.route.call_count == 3


# ---------------------------------------------------------------------------
# Async cancel
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    worker = ExecutionWorker(interval_seconds=0.01)
    worker._fetch_unrouted_alerts = lambda db: []

    import app.execution.worker as worker_mod

    original = worker_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return _db_mock()

        def __exit__(self, *_):
            pass

    worker_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        worker_mod.SessionLocal = original
