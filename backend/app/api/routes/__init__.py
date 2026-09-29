"""Aggregation of all API routers under the /api prefix."""

from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.changes import router as changes_router
from app.api.routes.chats import router as chats_router
from app.api.routes.health import router as health_router
from app.api.routes.repositories import router as repositories_router
from app.api.routes.tasks import router as tasks_router

api_router = APIRouter()

# Mount direct routes (e.g. /api/auth, /api/healthz)
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(repositories_router)
api_router.include_router(tasks_router)
api_router.include_router(changes_router)
api_router.include_router(chats_router)

# Mount versioned routes (e.g. /api/v1/auth, /api/v1/tasks)
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(repositories_router)
v1_router.include_router(tasks_router)
v1_router.include_router(changes_router)
v1_router.include_router(chats_router)

api_router.include_router(v1_router)

__all__ = ["api_router"]
