"""Chat sessions and message schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ChatRole


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1)


class ChatSessionCreate(BaseModel):
    repository_id: uuid.UUID
    task_id: uuid.UUID | None = None
    title: str = "New Chat"


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: ChatRole
    content: str
    citations: list[str] | None = None
    created_at: datetime


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    user_id: uuid.UUID
    task_id: uuid.UUID | None = None
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatStreamToken(BaseModel):
    token: str = ""
    done: bool = False
    citations: list[str] | None = None
    error: str | None = None
