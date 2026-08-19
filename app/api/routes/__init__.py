"""Route collection for the public HTTP surface."""

from fastapi import APIRouter

from app.api.routes.answer import router as answer_router
from app.api.routes.health import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(answer_router)

__all__ = ["router"]

