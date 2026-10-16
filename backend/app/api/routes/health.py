"""
DataJanitor — Health-check route.

GET /health  →  confirms the server is running.

This is the first route registered; later phases will add routers for
uploads, scans, repairs, etc.
"""

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns application status, name, version, and environment.",
)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        app_name=settings.app_name,
        version=settings.version,
        environment=settings.app_env,
    )
