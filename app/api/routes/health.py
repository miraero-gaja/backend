"""Process-liveness endpoint independent of optional external services."""

from fastapi import APIRouter

from app.api.schemas import HealthResponse, Utf8JSONResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, response_class=Utf8JSONResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")

