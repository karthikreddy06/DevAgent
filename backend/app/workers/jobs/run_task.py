"""Background job for running the agent orchestration loop on a task."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_session_factory
from app.llm.factory import build_llm_provider
from app.orchestration.orchestrator import TaskOrchestrator
from app.services.repo_service import RepoService
from app.services.task_service import TaskService
from app.tools import create_default_registry

logger = get_logger(__name__)


async def run_task_job(ctx: dict[str, Any], task_id: str) -> str:
    """Arq background job running end-to-end task execution."""
    settings = get_settings()
    session_factory = get_session_factory()
    task_uuid = uuid.UUID(task_id)

    async with session_factory() as session:
        task_service = TaskService(session, settings)
        task = await task_service.get_task(task_uuid)

        repo_service = RepoService(session, settings)
        repo = await repo_service.get_repository(task.repository_id)
        workspace = repo_service.workspace_path(repo.id)

        llm = build_llm_provider(settings)
        registry = create_default_registry()

        sandbox = ctx.get("sandbox")
        cleanup_sandbox = False
        if sandbox is None and settings.sandbox_enabled:
            from app.tools.docker.runner import DockerSandboxExecutor

            sandbox = DockerSandboxExecutor(task_id=str(task.id), workspace=workspace, settings=settings)
            await sandbox.start()
            cleanup_sandbox = True

        try:
            orchestrator = TaskOrchestrator(
                session=session,
                llm=llm,
                registry=registry,
                settings=settings,
                sandbox=sandbox,
            )

            final_status = await orchestrator.execute_task(task, workspace)
            logger.info("run_task_job_completed", task_id=task_id, status=final_status.value)
            return final_status.value
        finally:
            if cleanup_sandbox and sandbox is not None:
                await sandbox.destroy()
