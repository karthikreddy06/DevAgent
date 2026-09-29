"""Interactive chat and discussion endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_chat_service, get_current_user
from app.models.user import User
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageRead,
    ChatSessionCreate,
    ChatSessionRead,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    req: ChatSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionRead:
    session = await service.create_session(req, user=current_user)
    return ChatSessionRead.model_validate(session)


@router.get("", response_model=list[ChatSessionRead])
async def list_chat_sessions(
    repository_id: Annotated[uuid.UUID, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> list[ChatSessionRead]:
    sessions = await service.list_sessions(repository_id=repository_id, user_id=current_user.id)
    return [ChatSessionRead.model_validate(s) for s in sessions]


@router.get("/{session_id}", response_model=ChatSessionRead)
async def get_chat_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionRead:
    session = await service.get_session(session_id)
    return ChatSessionRead.model_validate(session)


@router.post("/{session_id}/messages", response_model=ChatMessageRead)
async def send_chat_message(
    session_id: uuid.UUID,
    req: ChatMessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatMessageRead:
    msg = await service.send_message(session_id, req)
    return ChatMessageRead.model_validate(msg)
