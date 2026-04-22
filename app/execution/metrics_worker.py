"""Daily performance metrics worker.

Refreshes ``daily_metrics`` from execution and signal tables so the review API
has real data to serve instead of relying on manually inserted rows.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.execution import Alert, DailyMetric, PaperOrder, PaperPosition
from app.db.models.signals import SignalCandidate
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 300.0


class DailyMetricsWorker:
    """Async worker that periodically upserts today's ``daily_metrics`` row."""

    def __init__(self, *, interval_seconds: float = _DEFAULT_INTERVAL) -> None:
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: refresh metrics, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                await asyncio.to_thread(self._run_once_in_session)
                log.debug("DailyMetricsWorker: refreshed metrics")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("DailyMetricsWorker cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def _run_once_in_session(self) -> DailyMetric:
        with SessionLocal() as db:
            return self.run_once(db)

    def run_once(self, db: Session, metric_date: date | None = None) -> DailyMetric:
        """Refresh one UTC day's aggregate metrics and return the row."""
        day = metric_date or datetime.now(UTC).date()
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)

        row = db.query(DailyMetric).filter(DailyMetric.metric_date == day).first()
        if row is None:
            row = DailyMetric(metric_date=day)
            db.add(row)

        row.total_signals = _count_between(
            db, SignalCandidate, SignalCandidate.created_at, start, end
        )
        row.total_alerts = _count_between(db, Alert, Alert.created_at, start, end)
        row.total_paper_orders = _count_between(db, PaperOrder, PaperOrder.created_at, start, end)

        closed = (
            db.query(PaperPosition)
            .filter(
                PaperPosition.status == "closed",
                PaperPosition.closed_at >= start,
                PaperPosition.closed_at < end,
            )
            .all()
        )
        row.total_positions_closed = len(closed)
        row.winning_positions = sum(1 for p in closed if float(p.pnl or 0) > 0)
        row.losing_positions = sum(1 for p in closed if float(p.pnl or 0) < 0)
        row.total_pnl = round(sum(float(p.pnl or 0) for p in closed), 4)

        avg_score = (
            db.query(func.avg(SignalCandidate.score))
            .filter(SignalCandidate.created_at >= start, SignalCandidate.created_at < end)
            .scalar()
        )
        row.avg_score = round(float(avg_score), 2) if avg_score is not None else None

        grade_rows = (
            db.query(Alert.grade, func.count(Alert.id))
            .filter(Alert.created_at >= start, Alert.created_at < end)
            .group_by(Alert.grade)
            .all()
        )
        row.alerts_by_grade = {grade or "?": count for grade, count in grade_rows}
        row.updated_at = datetime.now(UTC)
        db.commit()
        return row


def _count_between(db: Session, model, column, start: datetime, end: datetime) -> int:
    return int(db.query(func.count(model.id)).filter(column >= start, column < end).scalar() or 0)
