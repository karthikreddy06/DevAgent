"""Proposed changes, diff inspection, and approval decisions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, PolicyViolationError, ValidationError
from app.core.logging import get_logger
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import ApprovalDecision, ChangeStatus, TaskStatus
from app.models.task import Task
from app.models.user import User

logger = get_logger(__name__)


class ChangeService:
    """Manages proposed fixes, diff reviews, and human approvals."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def get_change(self, change_id: uuid.UUID) -> ProposedChange:
        stmt = select(ProposedChange).where(ProposedChange.id == change_id)
        res = await self.session.execute(stmt)
        change = res.scalar_one_or_none()
        if change is None:
            raise NotFoundError("Proposed change not found", details={"change_id": str(change_id)})
        return change

    async def list_all_changes(self) -> Sequence[ProposedChange]:
        stmt = select(ProposedChange).order_by(ProposedChange.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_changes_for_task(self, task_id: uuid.UUID) -> Sequence[ProposedChange]:
        stmt = select(ProposedChange).where(ProposedChange.task_id == task_id).order_by(ProposedChange.iteration.desc())
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_change_files(self, change_id: uuid.UUID) -> Sequence[ChangeFile]:
        stmt = select(ChangeFile).where(ChangeFile.proposed_change_id == change_id).order_by(ChangeFile.path.asc())
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_approval_by_change_id(self, change_id: uuid.UUID) -> Approval:
        stmt = select(Approval).where(Approval.proposed_change_id == change_id).order_by(Approval.created_at.desc())
        res = await self.session.execute(stmt)
        approval = res.scalar_one_or_none()
        if approval is None:
            raise NotFoundError("Approval record for change not found", details={"change_id": str(change_id)})
        return approval

    async def get_approval(self, approval_id: uuid.UUID) -> Approval:
        stmt = select(Approval).where(Approval.id == approval_id)
        res = await self.session.execute(stmt)
        approval = res.scalar_one_or_none()
        if approval is None:
            raise NotFoundError("Approval record not found", details={"approval_id": str(approval_id)})
        return approval

    async def decide_approval(
        self,
        approval_id: uuid.UUID,
        decision: ApprovalDecision,
        decided_by: User,
        notes: str | None = None,
        workspace: Path | None = None,
        sandbox: Any = None,
    ) -> Approval:
        approval = await self.get_approval(approval_id)
        if approval.decision is not None:
            raise PolicyViolationError("Approval has already been decided")

        # Invariant checks for approval decision
        change = None
        if decision == ApprovalDecision.APPROVED:
            if not approval.proposed_change_id:
                raise ValidationError("Approval record has no associated proposed_change_id")

            c_stmt = select(ProposedChange).where(ProposedChange.id == approval.proposed_change_id)
            c_res = await self.session.execute(c_stmt)
            change = c_res.scalar_one_or_none()
            if not change:
                raise NotFoundError("Proposed change associated with approval not found")

            if not change.patch_unified or not change.patch_unified.strip():
                raise ValidationError("ProposedChange contains no valid unified diff patch")

            cf_stmt = select(ChangeFile).where(ChangeFile.proposed_change_id == change.id)
            cf_res = await self.session.execute(cf_stmt)
            change_files = cf_res.scalars().all()
            if not change_files:
                raise ValidationError("ProposedChange has no associated ChangeFile records")

            has_actual_change = any(
                cf.proposed_content is not None or (cf.diff and cf.diff.strip()) for cf in change_files
            )
            if not has_actual_change:
                raise ValidationError("ProposedChange files represent no actual code change")

            approval.decision = decision
            approval.decided_by_id = decided_by.id
            approval.decided_at = datetime.now(UTC)
            approval.reason = notes
            change.status = ChangeStatus.APPROVED

        elif decision == ApprovalDecision.REJECTED:
            approval.decision = decision
            approval.decided_by_id = decided_by.id
            approval.decided_at = datetime.now(UTC)
            approval.reason = notes

            if approval.proposed_change_id:
                c_stmt = select(ProposedChange).where(ProposedChange.id == approval.proposed_change_id)
                c_res = await self.session.execute(c_stmt)
                change = c_res.scalar_one_or_none()
                if change:
                    change.status = ChangeStatus.REJECTED

        # Update task status based on decision
        t_stmt = select(Task).where(Task.id == approval.task_id)
        t_res = await self.session.execute(t_stmt)
        task = t_res.scalar_one_or_none()

        if task:
            from app.models.enums import EventLevel
            from app.models.task import TaskEvent
            from app.orchestration.state_machine import validate_transition

            if decision == ApprovalDecision.REJECTED:
                validate_transition(task.status, TaskStatus.REJECTED)
                task.status = TaskStatus.REJECTED
                task.summary = f"Proposed changes rejected by reviewer: {notes or 'No reason provided'}"
                seq_res = await self.session.execute(
                    select(func.coalesce(func.max(TaskEvent.seq), 0)).where(TaskEvent.task_id == task.id)
                )
                event = TaskEvent(
                    task_id=task.id,
                    seq=seq_res.scalar_one() + 1,
                    event_type="approval_rejected",
                    level=EventLevel.WARNING,
                    message="Proposed change rejected by reviewer",
                    payload={"notes": notes},
                )
                self.session.add(event)

            elif decision == ApprovalDecision.APPROVED:
                validate_transition(task.status, TaskStatus.APPLYING)
                task.status = TaskStatus.APPLYING
                await self.session.commit()

                # Delegate apply and test execution to the worker (holds the Docker socket)
                try:
                    from arq import create_pool
                    from arq.connections import RedisSettings

                    redis_pool = await create_pool(
                        RedisSettings.from_dsn(self.settings.redis_url),
                        default_queue_name=self.settings.task_queue_name(),
                    )
                    job = await redis_pool.enqueue_job(
                        "apply_and_test_job",
                        str(approval.id),
                        _queue_name=self.settings.task_queue_name(),
                    )
                    if job:
                        await job.result(timeout=self.settings.task_timeout_seconds)
                except Exception as exc:
                    logger.warning("enqueue_apply_and_test_fallback_direct", error=str(exc))
                    from app.workers.jobs.apply_and_test import apply_and_test_job

                    await apply_and_test_job({"sandbox": sandbox}, str(approval.id))

                await self.session.refresh(task)
                return approval

        await self.session.commit()
        return approval
