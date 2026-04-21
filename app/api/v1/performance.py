from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.execution import DailyMetric

router = APIRouter(prefix="/performance", tags=["performance"])


class PerformanceDayOut(BaseModel):
    metric_date: date
    total_signals: int
    total_alerts: int
    total_paper_orders: int
    total_positions_closed: int
    winning_positions: int
    losing_positions: int
    total_pnl: float | None
    avg_score: float | None
    alerts_by_grade: dict

    model_config = {"from_attributes": True}


@router.get("", response_model=list[PerformanceDayOut])
def list_performance(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> list[DailyMetric]:
    cutoff = date.today() - timedelta(days=days)
    return (
        db.query(DailyMetric)
        .filter(DailyMetric.metric_date >= cutoff)
        .order_by(desc(DailyMetric.metric_date))
        .all()
    )
