"""Task creation, status tracking, and event history."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.models.enums import EventLevel, TaskStatus
from app.models.task import Task, TaskEvent
from app.models.user import User
from app.schemas.task import TaskCreate


class TaskService:
    """Manages Task CRUD and state progression."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def create_task(self, req: TaskCreate, creator: User) -> Task:
        plan_meta = {}
        if req.target_files:
            plan_meta["target_files"] = req.target_files
        if req.test_command:
            plan_meta["test_command"] = req.test_command


        task = Task(
            repository_id=req.repository_id,
            user_id=creator.id,
            title=req.title.strip(),
            description=req.description.strip(),
            type=req.type,
            status=TaskStatus.CREATED,
            base_branch=req.base_branch or "main",
            iteration=1,
            plan=plan_meta or None,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)

        # Initial creation event
        event = TaskEvent(
            task_id=task.id,
            seq=1,
            event_type="task_created",
            level=EventLevel.INFO,
            message=f"Task '{task.title}' created by {creator.email}",
            payload={
                "type": task.type.value,
                "base_branch": task.base_branch,
                "target_files": req.target_files or [],
                "test_command": req.test_command,
            },
        )
        self.session.add(event)
        await self.session.commit()


        return task

    async def get_task(self, task_id: uuid.UUID) -> Task:
        stmt = select(Task).where(Task.id == task_id)
        res = await self.session.execute(stmt)
        task = res.scalar_one_or_none()
        if task is None:
            raise NotFoundError("Task not found", details={"task_id": str(task_id)})
        return task

    async def list_tasks(
        self,
        repository_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> Sequence[Task]:
        stmt = select(Task)
        if repository_id:
            stmt = stmt.where(Task.repository_id == repository_id)
        if user_id:
            stmt = stmt.where(Task.user_id == user_id)
        stmt = stmt.order_by(Task.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def cancel_task(self, task_id: uuid.UUID, reason: str) -> Task:
        task = await self.get_task(task_id)
        task.status = TaskStatus.FAILED
        task.error = {"cancelled": True, "reason": reason}

        event = TaskEvent(
            task_id=task.id,
            seq=999,
            event_type="task_cancelled",
            level=EventLevel.WARNING,
            message=f"Task cancelled: {reason}",
        )
        self.session.add(event)
        await self.session.commit()
        return task

    async def list_events(self, task_id: uuid.UUID) -> Sequence[TaskEvent]:
        stmt = select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.seq.asc())
        res = await self.session.execute(stmt)
        return res.scalars().all()
