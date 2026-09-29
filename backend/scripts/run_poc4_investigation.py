"""POC #4: Real-repository investigation and proposal formulation for elective-recommendation-system.

Stops at AWAITING_APPROVAL and preserves the human approval gate.
"""

from __future__ import annotations

import asyncio
import json
import uuid
import httpx
from sqlalchemy import select
from app.core.config import get_settings
from app.database.session import get_session_factory
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import TaskStatus
from app.models.repository import Repository
from app.models.agent import AgentRun, AgentStep
from app.models.task import Task, TaskEvent
from app.models.user import User
from app.core.security import TokenIssuer
from app.retrieval.hybrid import HybridRetriever
from app.llm.factory import build_embedding_provider


async def run_poc4_investigation() -> None:
    settings = get_settings()
    session_factory = get_session_factory()

    print("=" * 70)
    print("DEVAGENT POC #4: INVESTIGATION & PROPOSAL FOR ELECTIVE RECOMMENDATION SYSTEM")
    print("=" * 70)

    # 1. Verify Repository
    repo_name = "elective-recommendation-system"
    async with session_factory() as session:
        res = await session.execute(
            select(Repository).where(Repository.name == repo_name)
        )
        repo = res.scalar_one_or_none()
        assert repo is not None, f"Repository {repo_name} not found in database!"
        repo_id = repo.id
        print(f"\nTarget Repository: ID={repo_id}, name={repo.name}, clone_status={repo.clone_status}")

    # 2. Perform RAG / Hybrid Retrieval Investigation
    print("\n--- STEP 1: RAG & HYBRID RETRIEVAL INVESTIGATION ---")
    query = "FastAPI predict endpoint academic score interest rating validation StudentProfile"
    async with session_factory() as session:
        embedder = build_embedding_provider(settings)
        retriever = HybridRetriever(repository_id=repo_id, session=session, embedding_provider=embedder, settings=settings)
        hits = await retriever.search(query=query, top_k=5)
        print(f"Retrieved {len(hits)} relevant code hits for query: '{query}'")
        for i, hit in enumerate(hits, 1):
            print(f"\n[Hit {i}] File: {hit.path} (Lines {hit.start_line}-{hit.end_line})")
            print(f"Score: {hit.score:.4f}")
            preview = hit.content[:200].replace('\n', ' ')
            print(f"Content preview: {preview}...")

    # 3. Create Agent Task
    print("\n--- STEP 2: CREATE AGENT TASK ---")
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

    async with httpx.AsyncClient(base_url="http://backend:8000", headers=headers, timeout=120.0) as client:

        task_payload = {
            "repository_id": str(repo_id),
            "title": "Add robust validation to the FastAPI /api/predict endpoint and test suite",
            "description": (
                "Add robust validation to the FastAPI /api/predict endpoint: academic scores must be between 0 and 100, "
                "interest ratings must be between 1 and 5, invalid inputs must produce HTTP 422, valid prediction behavior "
                "must remain unchanged, and add comprehensive pytest tests covering all validation cases."
            ),
            "type": "feature",
        }
        res = await client.post("/api/tasks", json=task_payload)
        assert res.status_code == 201, f"Task creation failed: {res.text}"
        task_data = res.json()
        task_id = uuid.UUID(task_data["id"])
        print(f"Task created: ID={task_id}, status={task_data['status']}")

        # 4. Run Task through Orchestrator (stops at AWAITING_APPROVAL)
        print("\n--- STEP 3: RUN AGENT ORCHESTRATION ---")
        print("Executing task through planner, codebase and debugger agents...")
        res = await client.post(f"/api/tasks/{task_id}/run")
        assert res.status_code == 200, f"Task run failed: {res.text}"
        task_run_data = res.json()
        print(f"Task status after orchestration run: {task_run_data['status']}")
        assert task_run_data["status"] == "AWAITING_APPROVAL", f"Expected AWAITING_APPROVAL, got {task_run_data['status']}"

    # 5. Database Audit at Approval Gate
    print("\n--- STEP 4: DATABASE AUDIT AT AWAITING_APPROVAL GATE ---")
    async with session_factory() as session:
        # Task & State Machine
        t = await session.get(Task, task_id)
        print(f"Task: ID={t.id}, Status={t.status.value}, Iteration={t.iteration}")

        # TaskEvents
        events_res = await session.execute(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.seq.asc())
        )
        events = events_res.scalars().all()
        print(f"\nTask Events ({len(events)}):")
        for ev in events:
            print(f"  Seq {ev.seq}: {ev.event_type} -> {ev.message}")

        # AgentRuns
        runs_res = await session.execute(
            select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.created_at.asc())
        )
        runs = runs_res.scalars().all()
        print(f"\nAgent Runs ({len(runs)}):")
        for r in runs:
            print(f"  Agent: {r.agent.value}, status: {r.status.value}, steps: {r.step_count}")

        # ProposedChange & ChangeFiles
        prop_res = await session.execute(
            select(ProposedChange).where(ProposedChange.task_id == task_id)
        )
        proposal = prop_res.scalar_one_or_none()
        assert proposal is not None, "ProposedChange record missing!"
        print(f"\nProposed Change: ID={proposal.id}, Status={proposal.status.value}")
        print(f"Files Changed: {proposal.files_changed}")

        cf_res = await session.execute(
            select(ChangeFile).where(ChangeFile.proposed_change_id == proposal.id)
        )
        change_files = cf_res.scalars().all()
        print(f"Change Files ({len(change_files)}):")
        for cf in change_files:
            print(f"  - Path: {cf.path}, Type: {cf.change_type.value}, Applied: {cf.applied}")

        print("\nUnified Diff:\n" + ("=" * 50))
        print(proposal.patch_unified)
        print("=" * 50)

        # Approval
        appr_res = await session.execute(
            select(Approval).where(Approval.task_id == task_id)
        )
        approval = appr_res.scalar_one_or_none()
        assert approval is not None, "Approval record missing!"
        print(f"\nPending Approval: ID={approval.id}, Decision={approval.decision}, Kind={approval.kind.value}")

    print("\n" + "=" * 70)
    print("SUCCESSFULLY STOPPED AT AWAITING_APPROVAL GATE.")
    print("NO CHANGES HAVE BEEN APPLIED. AWAITING EXPLICIT HUMAN APPROVAL.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_poc4_investigation())
