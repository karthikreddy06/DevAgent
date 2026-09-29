"""Authentication request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, description="User email address")
    password: str = Field(min_length=6, description="Minimum 6 characters")
    full_name: str | None = None
    username: str | None = None

    @property
    def name(self) -> str:
        return self.username or self.full_name or self.email.split("@")[0]


class LoginRequest(BaseModel):
    email: str | None = None
    username: str | None = None
    password: str

    @property
    def identifier(self) -> str:
        return self.email or self.username or ""


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str = ""
    token_type: str = "Bearer"  # noqa: S105
    expires_in: int = 3600


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    email: str
    display_name: str = ""
    full_name: str = ""
    username: str = ""
    role: str = "developer"
    is_active: bool = True
    is_admin: bool = False
    is_superuser: bool = False
    created_at: datetime | None = None


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=10)
