"""Health check and public system configuration endpoints."""

from __future__ import annotations

import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/healthz")
@router.get("/health")
@router.get("/v1/health")
async def healthz(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    """Liveness probe used by Docker Compose, Kubernetes, and UI."""
    return {"status": "ok", "app": settings.app_name, "env": settings.env, "version": "0.1.0"}


@router.get("/readyz", response_model=HealthResponse)
async def readyz(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Readiness probe that checks connectivity to Postgres and Redis."""
    from app.database.session import ping as db_ping

    db_ok, _ = await db_ping(settings)

    redis_ok = False
    with contextlib.suppress(Exception):
        from arq.connections import RedisSettings, create_pool

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.ping()
        await pool.close()
        redis_ok = True

    db_status = "connected" if db_ok else "unreachable"
    redis_status = "connected" if redis_ok else "unreachable"
    overall = "ok" if (db_ok and redis_ok) else ("degraded" if db_ok else "unhealthy")

    return HealthResponse(
        status=overall,
        version="0.1.0",
        database=db_status,
        redis=redis_status,
        env=settings.env,
    )


@router.get("/config")
async def public_config(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Expose non-sensitive runtime configuration to the frontend."""
    return settings.public_config()
