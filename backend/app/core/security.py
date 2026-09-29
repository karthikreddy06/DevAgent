"""Authentication primitives: password hashing and JWT access/refresh tokens.

* Passwords are hashed with Argon2id (via ``argon2-cffi``).
* Access and refresh tokens are JWTs signed with ``JWT_SECRET`` and carry a
  ``typ`` claim so a refresh token can never be used as an access token.
* ``token_version`` lets a password change or explicit logout invalidate every
  token minted before it, without server-side session storage.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, get_settings
from app.core.errors import UnauthenticatedError, ValidationError

TokenType = Literal["access", "refresh"]

_ISSUER: Final[str] = "devagent"

_hasher: Final[PasswordHasher] = PasswordHasher()

_PLACEHOLDER_PASSWORDS: Final[frozenset[str]] = frozenset(
    {"password", "password1", "changeme", "secret", "admin", "letmein", "devagent", "12345678"}
)


def validate_password_strength(password: str, *, min_length: int = 10) -> None:
    """Raise :class:`ValidationError` when a password is too weak."""
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"must be at least {min_length} characters")
    if password.lower() in _PLACEHOLDER_PASSWORDS:
        problems.append("is a well-known placeholder")
    if password.isalpha() or password.isdigit():
        problems.append("must mix letters and digits or symbols")
    if problems:
        raise ValidationError("Password is not acceptable", details={"problems": problems})


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time verification that never raises on malformed hashes."""
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def new_opaque_token() -> str:
    """High-entropy opaque token (used for OAuth state values and future PATs)."""
    return secrets.token_urlsafe(48)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    token_type: TokenType
    token_version: int
    jti: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class TokenIssuer:
    """Issues and validates DevAgent JWTs."""

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=7),
        issuer: str = _ISSUER,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._issuer = issuer

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TokenIssuer:
        resolved = settings or get_settings()
        return cls(
            secret=resolved.jwt_secret_value,
            algorithm=resolved.jwt_algorithm,
            access_ttl=timedelta(minutes=resolved.access_token_ttl_minutes),
            refresh_ttl=timedelta(days=resolved.refresh_token_ttl_days),
        )

    @property
    def access_ttl(self) -> timedelta:
        return self._access_ttl

    @property
    def refresh_ttl(self) -> timedelta:
        return self._refresh_ttl

    def _encode(self, *, subject: str, kind: TokenType, token_version: int, ttl: timedelta) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + ttl
        payload: dict[str, Any] = {
            "sub": subject,
            "typ": kind,
            "ver": token_version,
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "iss": self._issuer,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm), expires_at

    def issue_pair(self, *, user_id: uuid.UUID | str, token_version: int = 0) -> TokenPair:
        subject = str(user_id)
        access_token, access_expires_at = self._encode(
            subject=subject, kind="access", token_version=token_version, ttl=self._access_ttl
        )
        refresh_token, refresh_expires_at = self._encode(
            subject=subject, kind="refresh", token_version=token_version, ttl=self._refresh_ttl
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )

    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        """Validate a token and assert its type; raises UnauthenticatedError."""
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "typ", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthenticatedError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError("Invalid token") from exc

        if payload.get("typ") != expected_type:
            raise UnauthenticatedError("Invalid token type")
        try:
            return TokenClaims(
                subject=str(payload["sub"]),
                token_type=expected_type,
                token_version=int(payload.get("ver", 0)),
                jti=str(payload["jti"]),
                issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=UTC),
                expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UnauthenticatedError("Malformed token claims") from exc
