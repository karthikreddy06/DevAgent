"""Arq worker configuration, lifecycle hooks and job registry."""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.workers.jobs.apply_and_test import apply_and_test_job
from app.workers.jobs.index_repo import index_repository_job
from app.workers.jobs.run_task import run_task_job
from app.workers.jobs.run_tests import run_tests_job

configure_logging()
logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    settings.ensure_directories()
    logger.info("arq_worker_started", redis=settings.redis_url)


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("arq_worker_shutdown")


class WorkerSettings:
    """Worker configuration consumed by `arq app.workers.settings.WorkerSettings`."""

    functions = [index_repository_job, run_task_job, run_tests_job, apply_and_test_job]  # noqa: RUF012
    on_startup = startup
    on_shutdown = shutdown

    _settings = get_settings()
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    queue_name = _settings.task_queue_name()
    max_jobs = 10
    job_timeout = 1800
