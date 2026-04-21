from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.provider import ProviderHealth

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderHealthOut(BaseModel):
    provider_name: str
    is_healthy: bool
    provider_confidence: float | None
    last_success_at: datetime | None
    consecutive_failures: int
    lag_seconds: float | None
    error_message: str | None
    checked_at: datetime

    model_config = {"from_attributes": True}


@router.get("/health", response_model=list[ProviderHealthOut])
def provider_health(db: Session = Depends(get_db)) -> list[ProviderHealth]:
    subq = (
        db.query(
            ProviderHealth.provider_name,
            func.max(ProviderHealth.checked_at).label("max_checked_at"),
        )
        .group_by(ProviderHealth.provider_name)
        .subquery()
    )
    return (
        db.query(ProviderHealth)
        .join(
            subq,
            (ProviderHealth.provider_name == subq.c.provider_name)
            & (ProviderHealth.checked_at == subq.c.max_checked_at),
        )
        .all()
    )
