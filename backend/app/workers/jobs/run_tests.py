"""Background job for running test suites in sandbox."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_session_factory
from app.services.test_service import TestService

logger = get_logger(__name__)


async def run_tests_job(ctx: dict[str, Any], task_id: str, command: list[str]) -> bool:
    """Arq background job executing sandboxed test suites."""
    settings = get_settings()
    session_factory = get_session_factory()
    task_uuid = uuid.UUID(task_id)
    sandbox = ctx.get("sandbox")

    if not sandbox:
        logger.error("sandbox_missing_in_worker_ctx", task_id=task_id)
        return False

    async with session_factory() as session:
        test_service = TestService(session, settings)
        test_run = await test_service.run_tests(task_uuid, command, sandbox)
        logger.info("run_tests_job_completed", task_id=task_id, all_passed=test_run.all_passed)
        return test_run.all_passed
