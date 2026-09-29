"""Repository chat: sessions and messages with citations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import ChatRole

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.user import User


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A conversation about one repository."""

    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship()
    repository: Mapped[Repository] = relationship()
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<ChatSession {self.title!r} messages={self.message_count}>"


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One message in a chat session.

    ``citations`` holds the retrieved code locations the answer was grounded in,
    each validated against indexed ``repo_files`` before being stored.
    """

    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ChatRole] = mapped_column(enum_column(ChatRole, "chat_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    citations: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage {self.role} chars={len(self.content)}>"
