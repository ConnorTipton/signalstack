from fastapi import APIRouter

from app.api.v1 import alerts, health, performance, positions, providers

router = APIRouter(prefix="/api/v1")
router.include_router(alerts.router)
router.include_router(health.router)
router.include_router(performance.router)
router.include_router(positions.router)
router.include_router(providers.router)
