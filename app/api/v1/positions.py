from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.execution import PaperPosition

router = APIRouter(prefix="/positions", tags=["positions"])


class PositionOut(BaseModel):
    id: int
    ticker: str
    contract_symbol: str
    option_type: str
    strike: float
    expiration_date: date
    quantity: int
    entry_price: float
    status: str
    time_stop_at: datetime | None
    exit_price: float | None
    exit_reason: str | None
    opened_at: datetime
    closed_at: datetime | None
    pnl: float | None
    pnl_pct: float | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[PositionOut])
def list_positions(
    status: str | None = Query("open"),
    ticker: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[PaperPosition]:
    q = db.query(PaperPosition)
    if status:
        q = q.filter(PaperPosition.status == status)
    if ticker:
        q = q.filter(PaperPosition.ticker == ticker.upper())
    return q.order_by(desc(PaperPosition.opened_at)).limit(limit).all()
