"""Unit tests for PositionManager (Phase 8)."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.db.models.execution import PaperOrder, PaperPosition, PositionEvent
from app.db.models.market import OptionQuote
from app.execution.position_manager import PositionManager, _parse_time_stop

_NOW = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
_ET = ZoneInfo("America/New_York")


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
    contract_symbol: str = "AAPL250501C00190000",
    order_id: int = 1,
    entry_price: float = 2.50,
    quantity: int = 1,
    status: str = "open",
    time_stop_at: datetime | None = None,
    target1_price: float | None = None,
    target2_price: float | None = None,
    invalidation_price: float | None = None,
) -> MagicMock:
    p = MagicMock(spec=PaperPosition)
    p.id = id
    p.ticker = ticker
    p.symbol_id = symbol_id
    p.contract_symbol = contract_symbol
    p.order_id = order_id
    p.entry_price = entry_price
    p.quantity = quantity
    p.status = status
    p.time_stop_at = time_stop_at
    p.target1_price = target1_price
    p.target2_price = target2_price
    p.invalidation_price = invalidation_price
    return p


def _dry_run_db(order: MagicMock, existing_position: MagicMock | None = None) -> MagicMock:
    """Build a db mock that returns a dry_run order and optional existing position.

    _promote_fills is a no-op when broker is None, so the only PaperOrder query
    comes from _open_dry_run_positions — always return [order].
    """
    db = MagicMock()
    db.flush = MagicMock()
    db.get.return_value = None  # Alert lookup returns None → _parse_time_stop uses expiration date

    def add_side_effect(obj):
        if isinstance(obj, PaperPosition):
            obj.id = 99

    db.add.side_effect = add_side_effect

    def query_side_effect(model):
        q = MagicMock()
        fq = MagicMock()
        fq.filter.return_value = fq
        fq.order_by.return_value = fq  # chain order_by so OptionQuote lookups work
        fq.limit.return_value = fq

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


def _exit_db(
    position: MagicMock,
    bid_price: float | None = None,
    has_live_order: bool = False,
) -> MagicMock:
    """Build a db mock for _check_exits tests.

    Returns empty results for Phase A/B queries, [position] for Phase C,
    and optionally a bid price from option_quotes and a live PaperOrder.
    """
    db = MagicMock()
    db.flush = MagicMock()
    db.add = MagicMock()

    def get_side_effect(model, id_):
        if model is PaperOrder:
            if has_live_order:
                mock_order = MagicMock(spec=PaperOrder)
                mock_order.alpaca_order_id = "alp_test_123"
                return mock_order
            return None
        return None

    db.get.side_effect = get_side_effect

    def query_side_effect(model):
        q = MagicMock()
        fq = MagicMock()
        fq.filter.return_value = fq
        fq.order_by.return_value = fq
        fq.limit.return_value = fq

        if model is PaperPosition:
            fq.all.return_value = [position]
            fq.first.return_value = None
        elif model is OptionQuote:
            if bid_price is not None:
                mock_quote = MagicMock()
                mock_quote.bid = bid_price
                mock_quote.ask = bid_price  # use same value for simplicity
                fq.first.return_value = mock_quote
            else:
                fq.first.return_value = None
        else:
            fq.all.return_value = []
            fq.first.return_value = None

        q.filter.return_value = fq
        return q

    db.query.side_effect = query_side_effect
    return db


def _limited_query_db(rows=None) -> tuple[MagicMock, MagicMock]:
    db = MagicMock()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = rows or []
    db.query.return_value = query
    return db, query


# ---------------------------------------------------------------------------
# _parse_time_stop unit tests (no DB)
# ---------------------------------------------------------------------------


def test_parse_time_stop_end_of_day():
    now_et = datetime.now(_ET)
    expected = datetime(now_et.year, now_et.month, now_et.day, 16, 0, tzinfo=_ET).astimezone(UTC)
    assert _parse_time_stop("exit end of day", date(2025, 5, 1)) == expected


def test_parse_time_stop_eod_keyword():
    now_et = datetime.now(_ET)
    expected = datetime(now_et.year, now_et.month, now_et.day, 16, 0, tzinfo=_ET).astimezone(UTC)
    assert _parse_time_stop("EOD exit", date(2025, 5, 1)) == expected


def test_parse_time_stop_n_days():
    now_et = datetime.now(_ET)
    target = now_et.date() + timedelta(days=2)
    expected = datetime(target.year, target.month, target.day, 16, 0, tzinfo=_ET).astimezone(UTC)
    assert _parse_time_stop("exit in 2 days if not triggered", date(2025, 5, 1)) == expected


def test_parse_time_stop_hours():
    before = datetime.now(UTC)
    result = _parse_time_stop("exit after 4 hours", date(2025, 5, 1))
    after = datetime.now(UTC)
    assert before + timedelta(hours=4) <= result <= after + timedelta(hours=4)


def test_parse_time_stop_none_falls_back_to_expiration():
    exp = date(2025, 5, 1)
    expected = datetime(2025, 5, 1, 16, 0, tzinfo=_ET).astimezone(UTC)
    assert _parse_time_stop(None, exp) == expected


def test_parse_time_stop_unrecognised_text_falls_back_to_expiration():
    exp = date(2025, 6, 15)
    expected = datetime(2025, 6, 15, 16, 0, tzinfo=_ET).astimezone(UTC)
    assert _parse_time_stop("exit when comfortable", exp) == expected


# ---------------------------------------------------------------------------
# dry_run order → position
# ---------------------------------------------------------------------------


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
    # no ask price in mock → entry_price defaults to 0.0
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


def test_process_opens_position_with_ask_price_as_entry():
    """When option_quotes has an ask, use it as entry_price (not 0.0)."""
    order = _order(status="dry_run")
    db = MagicMock()
    db.flush = MagicMock()
    db.get.return_value = None
    captured: list = []

    def add_se(obj):
        if isinstance(obj, PaperPosition):
            obj.id = 99
        captured.append(obj)

    db.add.side_effect = add_se

    def query_se(model):
        q = MagicMock()
        fq = MagicMock()
        fq.filter.return_value = fq
        fq.order_by.return_value = fq
        fq.limit.return_value = fq
        if model is PaperOrder:
            fq.all.return_value = [order]
            fq.first.return_value = None
        elif model is PaperPosition:
            fq.all.return_value = []
            fq.first.return_value = None
        elif model is OptionQuote:
            mock_quote = MagicMock()
            mock_quote.ask = 3.50
            fq.first.return_value = mock_quote
        else:
            fq.all.return_value = []
            fq.first.return_value = None
        q.filter.return_value = fq
        return q

    db.query.side_effect = query_se

    PositionManager().process(db)

    positions = [o for o in captured if isinstance(o, PaperPosition)]
    assert len(positions) == 1
    assert float(positions[0].entry_price) == pytest.approx(3.50)


def test_open_position_sets_target_prices():
    """target1=2× entry, invalidation=0.5× entry should be set on new positions."""
    order = _order(status="dry_run")
    db = MagicMock()
    db.flush = MagicMock()
    db.get.return_value = None
    captured: list = []

    def add_se(obj):
        if isinstance(obj, PaperPosition):
            obj.id = 99
        captured.append(obj)

    db.add.side_effect = add_se

    def query_se(model):
        q = MagicMock()
        fq = MagicMock()
        fq.filter.return_value = fq
        fq.order_by.return_value = fq
        fq.limit.return_value = fq
        if model is PaperOrder:
            fq.all.return_value = [order]
            fq.first.return_value = None
        elif model is PaperPosition:
            fq.all.return_value = []
            fq.first.return_value = None
        elif model is OptionQuote:
            mock_quote = MagicMock()
            mock_quote.ask = 2.0
            fq.first.return_value = mock_quote
        else:
            fq.all.return_value = []
            fq.first.return_value = None
        q.filter.return_value = fq
        return q

    db.query.side_effect = query_se

    PositionManager().process(db)

    positions = [o for o in captured if isinstance(o, PaperPosition)]
    pos = positions[0]
    assert float(pos.target1_price) == pytest.approx(4.0)  # 2× entry
    assert float(pos.invalidation_price) == pytest.approx(1.0)  # 0.5× entry


def test_open_position_sets_time_stop_at():
    """time_stop_at must be set to a non-None datetime when opening a position."""
    order = _order(status="dry_run")
    db = _dry_run_db(order)
    captured: list = []
    orig_add = db.add.side_effect

    def capturing_add(obj):
        captured.append(obj)
        if orig_add:
            orig_add(obj)

    db.add.side_effect = capturing_add

    PositionManager().process(db)

    positions = [o for o in captured if isinstance(o, PaperPosition)]
    assert len(positions) == 1
    assert isinstance(positions[0].time_stop_at, datetime)


# ---------------------------------------------------------------------------
# time stop exit
# ---------------------------------------------------------------------------


def _time_stop_db(positions: list, *, order_by_chained: bool = True) -> MagicMock:
    """Minimal db mock for time-stop tests."""
    db = MagicMock()
    db.flush = MagicMock()
    added: list = []
    db.add.side_effect = lambda o: added.append(o)
    db._captured = added

    def query_side_effect(model):
        q = MagicMock()

        def filter_se(*args, **kwargs):
            fq = MagicMock()
            fq.filter.return_value = fq
            fq.order_by.return_value = fq  # chain so OptionQuote lookups return None cleanly
            fq.limit.return_value = fq
            fq.all.return_value = positions if model is PaperPosition else []
            fq.first.return_value = None
            return fq

        q.filter.side_effect = filter_se
        return q

    db.query.side_effect = query_side_effect
    return db


def test_process_closes_position_on_time_stop():
    past_stop = _NOW - timedelta(minutes=5)
    pos = _position(status="open", time_stop_at=past_stop, entry_price=2.0)
    db = _time_stop_db([pos])

    PositionManager().process(db)

    assert pos.status == "closed"
    assert pos.exit_reason == "time_stop"
    events = [o for o in db._captured if isinstance(o, PositionEvent)]
    assert any("time_stop" in (e.event_type or "") for e in events)


def test_process_does_not_close_position_before_time_stop():
    future_stop = datetime.now(UTC) + timedelta(hours=2)
    pos = _position(status="open", time_stop_at=future_stop)
    db = _time_stop_db([pos])

    PositionManager().process(db)

    assert pos.status == "open"


def test_process_no_exit_when_no_time_stop_set():
    pos = _position(status="open", time_stop_at=None)
    db = _time_stop_db([pos])

    PositionManager().process(db)

    assert pos.status == "open"


def test_promote_fills_applies_order_batch_limit():
    db, query = _limited_query_db()

    PositionManager(broker_client=MagicMock(), order_batch_size=7)._promote_fills(db)

    query.limit.assert_called_once_with(7)


def test_open_dry_run_positions_applies_order_batch_limit():
    db, query = _limited_query_db()

    PositionManager(order_batch_size=8)._open_dry_run_positions(db)

    query.limit.assert_called_once_with(8)


def test_check_exits_applies_position_batch_limit():
    db, query = _limited_query_db()

    PositionManager(position_batch_size=9)._check_exits(db)

    query.limit.assert_called_once_with(9)


# ---------------------------------------------------------------------------
# Price-based exits
# ---------------------------------------------------------------------------


def test_check_exits_closes_on_invalidation_when_bid_low():
    pos = _position(entry_price=2.0, invalidation_price=1.0)
    db = _exit_db(pos, bid_price=0.80)

    PositionManager().process(db)

    assert pos.status == "closed"
    assert pos.exit_reason == "invalidation"


def test_check_exits_closes_on_target1_when_bid_high():
    pos = _position(entry_price=2.0, target1_price=4.0, invalidation_price=1.0)
    db = _exit_db(pos, bid_price=4.50)

    PositionManager().process(db)

    assert pos.status == "closed"
    assert pos.exit_reason == "target1"


def test_check_exits_no_exit_when_bid_between_invalidation_and_target():
    pos = _position(entry_price=2.0, target1_price=4.0, invalidation_price=1.0)
    db = _exit_db(pos, bid_price=2.50)

    PositionManager().process(db)

    assert pos.status == "open"


def test_check_exits_no_exit_when_no_bid_available():
    pos = _position(entry_price=2.0, target1_price=4.0, invalidation_price=1.0)
    db = _exit_db(pos, bid_price=None)

    PositionManager().process(db)

    assert pos.status == "open"


def test_check_exits_submits_sell_for_live_position():
    """When a position is backed by a real Alpaca order, sell order is submitted."""
    pos = _position(entry_price=2.0, invalidation_price=1.0)
    broker = MagicMock()
    db = _exit_db(pos, bid_price=0.80, has_live_order=True)

    PositionManager(broker_client=broker).process(db)

    broker.submit_limit_order.assert_called_once()
    kwargs = broker.submit_limit_order.call_args.kwargs
    assert kwargs["side"] == "sell"
    assert pos.status == "closed"


def test_check_exits_skips_sell_for_dry_run_position():
    """Dry-run positions (no Alpaca buy) still get closed in DB but no sell submitted."""
    pos = _position(entry_price=2.0, invalidation_price=1.0)
    broker = MagicMock()
    db = _exit_db(pos, bid_price=0.80, has_live_order=False)

    PositionManager(broker_client=broker).process(db)

    broker.submit_limit_order.assert_not_called()
    assert pos.status == "closed"


def test_check_exits_skips_sell_when_no_broker():
    """No broker configured → position closes in DB without network call."""
    pos = _position(entry_price=2.0, invalidation_price=1.0)
    db = _exit_db(pos, bid_price=0.80)

    PositionManager(broker_client=None).process(db)

    assert pos.status == "closed"


# ---------------------------------------------------------------------------
# pnl calculation
# ---------------------------------------------------------------------------


def test_close_position_calculates_pnl():
    past_stop = _NOW - timedelta(minutes=1)
    pos = _position(status="open", time_stop_at=past_stop, entry_price=2.0, quantity=1)
    db = _time_stop_db([pos])

    PositionManager().process(db)

    # no bid price in mock → exit_price falls back to entry_price → pnl = 0
    assert pos.pnl == pytest.approx(0.0)
    assert pos.pnl_pct == pytest.approx(0.0)


def test_close_position_pnl_with_real_exit_price():
    pos = _position(entry_price=2.0, invalidation_price=1.0, quantity=1)
    db = _exit_db(pos, bid_price=0.50)

    PositionManager().process(db)

    # pnl = (0.50 - 2.0) * 1 * 100 = -150.0
    assert pos.pnl == pytest.approx(-150.0)
    # pnl_pct = (0.50 - 2.0) / 2.0 = -0.75
    assert pos.pnl_pct == pytest.approx(-0.75)
