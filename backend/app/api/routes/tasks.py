"""Task creation, status inspection, and live event streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_task_service
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import EventLevel, TaskStatus
from app.models.task import Task, TaskEvent
from app.models.user import User
from app.orchestration.state_machine import validate_transition
from app.schemas.task import TaskCancelRequest, TaskCreate, TaskEventRead, TaskRead
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = get_logger(__name__)

ACTIVE_STATUSES = {
    TaskStatus.PLANNING,
    TaskStatus.ANALYZING,
    TaskStatus.INVESTIGATING,
    TaskStatus.APPLYING,
    TaskStatus.TESTING,
}

_background_tasks: set[asyncio.Task[Any]] = set()


async def _enqueue_run_task_job(task_id: uuid.UUID, wait: bool = False) -> None:
    settings = get_settings()
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis_pool = await create_pool(
            RedisSettings.from_dsn(settings.redis_url),
            default_queue_name=settings.task_queue_name(),
        )
        job = await redis_pool.enqueue_job(
            "run_task_job",
            str(task_id),
            _queue_name=settings.task_queue_name(),
        )
        if wait and job:
            await job.result(timeout=settings.task_timeout_seconds)
    except Exception as exc:
        logger.warning("enqueue_run_task_job_fallback_direct", error=str(exc))
        from app.workers.jobs.run_task import run_task_job

        if wait:
            await run_task_job({}, str(task_id))
        else:
            t = asyncio.create_task(run_task_job({}, str(task_id)))
            _background_tasks.add(t)
            t.add_done_callback(_background_tasks.discard)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    req: TaskCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: bool = Query(default=True, description="Immediately queue and launch the task"),
) -> TaskRead:
    task = await service.create_task(req, creator=current_user)

    if start:
        validate_transition(task.status, TaskStatus.PLANNING)
        task.status = TaskStatus.PLANNING
        res_seq = await db.execute(
            select(func.coalesce(func.max(TaskEvent.seq), 0)).where(TaskEvent.task_id == task.id)
        )
        next_seq = res_seq.scalar_one() + 1
        db.add(
            TaskEvent(
                task_id=task.id,
                seq=next_seq,
                event_type="status_change",
                level=EventLevel.INFO,
                message="Starting planning phase",
                payload={"new_status": "PLANNING"},
            )
        )
        await db.commit()
        await _enqueue_run_task_job(task.id, wait=False)

    await db.refresh(task)
    return TaskRead.model_validate(task)


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    repository_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[TaskRead]:
    tasks = await service.list_tasks(repository_id=repository_id, user_id=current_user.id)
    return [TaskRead.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskRead:
    task = await service.get_task(task_id)
    return TaskRead.model_validate(task)


@router.post("/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: uuid.UUID,
    req: TaskCancelRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskRead:
    task = await service.cancel_task(task_id, reason=req.reason)
    return TaskRead.model_validate(task)


@router.post("/{task_id}/run", response_model=TaskRead)
async def run_task(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    db: Annotated[AsyncSession, Depends(get_db)],
    wait: bool = Query(default=False, description="Wait for task execution synchronously before returning"),
) -> TaskRead:
    stmt = select(Task).where(Task.id == task_id).with_for_update()
    res = await db.execute(stmt)
    task = res.scalar_one_or_none()
    if task is None:
        raise NotFoundError("Task not found", details={"task_id": str(task_id)})

    if task.status in ACTIVE_STATUSES:
        raise ConflictError(
            f"Task {task_id} already has an active execution in status '{task.status.value}'",
            details={"status": task.status.value, "task_id": str(task_id)},
        )

    if task.status == TaskStatus.COMPLETED:
        raise ConflictError(
            f"Task {task_id} is completed and cannot be started again",
            details={"status": task.status.value, "task_id": str(task_id)},
        )

    if task.status in {TaskStatus.FIX_PROPOSED, TaskStatus.AWAITING_APPROVAL}:
        raise ConflictError(
            f"Task {task_id} is awaiting human approval and cannot be started again directly",
            details={"status": task.status.value, "task_id": str(task_id)},
        )

    if task.status in {TaskStatus.FAILED, TaskStatus.REJECTED}:
        raise ConflictError(
            f"Task {task_id} is in status '{task.status.value}'. Use retry instead of start.",
            details={"status": task.status.value, "task_id": str(task_id)},
        )

    validate_transition(task.status, TaskStatus.PLANNING)
    task.status = TaskStatus.PLANNING

    res_seq = await db.execute(select(func.coalesce(func.max(TaskEvent.seq), 0)).where(TaskEvent.task_id == task.id))
    next_seq = res_seq.scalar_one() + 1
    db.add(
        TaskEvent(
            task_id=task.id,
            seq=next_seq,
            event_type="status_change",
            level=EventLevel.INFO,
            message="Starting planning phase",
            payload={"new_status": "PLANNING"},
        )
    )
    await db.commit()

    await _enqueue_run_task_job(task.id, wait=wait)
    await db.refresh(task)
    return TaskRead.model_validate(task)


@router.post("/{task_id}/retry", response_model=TaskRead)
async def retry_task(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    db: Annotated[AsyncSession, Depends(get_db)],
    wait: bool = Query(default=False, description="Wait for task execution synchronously before returning"),
) -> TaskRead:
    task = await service.retry_task(task_id, current_user)
    await _enqueue_run_task_job(task.id, wait=wait)
    await db.refresh(task)
    return TaskRead.model_validate(task)


@router.get("/{task_id}/events", response_model=list[TaskEventRead])
async def list_task_events(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
) -> list[TaskEventRead]:
    events = await service.list_events(task_id)
    return [TaskEventRead.model_validate(e) for e in events]


@router.get("/{task_id}/events/stream")
async def stream_task_events(
    task_id: uuid.UUID,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> StreamingResponse:
    """Stream Server-Sent Events (SSE) for real-time task progress tracking."""

    async def event_generator() -> AsyncIterator[str]:
        last_seq = 0
        poll_count = 0
        while poll_count < 300:  # ~5 minutes max stream duration
            events = await service.list_events(task_id)
            new_events = [e for e in events if e.seq > last_seq]
            for ev in new_events:
                last_seq = max(last_seq, ev.seq)
                read_model = TaskEventRead.model_validate(ev)
                data = json.dumps(read_model.model_dump(mode="json"))
                yield f"data: {data}\n\n"

            task = await service.get_task(task_id)
            if task.status.value in ("COMPLETED", "FAILED", "REJECTED"):
                yield f"data: {json.dumps({'event_type': 'stream_done', 'task_id': str(task_id)})}\n\n"
                break

            await asyncio.sleep(1.0)
            poll_count += 1

    return StreamingResponse(event_generator(), media_type="text/event-stream")
