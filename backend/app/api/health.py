"""
Health check endpoint.

GET /healthz — used by load balancers, Docker health checks, and smoke tests
to confirm the service is alive and responding.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    env: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api-pilot-backend",
        version="0.0.1",
        env=settings.app_env,
    )
