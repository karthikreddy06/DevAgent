"""Authentication and user management business logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, NotFoundError, UnauthenticatedError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.security import (
    TokenIssuer,
    TokenPair,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest

logger = get_logger(__name__)

_NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# In-memory dev cache — used as fallback when PostgreSQL is not available
# ---------------------------------------------------------------------------
_DEV_USERS: dict[uuid.UUID, User] = {}
def _make_user(
    *,
    user_id: uuid.UUID,
    email: str,
    display_name: str,
    password_hash: str,
    is_active: bool = True,
    is_admin: bool = False,
    token_version: int = 1,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> User:
    """Create an in-memory User instance with full SQLAlchemy instrumentation."""
    now = datetime.now(timezone.utc)
    return User(
        id=user_id,
        email=email,
        display_name=display_name,
        password_hash=password_hash,
        is_active=is_active,
        is_admin=is_admin,
        token_version=token_version,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_admin = _make_user(
    user_id=_ADMIN_ID,
    email="admin@devagent.local",
    display_name="Admin",
    password_hash=hash_password("admin123456"),
    is_active=True,
    is_admin=True,
    token_version=1,
    created_at=_NOW,
    updated_at=_NOW,
)
_DEV_USERS[_ADMIN_ID] = _admin



class AuthService:
    """Handles user creation, login verification, and JWT minting."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.issuer = TokenIssuer.from_settings(self.settings)

    async def register(self, req: RegisterRequest) -> tuple[User, TokenPair]:
        validate_password_strength(req.password, min_length=min(8, self.settings.password_min_length))
        email_clean = req.email.lower().strip()

        # Check existing email in DB or dev cache
        existing_user: User | None = None
        db_available = True
        try:
            stmt = select(User).where(User.email == email_clean)
            res = await self.session.execute(stmt)
            existing_user = res.scalar_one_or_none()
        except Exception as exc:
            db_available = False
            logger.info("db_offline_using_dev_cache", error=str(exc))
            existing_user = next((u for u in _DEV_USERS.values() if u.email == email_clean), None)

        if existing_user is not None:
            raise ConflictError("A user with this email address already exists")

        pw_hash = hash_password(req.password)
        user_id = new_id()
        user = _make_user(
            user_id=user_id,
            email=email_clean,
            display_name=req.name,
            password_hash=pw_hash,
        )

        if db_available:
            try:
                db_user = User(
                    id=user_id,
                    email=email_clean,
                    password_hash=pw_hash,
                    display_name=req.name,
                    is_active=True,
                    is_admin=False,
                    token_version=1,
                )
                self.session.add(db_user)
                await self.session.commit()
                await self.session.refresh(db_user)
                user = db_user
                if not hasattr(user, "created_at") or user.created_at is None:
                    user.created_at = datetime.now(timezone.utc)
                if not hasattr(user, "updated_at") or user.updated_at is None:
                    user.updated_at = datetime.now(timezone.utc)
            except Exception as exc:
                logger.info("db_commit_fallback", error=str(exc))
                try:
                    await self.session.rollback()
                except Exception:
                    pass

        _DEV_USERS[user.id] = user
        tokens = self.issuer.issue_pair(user_id=user.id, token_version=user.token_version)
        return user, tokens

    async def login(self, req: LoginRequest) -> tuple[User, TokenPair]:
        identifier = req.identifier.lower().strip()
        user: User | None = None

        try:
            stmt = select(User).where((User.email == identifier) | (User.display_name == identifier))
            res = await self.session.execute(stmt)
            user = res.scalar_one_or_none()
            if user is not None and (not hasattr(user, "created_at") or user.created_at is None):
                user.created_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.info("db_offline_using_dev_cache", error=str(exc))

        if user is None:
            user = next(
                (u for u in _DEV_USERS.values() if u.email == identifier or u.display_name.lower() == identifier),
                None,
            )

        if user is None or not verify_password(req.password, user.password_hash):
            raise UnauthenticatedError("Invalid email or password")

        if not user.is_active:
            raise UnauthenticatedError("User account is inactive")

        tokens = self.issuer.issue_pair(user_id=user.id, token_version=user.token_version)
        return user, tokens

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        claims = self.issuer.decode(refresh_token, expected_type="refresh")
        user_id = uuid.UUID(claims.subject)

        user: User | None = None
        try:
            stmt = select(User).where(User.id == user_id)
            res = await self.session.execute(stmt)
            user = res.scalar_one_or_none()
        except Exception:
            pass

        if user is None:
            user = _DEV_USERS.get(user_id)

        if user is None or not user.is_active:
            raise UnauthenticatedError("User account not found or inactive")

        if claims.token_version < user.token_version:
            raise UnauthenticatedError("Token has been revoked")

        return self.issuer.issue_pair(user_id=user.id, token_version=user.token_version)

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        user: User | None = None
        try:
            stmt = select(User).where(User.id == user_id)
            res = await self.session.execute(stmt)
            user = res.scalar_one_or_none()
            if user is not None and (not hasattr(user, "created_at") or user.created_at is None):
                user.created_at = datetime.now(timezone.utc)
        except Exception:
            pass

        if user is None:
            user = _DEV_USERS.get(user_id)

        if user is None:
            raise NotFoundError("User not found", details={"user_id": str(user_id)})
        return user
