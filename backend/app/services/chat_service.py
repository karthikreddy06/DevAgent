"""Chat session management and context-aware LLM query answering."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.llm.base import LLMMessage, LLMProvider
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatRole
from app.models.user import User
from app.retrieval.hybrid import HybridRetriever
from app.schemas.chat import ChatMessageCreate, ChatSessionCreate


class ChatService:
    """Manages conversational sessions and LLM retrieval-augmented dialogue."""

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.settings = settings or get_settings()

    async def create_session(self, req: ChatSessionCreate, user: User) -> ChatSession:
        chat_sess = ChatSession(
            repository_id=req.repository_id,
            user_id=user.id,
            task_id=req.task_id,
            title=req.title,
        )
        self.session.add(chat_sess)
        await self.session.commit()
        await self.session.refresh(chat_sess)
        return chat_sess

    async def get_session(self, session_id: uuid.UUID) -> ChatSession:
        stmt = select(ChatSession).where(ChatSession.id == session_id).options(selectinload(ChatSession.messages))
        res = await self.session.execute(stmt)
        chat_sess = res.scalar_one_or_none()
        if chat_sess is None:
            raise NotFoundError("Chat session not found", details={"session_id": str(session_id)})
        return chat_sess

    async def list_sessions(self, repository_id: uuid.UUID, user_id: uuid.UUID) -> Sequence[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.repository_id == repository_id, ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def send_message(self, session_id: uuid.UUID, req: ChatMessageCreate) -> ChatMessage:
        chat_sess = await self.get_session(session_id)

        user_msg = ChatMessage(
            session_id=chat_sess.id,
            role=ChatRole.USER,
            content=req.content.strip(),
        )
        self.session.add(user_msg)
        await self.session.commit()

        # Hybrid retrieval for codebase context
        retriever = HybridRetriever(repository_id=chat_sess.repository_id, session=self.session)
        hits = await retriever.search(req.content, top_k=5)

        context_blocks = []
        citations = []
        for h in hits:
            ref = f"{h.path}:{h.start_line}-{h.end_line}"
            citations.append(ref)
            context_blocks.append(f"--- File: {ref} ---\n{h.content}")

        context_text = "\n\n".join(context_blocks)
        sys_prompt = (
            "You are DevAgent AI assistant. Answer the user's questions about the codebase accurately. "
            "Use the provided code context if relevant.\n\n"
            f"RELEVANT CODEBASE CONTEXT:\n{context_text}"
        )

        messages = [
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=req.content),
        ]

        response = await self.llm.complete(messages)

        asst_msg = ChatMessage(
            session_id=chat_sess.id,
            role=ChatRole.ASSISTANT,
            content=response.text,
            citations=citations if citations else None,
        )
        self.session.add(asst_msg)
        await self.session.commit()
        await self.session.refresh(asst_msg)

        return asst_msg
