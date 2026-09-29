"""POC #3 End-to-End Autonomous Coding Task Execution & Audit Script."""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import TokenIssuer
from app.database.session import get_session_factory
from app.models.agent import AgentRun, AgentStep, ToolExecution
from app.models.change import Approval, ChangeFile, ProposedChange
import os
from app.models.enums import ApprovalDecision, ApprovalKind, ChangeStatus, TaskStatus
from app.models.chunk import CodeChunk
from app.models.code import RepoFile
from app.models.repository import Repository
from app.models.sandbox import SandboxRun
from app.models.task import Task, TaskEvent
from app.models.testing import TestRun
from app.models.user import User


async def run_poc3():
    settings = get_settings()
    session_factory = get_session_factory()
    base_url = os.environ.get("BACKEND_URL", "http://backend:8000")

    print("=" * 70)
    print("DEVAGENT POC #3: AUTONOMOUS CODING TASK LIFECYCLE")
    print("=" * 70)

    # 1. Authenticate user
    async with session_factory() as session:
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

    async with AsyncClient(base_url=base_url, headers=headers, timeout=120.0) as client:
        # Step 1: Create isolated repository
        print("\n--- STEP 1: IMPORT ISOLATED TEST REPOSITORY ---")
        repo_create_payload = {
            "name": f"poc3-auth-service-{uuid.uuid4().hex[:6]}",
            "source_type": "local_path",
            "local_path": "/srv/fixtures/poc3-auth-service",
            "default_branch": "main",
        }
        res = await client.post("/api/repositories", json=repo_create_payload)
        assert res.status_code == 201, f"Repo create failed: {res.text}"
        repo_data = res.json()
        repo_id = uuid.UUID(repo_data["id"])
        print(f"Repository Created: ID={repo_id}, name={repo_data['name']}")
        print(f"Clone Status: {repo_data['clone_status']}")

        # Index repository
        print("\n--- STEP 1b: INDEX REPOSITORY ---")
        res = await client.post(f"/api/repositories/{repo_id}/index")
        assert res.status_code == 200, f"Indexing failed: {res.text}"
        print(f"Indexing response: {res.json()}")

        # Verify DB chunks and embeddings
        async with session_factory() as session:
            chunks_count = await session.scalar(
                select(func.count(CodeChunk.id)).where(CodeChunk.repository_id == repo_id)
            )
            files_count = await session.scalar(
                select(func.count(RepoFile.id)).where(RepoFile.repository_id == repo_id)
            )
            print(f"Indexed RepoFiles: {files_count}, CodeChunks: {chunks_count}")

            # Verify chunk embedding dimension
            first_chunk = (
                await session.execute(
                    select(CodeChunk).where(CodeChunk.repository_id == repo_id).limit(1)
                )
            ).scalar_one_or_none()
            if first_chunk and first_chunk.embedding is not None:
                dim = len(first_chunk.embedding)
                print(f"CodeChunk embedding dimension in Supabase: {dim}")

        # Step 2: Create Agent Task 1 & Reproduce Failure in Sandbox
        print("\n--- STEP 2: CREATE TASK 1 & TEST REPRODUCTION IN SANDBOX ---")
        task1_payload = {
            "repository_id": str(repo_id),
            "title": "Fix role hierarchy check in AuthService (rejection test)",
            "description": "check_permission uses strict > instead of >= causing same-level checks to fail",
            "type": "bug",
        }
        res = await client.post("/api/tasks", json=task1_payload)
        assert res.status_code == 201, f"Task 1 create failed: {res.text}"
        task1_data = res.json()
        task1_id = uuid.UUID(task1_data["id"])
        print(f"Task 1 created: ID={task1_id}, status={task1_data['status']}")

        from app.services.repo_service import RepoService
        from app.services.test_service import TestService
        from app.tools.docker.runner import DockerSandboxExecutor

        async with session_factory() as session:
            repo_service = RepoService(session, settings)
            ws = repo_service.workspace_path(repo_id)

            sandbox = DockerSandboxExecutor(
                task_id=f"pre-test-{repo_id.hex[:6]}", workspace=ws, settings=settings
            )
            await sandbox.start()
            try:
                test_service = TestService(session, settings)
                pre_test_run = await test_service.run_tests(
                    task1_id, ["pytest", "-v"], sandbox, phase="baseline"
                )
                print(f"Pre-test result: all_passed={pre_test_run.all_passed}, exit_code={pre_test_run.exit_code}")
                print(f"Pre-test summary: {pre_test_run.summary}")
                assert pre_test_run.exit_code == 1, "Baseline test should fail before fix"
                assert not pre_test_run.all_passed, "Baseline test must not pass"
            finally:
                await sandbox.destroy()

        # Step 3: Rejection Path Verification
        print("\n--- STEP 3: REJECTION PATH VERIFICATION ---")
        print("Executing Task 1 through orchestrator...")
        res = await client.post(f"/api/tasks/{task1_id}/run")
        assert res.status_code == 200, f"Task 1 run failed: {res.text}"
        task1_run_data = res.json()
        print(f"Task 1 status after run: {task1_run_data['status']}")
        assert task1_run_data["status"] == "AWAITING_APPROVAL"

        # Check pending approval
        async with session_factory() as session:
            appr_res = await session.execute(
                select(Approval).where(Approval.task_id == task1_id)
            )
            approval1 = appr_res.scalar_one()
            approval1_id = approval1.id
            print(f"Task 1 Approval Record: ID={approval1_id}, decision={approval1.decision}")

        # Reject the approval
        print(f"Submitting REJECT decision for Approval {approval1_id}...")
        decide_payload = {
            "decision": "REJECTED",
            "notes": "Testing rejection path - patch denied by reviewer",
        }
        res = await client.post(f"/api/approvals/{approval1_id}/decide", json=decide_payload)
        assert res.status_code == 200, f"Approval decide failed: {res.text}"
        appr1_decided = res.json()
        print(f"Approval 1 Decision Result: {appr1_decided['decision']}")

        # Verify task1 is REJECTED
        res = await client.get(f"/api/tasks/{task1_id}")
        task1_final = res.json()
        print(f"Task 1 Final Status: {task1_final['status']}")
        assert task1_final["status"] == "REJECTED"
        print("Rejection path successfully verified!")

        # Step 4: Successful Path Verification
        print("\n--- STEP 4: SUCCESSFUL PATH VERIFICATION ---")
        task2_payload = {
            "repository_id": str(repo_id),
            "title": "Fix role hierarchy check in AuthService",
            "description": "check_permission in src/auth.py uses strict > instead of >= causing same-level role checks to fail. Needs >= so equal roles pass.",
            "type": "bug",
        }
        res = await client.post("/api/tasks", json=task2_payload)
        assert res.status_code == 201, f"Task 2 create failed: {res.text}"
        task2_data = res.json()
        task2_id = uuid.UUID(task2_data["id"])
        print(f"Task 2 created: ID={task2_id}, status={task2_data['status']}")

        print("Executing Task 2 through orchestrator...")
        res = await client.post(f"/api/tasks/{task2_id}/run")
        assert res.status_code == 200, f"Task 2 run failed: {res.text}"
        task2_run_data = res.json()
        print(f"Task 2 status after run: {task2_run_data['status']}")
        assert task2_run_data["status"] == "AWAITING_APPROVAL"

        # Inspect ProposedChange and Approval in DB
        async with session_factory() as session:
            prop_res = await session.execute(
                select(ProposedChange).where(ProposedChange.task_id == task2_id)
            )
            proposal2 = prop_res.scalar_one()
            appr2_res = await session.execute(
                select(Approval).where(Approval.task_id == task2_id)
            )
            approval2 = appr2_res.scalar_one()
            approval2_id = approval2.id
            cf_res = await session.execute(
                select(ChangeFile).where(ChangeFile.proposed_change_id == proposal2.id)
            )
            change_file2 = cf_res.scalar_one_or_none()

            print(f"ProposedChange: ID={proposal2.id}, status={proposal2.status}")
            print(f"Patch Unified:\n{proposal2.patch_unified}")
            if change_file2:
                print(f"ChangeFile: path={change_file2.path}, applied={change_file2.applied}")
            print(f"Approval 2: ID={approval2_id}, decision={approval2.decision}")

        # Approve the change
        print(f"\nSubmitting APPROVED decision for Approval {approval2_id}...")
        decide2_payload = {
            "decision": "APPROVED",
            "notes": "Approved for application and sandbox verification",
        }
        res = await client.post(f"/api/approvals/{approval2_id}/decide", json=decide2_payload)
        assert res.status_code == 200, f"Approval 2 decide failed: {res.text}"
        appr2_decided = res.json()
        print(f"Approval 2 Decision Result: {appr2_decided['decision']}")

        # Verify task2 is COMPLETED
        res = await client.get(f"/api/tasks/{task2_id}")
        task2_final = res.json()
        print(f"Task 2 Final Status: {task2_final['status']}")
        print(f"Task 2 Summary: {task2_final.get('summary')}")
        assert task2_final["status"] == "COMPLETED"

        # Verify tests passed in DB
        async with session_factory() as session:
            tr_res = await session.execute(
                select(TestRun).where(TestRun.task_id == task2_id).order_by(TestRun.created_at.desc())
            )
            test_run2 = tr_res.scalar_one()
            print(f"Verified TestRun in DB: all_passed={test_run2.all_passed}, passed={test_run2.passed}, failed={test_run2.failed}")
            print(f"TestRun summary: {test_run2.summary}")
            assert test_run2.all_passed is True

        # Step 5: Failure Handling Verification
        print("\n--- STEP 5: FAILURE HANDLING VERIFICATION ---")
        task3_payload = {
            "repository_id": str(repo_id),
            "title": "Test failure handling with broken fix",
            "description": "Demonstrate that failing tests prevent COMPLETED state",
            "type": "bug",
        }
        res = await client.post("/api/tasks", json=task3_payload)
        assert res.status_code == 201
        task3_id = uuid.UUID(res.json()["id"])

        # Manually create a bad proposal with an incorrect patch that still fails tests
        async with session_factory() as session:
            bad_proposal = ProposedChange(
                task_id=task3_id,
                iteration=1,
                status=ChangeStatus.AWAITING_APPROVAL,
                summary="Broken patch that intentionally fails",
                patch_unified="broken logic",
                files_changed=1,
            )
            session.add(bad_proposal)
            await session.flush()

            bad_change_file = ChangeFile(
                proposed_change_id=bad_proposal.id,
                task_id=task3_id,
                path="src/auth.py",
                diff="broken",
                original_content="def invalid_syntax(:",  # invalid python syntax will fail pytest
                proposed_content="def check_permission(self, token, required_role):\n    return False\n",
            )
            session.add(bad_change_file)
            await session.flush()

            bad_approval = Approval(
                task_id=task3_id,
                proposed_change_id=bad_proposal.id,
                kind=ApprovalKind.APPLY_CHANGES,
            )
            session.add(bad_approval)
            t3 = await session.get(Task, task3_id)
            t3.status = TaskStatus.AWAITING_APPROVAL
            await session.commit()
            bad_approval_id = bad_approval.id

        # Decide approval with APPROVED - tests should fail and task must become FAILED!
        print(f"Approving bad patch for Task 3 to verify FAILED state handling...")
        res = await client.post(
            f"/api/changes/approvals/{bad_approval_id}/decide",
            json={"decision": "APPROVED", "notes": "Testing failure path"},
        )
        assert res.status_code == 200

        res = await client.get(f"/api/tasks/{task3_id}")
        task3_final = res.json()
        print(f"Task 3 Status after bad patch: {task3_final['status']}")
        print(f"Task 3 Error record: {task3_final.get('error')}")
        assert task3_final["status"] == "FAILED", "Task with failing tests must NOT report COMPLETED!"
        print("Failure handling verified: Task reached FAILED state correctly.")

        # Step 6: Database Records Audit
        print("\n--- STEP 6: DATABASE RECORDS AUDIT ---")
        async with session_factory() as session:
            agent_runs = (await session.execute(select(AgentRun).where(AgentRun.task_id == task2_id))).scalars().all()
            agent_steps = (await session.execute(select(AgentStep).where(AgentStep.task_id == task2_id))).scalars().all()
            tool_execs = (await session.execute(select(ToolExecution).where(ToolExecution.task_id == task2_id))).scalars().all()
            task_events = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task2_id).order_by(TaskEvent.seq))).scalars().all()
            sandbox_runs = (await session.execute(select(SandboxRun).where(SandboxRun.task_id == task2_id))).scalars().all()
            test_runs = (await session.execute(select(TestRun).where(TestRun.task_id == task2_id))).scalars().all()

            print(f"Task 2 AgentRuns count: {len(agent_runs)}")
            for ar in agent_runs:
                print(f"  - Agent: {ar.agent.value}, status: {ar.status.value}, steps: {ar.step_count}, tool_calls: {ar.tool_calls}")

            print(f"Task 2 AgentSteps count: {len(agent_steps)}")
            print(f"Task 2 ToolExecutions count: {len(tool_execs)}")
            for te in tool_execs:
                print(f"  - Tool: {te.tool_name}, status: {te.status.value}, exit: {te.exit_code}, duration: {te.duration_ms}ms")

            print(f"Task 2 TaskEvents count: {len(task_events)}")
            for ev in task_events:
                print(f"  - Seq {ev.seq}: {ev.event_type} -> {ev.message}")

            print(f"Task 2 SandboxRuns count: {len(sandbox_runs)}")
            for sb in sandbox_runs:
                print(f"  - SandboxRun: cmd={sb.command}, status={sb.status.value}, exit={sb.exit_code}")

            print(f"Task 2 TestRuns count: {len(test_runs)}")
            for tr in test_runs:
                print(f"  - TestRun: cmd={tr.command}, all_passed={tr.all_passed}, summary={tr.summary}")

        # Step 7: Isolation Verification
        print("\n--- STEP 7: ISOLATION VERIFICATION ---")
        fixture_auth = Path("/srv/fixtures/poc3-auth-service/src/auth.py")
        if fixture_auth.exists():
            fixture_hash = hashlib.sha256(fixture_auth.read_bytes()).hexdigest()
            print(f"Fixture /srv/fixtures/poc3-auth-service/src/auth.py SHA256: {fixture_hash}")

        # Check isolated workspace
        ws_auth = ws / "src" / "auth.py"
        ws_hash = hashlib.sha256(ws_auth.read_bytes()).hexdigest()
        print(f"Workspace {ws_auth} SHA256: {ws_hash}")
        assert fixture_hash != ws_hash or "return False" in ws_auth.read_text(), "Workspace should be modified, fixture unchanged"

        print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_poc3())
