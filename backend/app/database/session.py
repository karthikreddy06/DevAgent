"""Async engine and session management.

The engine is created lazily so that importing the app (or running unit tests)
never opens a database connection. :func:`session_scope` is the preferred way to
get a session outside of a request; :func:`get_db` is the FastAPI dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Build a new async engine from settings."""
    resolved = settings or get_settings()
    return create_async_engine(
        resolved.database_url,
        echo=resolved.db_echo,
        pool_size=resolved.database_pool_size,
        max_overflow=resolved.database_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


def init_engine(settings: Settings | None = None, *, force: bool = False) -> AsyncEngine:
    """Initialise the process-wide engine (idempotent)."""
    global _engine, _session_factory
    if _engine is None or force:
        _engine = create_engine(settings)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_engine() -> AsyncEngine:
    """Return the engine, creating it on first use."""
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, creating it on first use."""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


async def dispose_engine() -> None:
    """Close pooled connections (shutdown and tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session context manager: commits on success, rolls back on failure."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    The session is *not* committed automatically: routes commit explicitly so
    that the transaction boundary is visible in the handler.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping(settings: Settings | None = None) -> tuple[bool, str]:
    """Cheap readiness probe. Returns ``(ok, detail)`` and never raises."""
    resolved = settings or get_settings()
    try:
        engine = get_engine() if settings is None else create_engine(resolved)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        if settings is not None:
            await engine.dispose()
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def session_kwargs() -> dict[str, Any]:
    """Extra kwargs used when constructing sessions in tests."""
    return {"expire_on_commit": False}
