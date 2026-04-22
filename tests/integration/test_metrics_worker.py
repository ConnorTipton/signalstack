"""Integration tests for DailyMetricsWorker aggregation."""

from datetime import UTC, date, datetime

from app.db.models.execution import Alert, DailyMetric, PaperOrder, PaperPosition
from app.db.models.signals import SignalCandidate
from app.execution.metrics_worker import DailyMetricsWorker

_DAY = date(2026, 4, 22)
_NOW = datetime(2026, 4, 22, 15, 0, tzinfo=UTC)


def test_daily_metrics_worker_populates_counts(db_session):
    db_session.add(
        SignalCandidate(
            symbol_id=1,
            ticker="AAPL",
            score=80.0,
            status="promoted",
            created_at=_NOW,
        )
    )
    db_session.add(
        Alert(
            symbol_id=1,
            ticker="AAPL",
            direction="bullish",
            score=80.0,
            grade="A",
            created_at=_NOW,
        )
    )
    db_session.add(
        PaperOrder(
            symbol_id=1,
            ticker="AAPL",
            contract_symbol="AAPL260501C00190000",
            option_type="call",
            strike=190.0,
            expiration_date=date(2026, 5, 1),
            side="buy",
            created_at=_NOW,
        )
    )
    db_session.add(
        PaperPosition(
            symbol_id=1,
            ticker="AAPL",
            contract_symbol="AAPL260501C00190000",
            option_type="call",
            strike=190.0,
            expiration_date=date(2026, 5, 1),
            quantity=1,
            entry_price=1.0,
            status="closed",
            closed_at=_NOW,
            pnl=25.0,
        )
    )

    row = DailyMetricsWorker().run_once(db_session, metric_date=_DAY)

    assert row.total_signals == 1
    assert row.total_alerts == 1
    assert row.total_paper_orders == 1
    assert row.total_positions_closed == 1
    assert row.winning_positions == 1
    assert float(row.total_pnl) == 25.0
    assert row.alerts_by_grade == {"A": 1}


def test_daily_metrics_worker_updates_existing_row(db_session):
    db_session.add(DailyMetric(metric_date=_DAY, total_alerts=99))
    db_session.flush()

    row = DailyMetricsWorker().run_once(db_session, metric_date=_DAY)

    assert row.total_alerts == 0
    assert db_session.query(DailyMetric).count() == 1
