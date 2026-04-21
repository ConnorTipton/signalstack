from datetime import UTC, datetime

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "runtime_mode": settings.runtime_mode.value,
        "timestamp": datetime.now(UTC).isoformat(),
    }
