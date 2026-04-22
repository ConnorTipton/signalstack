"""Unit tests for OrderRouter (Phase 8)."""

from datetime import date
from unittest.mock import MagicMock

from app.db.models.execution import Alert, PaperOrder, PaperPosition
from app.db.models.market import OptionQuote
from app.execution.order_router import OrderRouter


def _alert(
    id: int = 1,
    ticker: str = "AAPL",
    symbol_id: int = 2,
    contract_symbol: str = "AAPL250501C00190000",
    option_type: str = "call",
    strike: float = 190.0,
    expiration_date: date = date(2025, 5, 1),
    sent_at=None,
) -> MagicMock:
    a = MagicMock(spec=Alert)
    a.id = id
    a.ticker = ticker
    a.symbol_id = symbol_id
    a.contract_symbol = contract_symbol
    a.option_type = option_type
    a.strike = strike
    a.expiration_date = expiration_date
    a.sent_at = sent_at
    return a


def _db_mock(
    has_open_position: bool = False,
    has_active_order: bool = False,
    ask_price: float | None = 1.50,
) -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        if model is PaperPosition:
            q.first.return_value = MagicMock() if has_open_position else None
        elif model is PaperOrder:
            q.first.return_value = MagicMock() if has_active_order else None
        elif model is OptionQuote:
            if ask_price is not None:
                mock_quote = MagicMock()
                mock_quote.ask = ask_price
                q.first.return_value = mock_quote
            else:
                q.first.return_value = None
        else:
            q.first.return_value = None
        return q

    db.query.side_effect = query_side_effect
    return db


# ---------------------------------------------------------------------------
# Basic routing
# ---------------------------------------------------------------------------


def test_route_returns_paper_order():
    router = OrderRouter(dry_run=True)
    order = router.route(_alert(), _db_mock())
    assert isinstance(order, PaperOrder)


def test_route_adds_order_to_session():
    db = _db_mock()
    OrderRouter(dry_run=True).route(_alert(), db)
    db.add.assert_called_once()


def test_route_returns_none_when_no_contract_symbol():
    a = _alert(contract_symbol="")
    a.contract_symbol = None
    order = OrderRouter(dry_run=True).route(a, _db_mock())
    assert order is None


def test_route_skips_when_open_position_exists():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock(has_open_position=True))
    assert order is None


def test_route_skips_when_active_order_exists():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock(has_active_order=True))
    assert order is None


# ---------------------------------------------------------------------------
# dry_run behavior
# ---------------------------------------------------------------------------


def test_route_dry_run_sets_status_dry_run():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock(ask_price=1.50))
    assert order.status == "dry_run"


def test_route_returns_none_when_no_ask_price():
    order = OrderRouter(broker_client=None, dry_run=False).route(_alert(), _db_mock(ask_price=None))
    assert order is None


def test_route_non_dry_run_no_broker_sets_status_pending():
    order = OrderRouter(broker_client=None, dry_run=False).route(_alert(), _db_mock(ask_price=1.50))
    assert order.status == "pending"


# ---------------------------------------------------------------------------
# Order fields
# ---------------------------------------------------------------------------


def test_route_sets_ticker():
    order = OrderRouter(dry_run=True).route(_alert(ticker="MSFT"), _db_mock())
    assert order.ticker == "MSFT"


def test_route_sets_contract_symbol():
    order = OrderRouter(dry_run=True).route(
        _alert(contract_symbol="MSFT250501C00300000"), _db_mock()
    )
    assert order.contract_symbol == "MSFT250501C00300000"


def test_route_sets_quantity_one():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock())
    assert order.quantity == 1


def test_route_sets_order_type_limit():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock())
    assert order.order_type == "limit"


def test_route_sets_side_buy():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock())
    assert order.side == "buy"


def test_route_sets_alert_id():
    order = OrderRouter(dry_run=True).route(_alert(id=42), _db_mock())
    assert order.alert_id == 42


def test_route_sets_expiration_date():
    order = OrderRouter(dry_run=True).route(
        _alert(expiration_date=date(2025, 5, 1)), _db_mock()
    )
    assert order.expiration_date == date(2025, 5, 1)


# ---------------------------------------------------------------------------
# Broker submission (live paper)
# ---------------------------------------------------------------------------



def test_route_sets_submit_failed_on_broker_error():
    broker = MagicMock()
    broker.submit_limit_order.side_effect = RuntimeError("network error")

    order = OrderRouter(broker_client=broker, dry_run=False).route(
        _alert(), _db_mock(ask_price=2.35)
    )
    assert order.status == "submit_failed"


# ---------------------------------------------------------------------------
# Limit price from option quote
# ---------------------------------------------------------------------------


def test_route_sets_limit_price_from_quote():
    order = OrderRouter(dry_run=True).route(_alert(), _db_mock(ask_price=2.35))
    assert float(order.limit_price) == 2.35



def test_route_submits_to_broker_when_ask_price_available():
    broker = MagicMock()
    broker.submit_limit_order.return_value = {"id": "alp456", "status": "new"}

    order = OrderRouter(broker_client=broker, dry_run=False).route(
        _alert(), _db_mock(ask_price=3.10)
    )
    broker.submit_limit_order.assert_called_once()
    assert order.status == "submitted"
    assert order.alpaca_order_id == "alp456"


def test_route_no_broker_call_when_no_ask_price():
    broker = MagicMock()

    order = OrderRouter(broker_client=broker, dry_run=False).route(
        _alert(), _db_mock(ask_price=None)
    )
    broker.submit_limit_order.assert_not_called()
    assert order is None
