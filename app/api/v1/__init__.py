from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.api.v1 import (
    alerts,
    health,
    performance,
    positions,
    providers,
    replay,
    source_trace,
    underlying,
)
from app.api.v1 import (
    settings as settings_route,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
router.include_router(alerts.router)
router.include_router(health.router)
router.include_router(performance.router)
router.include_router(positions.router)
router.include_router(providers.router)
router.include_router(replay.router)
router.include_router(settings_route.router)
router.include_router(source_trace.router)
router.include_router(underlying.router)
