"""Test execution and test report parsing service."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.enums import RunStatus
from app.models.testing import TestRun
from app.tools.base import SandboxExecutor

_PYTEST_SUMMARY_RE = re.compile(
    r"(?:(?P<passed>\d+)\s+passed)?"
    r"(?:,\s*(?P<failed>\d+)\s+failed)?"
    r"(?:,\s*(?P<errors>\d+)\s+errors?)?"
    r"(?:,\s*(?P<skipped>\d+)\s+skipped)?",
    re.IGNORECASE,
)


def parse_pytest_counts(output: str) -> tuple[int, int, int, int]:
    """Extract (passed, failed, errors, skipped) counts from pytest output."""
    passed, failed, errors, skipped = 0, 0, 0, 0
    for line in reversed(output.splitlines()):
        if "====" in line and ("passed" in line or "failed" in line or "error" in line):
            p_match = re.search(r"(\d+)\s+passed", line)
            f_match = re.search(r"(\d+)\s+failed", line)
            e_match = re.search(r"(\d+)\s+error", line)
            s_match = re.search(r"(\d+)\s+skipped", line)
            if p_match or f_match or e_match or s_match:
                passed = int(p_match.group(1)) if p_match else 0
                failed = int(f_match.group(1)) if f_match else 0
                errors = int(e_match.group(1)) if e_match else 0
                skipped = int(s_match.group(1)) if s_match else 0
                break
    return passed, failed, errors, skipped


class TestService:
    """Manages executing tests in sandbox and saving test run results."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def run_tests(
        self,
        task_id: uuid.UUID,
        command: list[str],
        sandbox: SandboxExecutor,
        iteration: int = 1,
        phase: str = "verification",
    ) -> TestRun:
        t0 = time.perf_counter()
        output = await sandbox.execute(command, purpose="Run test suite")
        duration_ms = int((time.perf_counter() - t0) * 1000)

        combined = f"{output.stdout}\n{output.stderr}"
        passed, failed, errors, skipped = parse_pytest_counts(combined)
        total = passed + failed + errors + skipped
        if total == 0 and output.exit_code == 0:
            # If pytest ran with no test count summary but exited 0
            passed = 1
            total = 1
        all_passed = output.exit_code == 0 and failed == 0 and errors == 0

        test_run = TestRun(
            task_id=task_id,
            iteration=iteration,
            framework="pytest",
            command=command,
            status=RunStatus.SUCCEEDED if all_passed else RunStatus.FAILED,
            phase=phase,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_ms=duration_ms,
            exit_code=output.exit_code,
            all_passed=all_passed,
            stdout_tail=output.stdout[-4000:],
            stderr_tail=output.stderr[-4000:],
            summary=f"{passed} passed, {failed} failed, {errors} errors out of {total} total",
        )
        from app.models.task import Task

        task_in_db = await self.session.get(Task, task_id)
        if task_in_db is not None:
            self.session.add(test_run)
            try:
                from app.models.enums import AgentName
                from app.models.sandbox import SandboxRun

                sandbox_run = SandboxRun(
                    task_id=task_id,
                    agent=AgentName.TESTER,
                    purpose="pytest test suite",
                    image=getattr(sandbox, "_image", self.settings.sandbox_image),
                    container_id=getattr(sandbox, "container_id", None),
                    command=command,
                    cwd="/workspace",
                    status=RunStatus.SUCCEEDED if output.exit_code == 0 else RunStatus.FAILED,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    duration_ms=duration_ms,
                    stdout_ref=(output.stdout or "")[:1000],
                    stderr_ref=(output.stderr or "")[:1000],
                )
                self.session.add(sandbox_run)
            except Exception:
                pass

            await self.session.commit()
            await self.session.refresh(test_run)

        return test_run

    async def get_test_runs(self, task_id: uuid.UUID) -> Sequence[TestRun]:
        stmt = select(TestRun).where(TestRun.task_id == task_id).order_by(TestRun.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().all()
