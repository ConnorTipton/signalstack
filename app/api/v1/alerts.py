from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.execution import Alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertOut(BaseModel):
    id: int
    ticker: str
    direction: str
    score: float
    grade: str | None
    contract_symbol: str | None
    expiration_date: date | None
    strike: float | None
    option_type: str | None
    entry_condition: str | None
    invalidation: str | None
    target1: str | None
    target2: str | None
    time_stop: str | None
    reason: str | None
    liquidity_note: str | None
    data_note: str | None
    dry_run: bool
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AlertOut])
def list_alerts(
    ticker: str | None = Query(None),
    sent_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Alert]:
    q = db.query(Alert)
    if sent_only:
        q = q.filter(Alert.sent_at.isnot(None))
    if ticker:
        q = q.filter(Alert.ticker == ticker.upper())
    return q.order_by(desc(Alert.created_at)).limit(limit).all()
