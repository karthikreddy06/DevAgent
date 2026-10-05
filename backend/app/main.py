"""FastAPI application entry point for DevAgent."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.errors import DevAgentError
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_directories()
    logger.info("app_started", app_name=settings.app_name, env=settings.env)
    yield
    from app.database.session import dispose_engine

    await dispose_engine()
    logger.info("app_stopped")


app = FastAPI(
    title="DevAgent API",
    description="Autonomous software engineering agent API",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

settings = get_settings()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = trace_id
    return response


@app.exception_handler(DevAgentError)
async def devagent_error_handler(request: Request, exc: DevAgentError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_payload(trace_id=trace_id),
    )


# Mount all API routes under /api
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/healthz"}
