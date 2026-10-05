"""Authentication and user profile endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_auth_service, get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserRead,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _safe_user_read(user: User) -> UserRead:
    """Convert a User model to UserRead safely, filling in any missing timestamps."""
    created = getattr(user, "created_at", None)
    if created is None:
        created = datetime.now(UTC)
    return UserRead(
        id=user.id,
        email=user.email,
        display_name=getattr(user, "display_name", ""),
        full_name=getattr(user, "full_name", getattr(user, "display_name", "")),
        username=getattr(user, "username", user.email.split("@")[0]),
        role=getattr(user, "role", "developer"),
        is_active=user.is_active,
        is_admin=getattr(user, "is_admin", False),
        is_superuser=getattr(user, "is_superuser", False),
        created_at=created,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    req: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    _, tokens = await service.register(req)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=int(service.issuer.access_ttl.total_seconds()),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    _, tokens = await service.login(req)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=int(service.issuer.access_ttl.total_seconds()),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    req: RefreshTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    tokens = await service.refresh_tokens(req.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=int(service.issuer.access_ttl.total_seconds()),
    )


@router.get("/me", response_model=UserRead)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return _safe_user_read(current_user)
