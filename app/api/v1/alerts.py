from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_db
from app.db.models.execution import Alert
from app.db.models.signals import DetectedEvent, SignalCandidate

router = APIRouter(prefix="/alerts", tags=["alerts"])


class DetectorEvidenceOut(BaseModel):
    # News (Detector A)
    news_summary: str | None = None
    news_event_type: str | None = None
    news_polarity: str | None = None
    news_confidence: float | None = None
    news_importance: float | None = None
    news_source_tier: int | None = None

    # Price (Detector B)
    price_pattern: str | None = None
    price_confidence: float | None = None
    price_polarity: str | None = None

    # Options (Detector C)
    options_signal: str | None = None
    options_confidence: float | None = None
    options_relative_activity: str | None = None

    # Scoring breakdown
    news_score: float | None = None
    price_score: float | None = None
    options_score: float | None = None
    liquidity_score: float | None = None
    data_confidence_score: float | None = None
    provider_confidence: float | None = None

    # Contract detail
    contract_bid: float | None = None
    contract_ask: float | None = None
    contract_spread_pct: float | None = None
    contract_oi: int | None = None
    contract_volume: int | None = None
    contract_selection_reason: str | None = None
    contract_rejection_json: list | None = None


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
    evidence: DetectorEvidenceOut | None = None

    model_config = {"from_attributes": True}


def _build_evidence(
    candidate: SignalCandidate | None,
    news_event: DetectedEvent | None,
    price_event: DetectedEvent | None,
    options_event: DetectedEvent | None,
) -> DetectorEvidenceOut | None:
    if candidate is None:
        return None

    def _f(val: object) -> float | None:
        return float(val) if val is not None else None  # type: ignore[arg-type]

    rel_activity: str | None = None
    if options_event and options_event.metadata_json:
        raw = options_event.metadata_json.get("relative_activity")
        if raw is not None:
            rel_activity = str(raw)

    return DetectorEvidenceOut(
        news_summary=news_event.one_sentence_summary if news_event else None,
        news_event_type=news_event.event_type if news_event else None,
        news_polarity=news_event.polarity if news_event else None,
        news_confidence=_f(news_event.confidence) if news_event else None,
        news_importance=_f(news_event.importance) if news_event else None,
        news_source_tier=news_event.source_tier if news_event else None,
        price_pattern=price_event.event_type if price_event else None,
        price_confidence=_f(price_event.confidence) if price_event else None,
        price_polarity=price_event.polarity if price_event else None,
        options_signal=options_event.event_type if options_event else None,
        options_confidence=_f(options_event.confidence) if options_event else None,
        options_relative_activity=rel_activity,
        news_score=_f(candidate.news_score),
        price_score=_f(candidate.price_score),
        options_score=_f(candidate.options_score),
        liquidity_score=_f(candidate.liquidity_score),
        data_confidence_score=_f(candidate.data_confidence_score),
        provider_confidence=_f(candidate.provider_confidence),
        contract_bid=_f(candidate.contract_bid),
        contract_ask=_f(candidate.contract_ask),
        contract_spread_pct=_f(candidate.contract_spread_pct),
        contract_oi=candidate.contract_oi,
        contract_volume=candidate.contract_volume,
        contract_selection_reason=candidate.contract_selection_reason,
        contract_rejection_json=candidate.contract_rejection_json,
    )


def _fetch_alerts(
    db: Session,
    *,
    ticker: str | None = None,
    sent_only: bool = True,
    limit: int = 50,
    alert_id: int | None = None,
) -> list[AlertOut]:
    """Single query (4 outer joins) to fetch alerts with full evidence."""
    NewsDE = aliased(DetectedEvent)
    PriceDE = aliased(DetectedEvent)
    OptionsDE = aliased(DetectedEvent)

    q = (
        db.query(Alert, SignalCandidate, NewsDE, PriceDE, OptionsDE)
        .outerjoin(SignalCandidate, Alert.signal_candidate_id == SignalCandidate.id)
        .outerjoin(NewsDE, NewsDE.id == SignalCandidate.news_event_id)
        .outerjoin(PriceDE, PriceDE.id == SignalCandidate.price_event_id)
        .outerjoin(OptionsDE, OptionsDE.id == SignalCandidate.options_event_id)
    )
    if sent_only:
        q = q.filter(Alert.sent_at.isnot(None))
    if ticker:
        q = q.filter(Alert.ticker == ticker.upper())
    if alert_id is not None:
        q = q.filter(Alert.id == alert_id)
    q = q.order_by(desc(Alert.created_at)).limit(limit)

    results: list[AlertOut] = []
    for alert, candidate, news_de, price_de, options_de in q.all():
        out = AlertOut.model_validate(alert)
        out.evidence = _build_evidence(candidate, news_de, price_de, options_de)
        results.append(out)
    return results


@router.get("", response_model=list[AlertOut])
def list_alerts(
    ticker: str | None = Query(None),
    sent_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    return _fetch_alerts(db, ticker=ticker, sent_only=sent_only, limit=limit)


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertOut:
    results = _fetch_alerts(db, alert_id=alert_id, sent_only=False, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail="Alert not found")
    return results[0]
