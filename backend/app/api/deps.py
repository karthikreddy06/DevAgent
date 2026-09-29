"""FastAPI dependency injection providers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import UnauthenticatedError
from app.core.security import TokenClaims, TokenIssuer
from app.database.session import get_session_factory
from app.llm.base import LLMProvider
from app.llm.factory import build_llm_provider
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.change_service import ChangeService
from app.services.chat_service import ChatService
from app.services.repo_service import RepoService
from app.services.task_service import TaskService
from app.services.test_service import TestService


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a transactional SQLAlchemy async session."""
    session_maker = get_session_factory()
    async with session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_token_issuer(settings: Annotated[Settings, Depends(get_settings)]) -> TokenIssuer:
    return TokenIssuer.from_settings(settings)


def get_llm(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    return build_llm_provider(settings)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Extract and validate JWT Bearer token, returning the authenticated User."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims: TokenClaims = issuer.decode(token, expected_type="access")
    except UnauthenticatedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = uuid.UUID(claims.subject)
    auth_service = AuthService(db)
    try:
        user = await auth_service.get_user_by_id(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or revoked",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled")

    if claims.token_version < user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_auth_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(db)


def get_repo_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RepoService:
    return RepoService(db)


def get_task_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TaskService:
    return TaskService(db)


def get_change_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ChangeService:
    return ChangeService(db)


def get_chat_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LLMProvider, Depends(get_llm)],
) -> ChatService:
    return ChatService(db, llm)


def get_test_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TestService:
    return TestService(db)
