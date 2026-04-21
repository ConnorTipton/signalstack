from datetime import UTC, datetime

from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "runtime_mode": settings.runtime_mode.value,
        "timestamp": datetime.now(UTC).isoformat(),
    }
