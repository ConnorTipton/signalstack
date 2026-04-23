from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.news import NewsArticle

router = APIRouter(prefix="/source-trace", tags=["source-trace"])


class SourceTraceRow(BaseModel):
    article_id: int
    provider_name: str
    source_tier: int
    raw_table: str
    raw_event_id: str | None
    received_at: datetime
    title: str


# Map news source_name → raw event table that stored it first.
_RAW_TABLE_BY_SOURCE: dict[str, str] = {
    "edgar": "raw_official_news_events",
    "sec": "raw_official_news_events",
    "businesswire": "raw_official_news_events",
    "globenewswire": "raw_official_news_events",
    "prnewswire": "raw_official_news_events",
    "marketaux": "raw_marketaux_events",
    "alpaca_news": "raw_news_backup_events",
}


def _raw_table_for(source_name: str) -> str:
    key = source_name.lower()
    return _RAW_TABLE_BY_SOURCE.get(key, "raw_news_backup_events")


@router.get("", response_model=list[SourceTraceRow])
def list_source_trace(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[SourceTraceRow]:
    """Recent news articles with their raw-event lineage.

    Each row maps `article_id` → the raw table its payload was stored in
    before normalization, via the article's `source_name`.
    """
    rows = (
        db.query(NewsArticle)
        .order_by(desc(NewsArticle.received_at))
        .limit(limit)
        .all()
    )
    return [
        SourceTraceRow(
            article_id=a.id,
            provider_name=a.source_name,
            source_tier=a.source_tier,
            raw_table=_raw_table_for(a.source_name),
            raw_event_id=a.provider_event_id,
            received_at=a.received_at,
            title=a.title,
        )
        for a in rows
    ]
