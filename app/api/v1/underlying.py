from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.market import UnderlyingBar1m
from app.db.models.symbols import Symbol

router = APIRouter(prefix="/underlying", tags=["underlying"])


class BarOut(BaseModel):
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None


@router.get("/{ticker}/bars", response_model=list[BarOut])
def recent_bars(
    ticker: str,
    minutes: int = Query(60, ge=5, le=390),
    db: Session = Depends(get_db),
) -> list[BarOut]:
    """Recent 1-minute bars for a ticker, oldest first."""
    sym = db.query(Symbol).filter(Symbol.ticker == ticker.upper()).first()
    if sym is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker}")
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    rows = (
        db.query(UnderlyingBar1m)
        .filter(UnderlyingBar1m.symbol_id == sym.id, UnderlyingBar1m.bar_time >= cutoff)
        .order_by(UnderlyingBar1m.bar_time.asc())
        .all()
    )
    return [
        BarOut(
            bar_time=r.bar_time,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=int(r.volume),
            vwap=float(r.vwap) if r.vwap is not None else None,
        )
        for r in rows
    ]
