"""POC #4: Apply approved change, run sandbox verification tests, and audit results."""

from __future__ import annotations

import asyncio
import uuid
import httpx
from sqlalchemy import select
from app.core.config import get_settings
from app.core.security import TokenIssuer
from app.database.session import get_session_factory
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import TaskStatus
from app.models.sandbox import SandboxRun
from app.models.testing import TestRun
from app.models.repository import Repository
from app.models.task import Task, TaskEvent
from app.models.user import User


async def run_poc4_apply() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    approval_id = uuid.UUID("01a0e7a0-9996-7d93-8ab9-712efae624c1")

    print("=" * 70)
    print("DEVAGENT POC #4: APPLY APPROVED CHANGE & SANDBOX TEST VERIFICATION")
    print("=" * 70)

    # 1. Get Approval Record and Task ID
    async with session_factory() as session:
        appr_res = await session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        approval = appr_res.scalar_one_or_none()
        assert approval is not None, f"Approval {approval_id} not found!"
        task_id = approval.task_id
        print(f"Target Approval: ID={approval.id}, Task ID={task_id}, Decision={approval.decision}")

        user_res = await session.execute(
            select(User).where(User.email == "karthikreddy251204@gmail.com")
        )
        user = user_res.scalar_one()
        issuer = TokenIssuer.from_settings(settings)
        access_token = issuer.issue_pair(
            user_id=user.id, token_version=user.token_version
        ).access_token

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # 2. Submit APPROVED Decision
    if approval.decision != "APPROVED":
        print(f"\n--- STEP 1: SUBMIT APPROVED DECISION FOR APPROVAL {approval_id} ---")
        async with httpx.AsyncClient(base_url="http://backend:8000", headers=headers, timeout=180.0) as client:
            decide_payload = {
                "decision": "APPROVED",
                "notes": "Approved by user for application and sandbox verification",
            }
            res = await client.post(f"/api/approvals/{approval_id}/decide", json=decide_payload)
            assert res.status_code == 200, f"Approval decision failed: {res.text}"
            appr_data = res.json()
            print(f"Approval Result: Decision={appr_data['decision']}, DecidedBy={appr_data['decided_by']}")
    else:
        print(f"\nApproval {approval_id} already decided as APPROVED. Re-running verification tests in sandbox with updated regex...")
        from app.tools.docker.runner import DockerSandboxExecutor
        from app.services.test_service import TestService
        from pathlib import Path
        async with session_factory() as session:
            t_obj = await session.get(Task, task_id)
            repo_id = t_obj.repository_id
        workspace = Path(f"/data/workspaces/{repo_id}")
        sandbox = DockerSandboxExecutor(task_id=str(task_id), workspace=workspace, settings=settings)
        await sandbox.start()
        try:
            async with session_factory() as session:
                ts = TestService(session, settings)
                await ts.run_tests(task_id, ["pytest", "-v"], sandbox, phase="verification")
        finally:
            await sandbox.destroy()

    # 3. Audit Task & Execution Records in Database
    print("\n--- STEP 2: AUDIT DATABASE RECORDS AFTER APPLY & TEST ---")
    async with session_factory() as session:
        # Task
        t = await session.get(Task, task_id)
        print(f"Task ID: {t.id}")
        print(f"Final Status: {t.status.value}")
        print(f"Summary: {t.summary}")
        assert t.status == TaskStatus.COMPLETED, f"Expected Task COMPLETED, got {t.status.value}"

        # TaskEvents
        events_res = await session.execute(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.seq.asc())
        )
        events = events_res.scalars().all()
        print(f"\nTask Events ({len(events)}):")
        for ev in events:
            print(f"  Seq {ev.seq}: {ev.event_type} -> {ev.message}")

        # ProposedChange & ChangeFiles
        prop_res = await session.execute(
            select(ProposedChange).where(ProposedChange.task_id == task_id)
        )
        proposal = prop_res.scalar_one()
        print(f"\nProposedChange: ID={proposal.id}, Status={proposal.status.value}")

        cf_res = await session.execute(
            select(ChangeFile).where(ChangeFile.proposed_change_id == proposal.id)
        )
        change_files = cf_res.scalars().all()
        print(f"ChangeFiles ({len(change_files)}):")
        for cf in change_files:
            print(f"  - Path: {cf.path}, Type: {cf.change_type.value}, Applied: {cf.applied}")
            assert cf.applied is True, f"File {cf.path} was not marked applied!"

        # SandboxRun
        sb_res = await session.execute(
            select(SandboxRun).where(SandboxRun.task_id == task_id)
        )
        sandbox_runs = sb_res.scalars().all()
        print(f"\nSandboxRuns ({len(sandbox_runs)}):")
        for sb in sandbox_runs:
            print(f"  - Container: {sb.container_id[:12]}, Command: {sb.command}, Exit: {sb.exit_code}, Status: {sb.status.value}")

        # TestRun
        tr_res = await session.execute(
            select(TestRun).where(TestRun.task_id == task_id).order_by(TestRun.created_at.desc())
        )
        test_runs = tr_res.scalars().all()
        print(f"\nTestRuns ({len(test_runs)}):")
        for tr in test_runs:
            print(f"  - Phase: {tr.phase}, Command: {tr.command}, All Passed: {tr.all_passed}")
            print(f"  - Summary: {tr.summary}")
            print(f"  - Passed: {tr.passed}, Failed: {tr.failed}, Errors: {tr.errors}")
        
        latest_tr = test_runs[0]
        print(f"\nLatest TestRun Verified: {latest_tr.summary}")
        assert latest_tr.all_passed is True, "Expected all tests to pass!"
        assert latest_tr.passed == 7, f"Expected 7 passed tests, got {latest_tr.passed}"
        
        t.summary = f"All {latest_tr.passed} tests passed. Fix successfully verified in sandbox."
        await session.commit()

    # 4. Verify Files on Disk in Workspace
    print("\n--- STEP 3: WORKSPACE FILE INTEGRITY VERIFICATION ---")
    repo_service = session_factory()
    workspace_path = f"/data/workspaces/{t.repository_id}"
    print(f"Checking workspace: {workspace_path}")

    import subprocess
    proc = subprocess.run(["git", "-C", workspace_path, "status", "--short"], capture_output=True, text=True)
    print("Git status in workspace:\n" + proc.stdout)

    print("\n" + "=" * 70)
    print("POC #4 END-TO-END VERIFICATION COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_poc4_apply())
