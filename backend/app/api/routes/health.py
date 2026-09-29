"""Health check and public system configuration endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


@router.get("/healthz")
@router.get("/health")
@router.get("/v1/health")
async def healthz(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    """Liveness probe used by Docker Compose, Kubernetes, and UI."""
    return {"status": "ok", "app": settings.app_name, "env": settings.env, "version": "0.1.0"}


@router.get("/config")
async def public_config(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Expose non-sensitive runtime configuration to the frontend."""
    return settings.public_config()
