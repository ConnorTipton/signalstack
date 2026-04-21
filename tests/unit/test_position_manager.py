"""Unit tests for PositionManager (Phase 8)."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.db.models.execution import PaperOrder, PaperPosition, PositionEvent
from app.execution.position_manager import PositionManager

_NOW = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)


def _order(
    id: int = 1,
    ticker: str = "AAPL",
    alert_id: int = 10,
    symbol_id: int = 2,
    contract_symbol: str = "AAPL250501C00190000",
    option_type: str = "call",
    strike: float = 190.0,
    expiration_date: date = date(2025, 5, 1),
    quantity: int = 1,
    status: str = "dry_run",
    alpaca_order_id: str | None = None,
) -> MagicMock:
    o = MagicMock(spec=PaperOrder)
    o.id = id
    o.ticker = ticker
    o.alert_id = alert_id
    o.symbol_id = symbol_id
    o.contract_symbol = contract_symbol
    o.option_type = option_type
    o.strike = strike
    o.expiration_date = expiration_date
    o.quantity = quantity
    o.status = status
    o.alpaca_order_id = alpaca_order_id
    return o


def _position(
    id: int = 1,
    ticker: str = "AAPL",
    symbol_id: int = 2,
    entry_price: float = 2.50,
    quantity: int = 1,
    status: str = "open",
    time_stop_at: datetime | None = None,
) -> MagicMock:
    p = MagicMock(spec=PaperPosition)
    p.id = id
    p.ticker = ticker
    p.symbol_id = symbol_id
    p.entry_price = entry_price
    p.quantity = quantity
    p.status = status
    p.time_stop_at = time_stop_at
    return p


def _db_mock(
    dry_run_orders: list | None = None,
    submitted_orders: list | None = None,
    open_positions: list | None = None,
    existing_position_for_order: MagicMock | None = None,
) -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()

    def query_side_effect(model):
        q = MagicMock()

        def filter_side_effect(*args, **kwargs):
            fq = MagicMock()
            fq.filter.return_value = fq

            def inner_first():
                return existing_position_for_order

            fq.first.side_effect = inner_first

            def all_side_effect():
                if model is PaperOrder:
                    # Determine which list by inspecting the filter args
                    # (simplified: return whichever list is non-empty)
                    for arg in args:
                        arg_str = str(arg)
                        if "dry_run" in arg_str:
                            return dry_run_orders or []
                        if "submitted" in arg_str:
                            return submitted_orders or []
                if model is PaperPosition:
                    return open_positions or []
                return []

            fq.all.side_effect = all_side_effect
            return fq

        q.filter.side_effect = filter_side_effect
        return q

    db.query.side_effect = query_side_effect
    return db


# ---------------------------------------------------------------------------
# dry_run order → position
# ---------------------------------------------------------------------------


def _dry_run_db(order: MagicMock, existing_position: MagicMock | None = None) -> MagicMock:
    """Build a db mock that returns a dry_run order and optional existing position.

    _promote_fills is a no-op when broker is None, so the only PaperOrder query
    comes from _open_dry_run_positions — always return [order].
    """
    db = MagicMock()
    db.flush = MagicMock()

    def add_side_effect(obj):
        if isinstance(obj, PaperPosition):
            obj.id = 99

    db.add.side_effect = add_side_effect

    def query_side_effect(model):
        q = MagicMock()
        fq = MagicMock()
        fq.filter.return_value = fq

        if model is PaperOrder:
            fq.all.return_value = [order]
            fq.first.return_value = None
        elif model is PaperPosition:
            fq.all.return_value = []
            fq.first.return_value = existing_position
        else:
            fq.all.return_value = []
            fq.first.return_value = None

        q.filter.return_value = fq
        return q

    db.query.side_effect = query_side_effect
    return db


def test_process_opens_dry_run_position():
    order = _order(status="dry_run")
    captured_positions: list = []
    db = _dry_run_db(order)
    orig_add = db.add.side_effect

    def capturing_add(obj):
        captured_positions.append(obj)
        if orig_add:
            orig_add(obj)

    db.add.side_effect = capturing_add

    PositionManager().process(db)

    positions = [o for o in captured_positions if isinstance(o, PaperPosition)]
    assert len(positions) == 1
    assert positions[0].status == "open"


def test_process_sets_order_filled_on_dry_run():
    order = _order(status="dry_run")
    db = _dry_run_db(order)

    PositionManager().process(db)

    assert order.status == "filled"
    assert order.fill_price == 0.0


def test_process_does_not_double_open_dry_run_position():
    """If a position already exists for the dry_run order, skip it."""
    order = _order(status="dry_run")
    existing_pos = _position()
    added: list = []
    db = _dry_run_db(order, existing_position=existing_pos)
    db.add.side_effect = lambda o: added.append(o)

    PositionManager().process(db)

    new_positions = [o for o in added if isinstance(o, PaperPosition)]
    assert len(new_positions) == 0


# ---------------------------------------------------------------------------
# time stop exit
# ---------------------------------------------------------------------------


def test_process_closes_position_on_time_stop():
    past_stop = _NOW - timedelta(minutes=5)
    pos = _position(status="open", time_stop_at=past_stop, entry_price=2.0)
    db = MagicMock()
    db.flush = MagicMock()
    added: list = []
    db.add.side_effect = lambda o: added.append(o)

    def query_side_effect(model):
        q = MagicMock()

        def filter_se(*args, **kwargs):
            fq = MagicMock()
            fq.filter.return_value = fq
            fq.all.return_value = [pos] if model is PaperPosition else []
            fq.first.return_value = None
            return fq

        q.filter.side_effect = filter_se
        return q

    db.query.side_effect = query_side_effect

    PositionManager().process(db)

    assert pos.status == "closed"
    assert pos.exit_reason == "time_stop"
    events = [o for o in added if isinstance(o, PositionEvent)]
    assert any("time_stop" in (e.event_type or "") for e in events)


def test_process_does_not_close_position_before_time_stop():
    future_stop = datetime.now(UTC) + timedelta(hours=2)
    pos = _position(status="open", time_stop_at=future_stop)
    db = MagicMock()
    db.flush = MagicMock()

    def query_side_effect(model):
        q = MagicMock()

        def filter_se(*args, **kwargs):
            fq = MagicMock()
            fq.filter.return_value = fq
            fq.all.return_value = [pos] if model is PaperPosition else []
            fq.first.return_value = None
            return fq

        q.filter.side_effect = filter_se
        return q

    db.query.side_effect = query_side_effect

    PositionManager().process(db)

    assert pos.status == "open"


def test_process_no_exit_when_no_time_stop_set():
    pos = _position(status="open", time_stop_at=None)
    db = MagicMock()
    db.flush = MagicMock()

    def query_side_effect(model):
        q = MagicMock()

        def filter_se(*args, **kwargs):
            fq = MagicMock()
            fq.filter.return_value = fq
            fq.all.return_value = [pos] if model is PaperPosition else []
            fq.first.return_value = None
            return fq

        q.filter.side_effect = filter_se
        return q

    db.query.side_effect = query_side_effect

    PositionManager().process(db)

    assert pos.status == "open"


# ---------------------------------------------------------------------------
# pnl calculation
# ---------------------------------------------------------------------------


def test_close_position_calculates_pnl():
    past_stop = _NOW - timedelta(minutes=1)
    pos = _position(status="open", time_stop_at=past_stop, entry_price=2.0, quantity=1)
    # exit at entry (0 pnl in dry_run — entry_price=0.0 so exit=0.0 too)
    # Use a real position to check math
    db = MagicMock()
    db.flush = MagicMock()
    added: list = []
    db.add.side_effect = lambda o: added.append(o)

    def query_side_effect(model):
        q = MagicMock()

        def filter_se(*args, **kwargs):
            fq = MagicMock()
            fq.filter.return_value = fq
            fq.all.return_value = [pos] if model is PaperPosition else []
            fq.first.return_value = None
            return fq

        q.filter.side_effect = filter_se
        return q

    db.query.side_effect = query_side_effect

    PositionManager().process(db)

    # exit_price == entry_price == 2.0 → pnl = 0
    assert pos.pnl == pytest.approx(0.0)
    assert pos.pnl_pct == pytest.approx(0.0)
