"""Code change proposals and approval endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_change_service, get_current_user
from app.models.enums import ApprovalDecision, ChangeStatus
from app.models.user import User
from app.schemas.change import (
    ApprovalDecisionRequest,
    ApprovalRead,
    ChangeItemRead,
    ChangeReviewRequest,
    ProposedChangeRead,
)
from app.services.change_service import ChangeService

router = APIRouter(tags=["changes"])


def _map_change_status(status: ChangeStatus) -> str:
    status_map = {
        ChangeStatus.AWAITING_APPROVAL: "pending",
        ChangeStatus.APPROVED: "approved",
        ChangeStatus.APPLIED: "merged",
        ChangeStatus.REJECTED: "rejected",
    }
    return status_map.get(status, "pending")


@router.get("/changes", response_model=list[ChangeItemRead])
async def list_changes(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChangeService, Depends(get_change_service)],
    task_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ChangeItemRead]:
    changes = await service.get_changes_for_task(task_id) if task_id else await service.list_all_changes()
    items: list[ChangeItemRead] = []
    for c in changes:
        c_files = await service.get_change_files(c.id)
        file_paths = [cf.path for cf in c_files] or ([c.summary] if c.summary else [])
        st = _map_change_status(c.status)
        items.append(
            ChangeItemRead(
                id=c.id,
                task_id=c.task_id,
                patch_unified=c.patch_unified or "",
                files_changed=file_paths,
                summary=c.summary,
                status=st,
                test_status="passed" if c.status == ChangeStatus.APPLIED else "pending",
                reviewed_at=c.applied_at,
                reviewed_by=None,
                created_at=c.created_at,
            )
        )
    return items


@router.get("/changes/{change_id}", response_model=ChangeItemRead)
async def get_change(
    change_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChangeService, Depends(get_change_service)],
) -> ChangeItemRead:
    c = await service.get_change(change_id)
    c_files = await service.get_change_files(c.id)
    file_paths = [cf.path for cf in c_files] or ([c.summary] if c.summary else [])
    return ChangeItemRead(
        id=c.id,
        task_id=c.task_id,
        patch_unified=c.patch_unified or "",
        files_changed=file_paths,
        summary=c.summary,
        status=_map_change_status(c.status),
        test_status="passed" if c.status == ChangeStatus.APPLIED else "pending",
        reviewed_at=c.applied_at,
        reviewed_by=None,
        created_at=c.created_at,
    )


@router.post("/changes/{change_id}/review", response_model=ChangeItemRead)
async def review_change(
    change_id: uuid.UUID,
    req: ChangeReviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChangeService, Depends(get_change_service)],
) -> ChangeItemRead:
    approval = await service.get_approval_by_change_id(change_id)
    decision = ApprovalDecision.APPROVED if req.approved else ApprovalDecision.REJECTED
    await service.decide_approval(
        approval_id=approval.id,
        decision=decision,
        decided_by=current_user,
        notes=req.reason,
    )
    return await get_change(change_id, current_user, service)


@router.get("/tasks/{task_id}/changes", response_model=list[ProposedChangeRead])
async def get_task_changes(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChangeService, Depends(get_change_service)],
) -> list[ProposedChangeRead]:
    changes = await service.get_changes_for_task(task_id)
    return [
        ProposedChangeRead(
            id=c.id,
            task_id=c.task_id,
            agent_run_id=None,
            title=c.summary,
            summary=c.summary,
            unified_diff=c.patch_unified,
            status=c.status,
            created_at=c.created_at,
            updated_at=c.updated_at,
            files=[],
        )
        for c in changes
    ]


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalRead)
@router.post("/changes/approvals/{approval_id}/decide", response_model=ApprovalRead)
async def decide_approval(
    approval_id: uuid.UUID,
    req: ApprovalDecisionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChangeService, Depends(get_change_service)],
) -> ApprovalRead:
    approval = await service.decide_approval(
        approval_id=approval_id,
        decision=req.decision,
        decided_by=current_user,
        notes=req.notes,
    )
    return ApprovalRead(
        id=approval.id,
        task_id=approval.task_id,
        change_id=approval.proposed_change_id,
        kind=approval.kind,
        decision=approval.decision,
        requested_by="DevAgent Orchestrator",
        decided_by=current_user.email,
        notes=approval.reason,
        decided_at=approval.decided_at,
        created_at=approval.created_at,
    )
