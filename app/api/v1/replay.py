from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.replay.report import ReplayReport
from app.replay.scenario_runner import ScenarioRunner

router = APIRouter(prefix="/replay", tags=["replay"])

_runner = ScenarioRunner()


@router.get("", response_model=ReplayReport)
def run_replay(
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    ticker: list[str] = Query(default=[]),
    max_events: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> ReplayReport:
    return _runner.run(
        db,
        window_start=window_start,
        window_end=window_end,
        tickers=ticker or None,
        max_timeline_events=max_events,
    )
