"""Unit tests for Phase 9 Review API endpoints."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app

client = TestClient(app)

_NOW = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
_TODAY = date(2026, 4, 21)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _chain(result: list) -> MagicMock:
    """Chainable SQLAlchemy query mock that always returns result from .all()."""
    m = MagicMock()
    m.filter.return_value = m
    m.order_by.return_value = m
    m.limit.return_value = m
    m.join.return_value = m
    m.group_by.return_value = m
    m.subquery.return_value = MagicMock()
    m.all.return_value = result
    return m


def _db(result: list | None = None) -> MagicMock:
    db = MagicMock()
    db.query.return_value = _chain(result or [])
    db.execute.return_value = MagicMock()
    return db


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def _alert_row(**kw) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "ticker": "AAPL",
        "direction": "bullish",
        "score": 75.0,
        "grade": "A",
        "contract_symbol": "AAPL250501C00190000",
        "expiration_date": date(2025, 5, 1),
        "strike": 190.0,
        "option_type": "call",
        "entry_condition": "break above 190",
        "invalidation": "below 185",
        "target1": "200",
        "target2": "210",
        "time_stop": "2h",
        "reason": "Catalyst: earnings beat",
        "liquidity_note": "OI: 1200",
        "data_note": None,
        "dry_run": True,
        "sent_at": _NOW,
        "created_at": _NOW,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _perf_row(**kw) -> SimpleNamespace:
    defaults = {
        "metric_date": _TODAY,
        "total_signals": 10,
        "total_alerts": 5,
        "total_paper_orders": 3,
        "total_positions_closed": 2,
        "winning_positions": 1,
        "losing_positions": 1,
        "total_pnl": 50.0,
        "avg_score": 72.5,
        "alerts_by_grade": {"A": 3, "B": 2},
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _position_row(**kw) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "ticker": "AAPL",
        "contract_symbol": "AAPL250501C00190000",
        "option_type": "call",
        "strike": 190.0,
        "expiration_date": date(2025, 5, 1),
        "quantity": 1,
        "entry_price": 2.50,
        "status": "open",
        "time_stop_at": None,
        "exit_price": None,
        "exit_reason": None,
        "opened_at": _NOW,
        "closed_at": None,
        "pnl": None,
        "pnl_pct": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _provider_row(**kw) -> SimpleNamespace:
    defaults = {
        "provider_name": "tradier",
        "is_healthy": True,
        "provider_confidence": 0.95,
        "last_success_at": _NOW,
        "consecutive_failures": 0,
        "lag_seconds": 1.2,
        "error_message": None,
        "checked_at": _NOW,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# GET /api/v1/alerts
# ---------------------------------------------------------------------------


def test_alerts_returns_200():
    app.dependency_overrides[get_db] = lambda: _db([_alert_row()])
    assert client.get("/api/v1/alerts").status_code == 200


def test_alerts_returns_list():
    app.dependency_overrides[get_db] = lambda: _db([_alert_row(), _alert_row(id=2)])
    data = client.get("/api/v1/alerts").json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_alerts_response_has_expected_fields():
    app.dependency_overrides[get_db] = lambda: _db([_alert_row()])
    item = client.get("/api/v1/alerts").json()[0]
    assert item["ticker"] == "AAPL"
    assert item["direction"] == "bullish"
    assert item["grade"] == "A"
    assert item["contract_symbol"] == "AAPL250501C00190000"


def test_alerts_sent_only_applies_filter():
    db = _db([_alert_row()])
    app.dependency_overrides[get_db] = lambda: db
    client.get("/api/v1/alerts?sent_only=true")
    # sent_only=True adds a filter call beyond the base query
    assert db.query.return_value.filter.call_count >= 1


def test_alerts_sent_only_false_skips_sent_filter():
    db = _db([_alert_row(sent_at=None)])
    app.dependency_overrides[get_db] = lambda: db
    resp = client.get("/api/v1/alerts?sent_only=false")
    assert resp.status_code == 200


def test_alerts_ticker_filter_applies():
    db = _db([_alert_row(ticker="MSFT")])
    app.dependency_overrides[get_db] = lambda: db
    resp = client.get("/api/v1/alerts?ticker=msft")
    assert resp.status_code == 200
    # Two filter calls: sent_only + ticker
    assert db.query.return_value.filter.call_count >= 2


def test_alerts_empty_returns_empty_list():
    app.dependency_overrides[get_db] = lambda: _db([])
    assert client.get("/api/v1/alerts").json() == []


# ---------------------------------------------------------------------------
# GET /api/v1/performance
# ---------------------------------------------------------------------------


def test_performance_returns_200():
    app.dependency_overrides[get_db] = lambda: _db([_perf_row()])
    assert client.get("/api/v1/performance").status_code == 200


def test_performance_returns_list():
    app.dependency_overrides[get_db] = lambda: _db(
        [_perf_row(), _perf_row(metric_date=date(2026, 4, 20))]
    )
    data = client.get("/api/v1/performance").json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_performance_response_has_expected_fields():
    app.dependency_overrides[get_db] = lambda: _db([_perf_row()])
    item = client.get("/api/v1/performance").json()[0]
    assert item["total_signals"] == 10
    assert item["winning_positions"] == 1
    assert item["total_pnl"] == pytest.approx(50.0)
    assert item["alerts_by_grade"] == {"A": 3, "B": 2}


def test_performance_days_param_accepted():
    app.dependency_overrides[get_db] = lambda: _db([])
    assert client.get("/api/v1/performance?days=7").status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/positions
# ---------------------------------------------------------------------------


def test_positions_returns_200():
    app.dependency_overrides[get_db] = lambda: _db([_position_row()])
    assert client.get("/api/v1/positions").status_code == 200


def test_positions_returns_list():
    app.dependency_overrides[get_db] = lambda: _db([_position_row(), _position_row(id=2)])
    data = client.get("/api/v1/positions").json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_positions_response_has_expected_fields():
    app.dependency_overrides[get_db] = lambda: _db([_position_row()])
    item = client.get("/api/v1/positions").json()[0]
    assert item["ticker"] == "AAPL"
    assert item["status"] == "open"
    assert item["entry_price"] == pytest.approx(2.50)


def test_positions_default_status_open():
    db = _db([_position_row()])
    app.dependency_overrides[get_db] = lambda: db
    client.get("/api/v1/positions")
    # Default status=open adds a filter
    assert db.query.return_value.filter.call_count >= 1


def test_positions_status_all_skips_status_filter():
    db = _db(
        [
            _position_row(
                status="closed",
                exit_price=3.0,
                exit_reason="time_stop",
                closed_at=_NOW,
                pnl=50.0,
                pnl_pct=0.20,
            )
        ]
    )
    app.dependency_overrides[get_db] = lambda: db
    resp = client.get("/api/v1/positions?status=closed")
    assert resp.status_code == 200


def test_positions_ticker_filter():
    db = _db([_position_row(ticker="MSFT")])
    app.dependency_overrides[get_db] = lambda: db
    resp = client.get("/api/v1/positions?ticker=msft")
    assert resp.status_code == 200
    assert db.query.return_value.filter.call_count >= 2


# ---------------------------------------------------------------------------
# GET /api/v1/providers/health
# ---------------------------------------------------------------------------


def test_provider_health_returns_200():
    app.dependency_overrides[get_db] = lambda: _db([_provider_row()])
    assert client.get("/api/v1/providers/health").status_code == 200


def test_provider_health_returns_list():
    app.dependency_overrides[get_db] = lambda: _db(
        [
            _provider_row(provider_name="tradier"),
            _provider_row(provider_name="alpaca", is_healthy=False, consecutive_failures=3),
        ]
    )
    data = client.get("/api/v1/providers/health").json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_provider_health_response_fields():
    app.dependency_overrides[get_db] = lambda: _db([_provider_row()])
    item = client.get("/api/v1/providers/health").json()[0]
    assert item["provider_name"] == "tradier"
    assert item["is_healthy"] is True
    assert item["consecutive_failures"] == 0


def test_provider_health_unhealthy_provider():
    row = _provider_row(
        provider_name="alpaca",
        is_healthy=False,
        consecutive_failures=5,
        error_message="timeout",
    )
    app.dependency_overrides[get_db] = lambda: _db([row])
    item = client.get("/api/v1/providers/health").json()[0]
    assert item["is_healthy"] is False
    assert item["consecutive_failures"] == 5
    assert item["error_message"] == "timeout"


# ---------------------------------------------------------------------------
# GET /api/v1/health
# ---------------------------------------------------------------------------


def test_system_health_returns_200():
    app.dependency_overrides[get_db] = lambda: _db()
    assert client.get("/api/v1/health").status_code == 200


def test_system_health_db_ok():
    app.dependency_overrides[get_db] = lambda: _db()
    data = client.get("/api/v1/health").json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert "timestamp" in data


def test_system_health_db_error():
    bad_db = MagicMock()
    bad_db.execute.side_effect = RuntimeError("connection refused")
    app.dependency_overrides[get_db] = lambda: bad_db
    data = client.get("/api/v1/health").json()
    assert data["status"] == "degraded"
    assert data["database"] == "error"
