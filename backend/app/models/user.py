"""User account model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.task import Task


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A DevAgent user. Owns repositories and tasks."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bumping this invalidates every JWT minted before the change.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    repositories: Mapped[list[Repository]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", lazy="selectin"
    )
    tasks: Mapped[list[Task]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return self.display_name

    @property
    def username(self) -> str:
        return self.display_name or self.email.split("@")[0]

    @property
    def is_superuser(self) -> bool:
        return self.is_admin

    @property
    def role(self) -> str:
        return "admin" if self.is_admin else "developer"

    def __repr__(self) -> str:
        return f"<User {self.email}>"
