"""Integration tests for hardened Docker sandbox execution.

Requires a running Docker daemon and the `devagent/runner-python:3.12` image.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import docker
import pytest

from app.core.config import Settings
from app.tools.docker.runner import DockerSandboxExecutor, docker_available, docker_client


@pytest.mark.docker
class TestDockerSandbox:
    @pytest.fixture(autouse=True)
    def check_docker(self) -> None:
        if not docker_available():
            pytest.skip("Docker daemon is not available")

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        settings = Settings(env="test", workspaces_dir=tmp_path / "workspaces")
        ws = settings.workspaces_dir / f"test-{uuid.uuid4().hex[:8]}"
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    @pytest.fixture
    def test_settings(self, tmp_path: Path) -> Settings:
        return Settings(
            env="test",
            workspaces_dir=tmp_path / "workspaces",
            sandbox_enabled=True,
            sandbox_image="devagent/runner-python:3.12",
        )

    @pytest.mark.asyncio
    async def test_sandbox_executes_harmless_command(self, workspace: Path, test_settings: Settings) -> None:
        script = workspace / "test_ok.py"
        script.write_text(
            "import sys\n"
            "print('SANDBOX_OK')\n"
            "sys.stderr.write('SANDBOX_STDERR\\n')\n",
            encoding="utf-8",
        )
        task_id = str(uuid.uuid4())
        executor = DockerSandboxExecutor(
            task_id=task_id,
            workspace=workspace,
            settings=test_settings,
        )
        try:
            await executor.start()
            assert executor.container is not None
            assert executor.container.status == "running"

            output = await executor.execute(
                ["python", "test_ok.py"],
                purpose="Test stdout and stderr capture",
            )
            assert output.exit_code == 0
            assert "SANDBOX_OK" in output.stdout
            assert "SANDBOX_STDERR" in output.stderr
            assert output.ok
        finally:
            await executor.destroy()
            assert executor.container is None

    @pytest.mark.asyncio
    async def test_sandbox_enforces_read_only_rootfs(self, workspace: Path, test_settings: Settings) -> None:
        script = workspace / "test_ro.py"
        script.write_text("open('/root_test.txt', 'w').write('fail')\n", encoding="utf-8")

        task_id = str(uuid.uuid4())
        executor = DockerSandboxExecutor(
            task_id=task_id,
            workspace=workspace,
            settings=test_settings,
        )
        try:
            output = await executor.execute(
                ["python", "test_ro.py"],
                purpose="Verify read-only rootfs",
            )
            assert output.exit_code != 0
            assert "Read-only file system" in output.stderr or "Permission denied" in output.stderr
        finally:
            await executor.destroy()

    @pytest.mark.asyncio
    async def test_sandbox_has_no_network_access(self, workspace: Path, test_settings: Settings) -> None:
        script = workspace / "test_net.py"
        script.write_text(
            "import urllib.request\n"
            "urllib.request.urlopen('http://1.1.1.1', timeout=2)\n",
            encoding="utf-8",
        )
        task_id = str(uuid.uuid4())
        executor = DockerSandboxExecutor(
            task_id=task_id,
            workspace=workspace,
            settings=test_settings,
        )
        try:
            output = await executor.execute(
                ["python", "test_net.py"],
                purpose="Verify network isolation",
            )
            assert output.exit_code != 0
            assert "Network is unreachable" in output.stderr or "URLError" in output.stderr
        finally:
            await executor.destroy()

    @pytest.mark.asyncio
    async def test_sandbox_does_not_leak_host_environment(self, workspace: Path, test_settings: Settings) -> None:
        script = workspace / "test_env.py"
        script.write_text(
            "import os\n"
            "print('ENV_KEYS:', ','.join(os.environ.keys()))\n",
            encoding="utf-8",
        )
        task_id = str(uuid.uuid4())
        executor = DockerSandboxExecutor(
            task_id=task_id,
            workspace=workspace,
            settings=test_settings,
        )
        try:
            output = await executor.execute(
                ["python", "test_env.py"],
                purpose="Verify no host environment leakage",
            )
            assert output.exit_code == 0
            stdout = output.stdout
            assert "SECRET_KEY" not in stdout
            assert "DATABASE_URL" not in stdout
            assert "JWT_SECRET" not in stdout
        finally:
            await executor.destroy()

    @pytest.mark.asyncio
    async def test_sandbox_cleanup(self, workspace: Path, test_settings: Settings) -> None:
        task_id = str(uuid.uuid4())
        executor = DockerSandboxExecutor(
            task_id=task_id,
            workspace=workspace,
            settings=test_settings,
        )
        await executor.start()
        container_id = executor.container_id
        assert container_id is not None

        client = docker_client()
        container = client.containers.get(container_id)
        assert container.status == "running"

        await executor.destroy()

        with pytest.raises(docker.errors.NotFound):
            client.containers.get(container_id)
