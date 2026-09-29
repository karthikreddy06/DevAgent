"""Hardened Docker sandbox executor.

Untrusted repository code only ever runs inside a container created here, with
the isolation policy described in ``docs/architecture/sandbox.md``:

* ``network_mode=none`` unless a caller explicitly opts in (recorded per run)
* read-only root filesystem; writable only at ``/workspace`` (the task copy),
  ``/tmp``, ``/home/runner/.cache`` and ``/home/runner/.local``
* all Linux capabilities dropped, ``no-new-privileges``, non-root user
* CPU / memory / pid limits, wall-clock timeout, capped output
* an environment allowlist with **no** host variables (no DATABASE_URL, no API
  keys, no git tokens)
* the docker socket is never mounted inside a sandbox container
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import docker
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

from app.core.config import Settings, get_settings
from app.core.errors import PolicyViolationError, SandboxUnavailableError
from app.core.logging import get_logger
from app.core.paths import ensure_within
from app.core.redaction import truncate_text
from app.tools.base import SandboxOutput
from app.tools.docker.limits import SANDBOX_HOME, SANDBOX_USER, SANDBOX_WORKDIR, SandboxLimits
from app.tools.docker.policy import validate_command

logger = get_logger(__name__)

MANAGED_LABEL = "devagent.managed"
TASK_LABEL = "devagent.task_id"
CREATED_LABEL = "devagent.created_at"
CONTAINER_PREFIX = "devagent-sbx"

#: The complete environment a sandboxed process sees. Nothing from the host
#: environment is forwarded, so backend secrets cannot leak into repository code.
SANDBOX_ENV: dict[str, str] = {
    "HOME": SANDBOX_HOME,
    "PATH": "/home/runner/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TERM": "dumb",
    "TMPDIR": "/tmp",
    "CI": "true",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONPATH": "/workspace",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    "NPM_CONFIG_FUND": "false",
}

_WRITABLE_TMPFS: dict[str, str] = {
    "/tmp": "size=256m,mode=1777",
    f"{SANDBOX_HOME}/.cache": "size=512m,mode=1777",
    f"{SANDBOX_HOME}/.local": "size=256m,mode=1777",
    f"{SANDBOX_HOME}/.config": "size=64m,mode=1777",
}


def container_name(task_id: str) -> str:
    return f"{CONTAINER_PREFIX}-{task_id.replace('-', '')[:12]}-{uuid.uuid4().hex[:6]}"


def resolve_host_workspace_path(workspace: Path, client: docker.DockerClient | None = None) -> str:
    """Translate workspace path when running inside a container (sibling container mounting)."""
    ws_str = str(workspace)
    try:
        cli = client or docker.from_env()
        hostname = socket.gethostname()
        me = cli.containers.get(hostname)
        for m in me.attrs.get("Mounts", []):
            dest = m.get("Destination")
            src = m.get("Source")
            if dest and src and ws_str.startswith(dest):
                rel = os.path.relpath(ws_str, dest)
                resolved = os.path.join(src, rel) if rel != "." else src
                logger.info("resolved_host_workspace_path", original=ws_str, host_path=resolved)
                return resolved
    except Exception as exc:
        logger.debug("resolve_host_workspace_path_fallback", error=str(exc))
    return ws_str


def build_container_kwargs(
    *,
    image: str,
    workspace: Path,
    task_id: str,
    limits: SandboxLimits,
) -> dict[str, Any]:
    """The single source of truth for container hardening (asserted in tests)."""
    vol_source = resolve_host_workspace_path(workspace)
    return {
        "image": image,
        "command": ["sleep", "infinity"],
        "name": container_name(task_id),
        "labels": {
            MANAGED_LABEL: "true",
            TASK_LABEL: task_id,
            CREATED_LABEL: datetime.now(UTC).isoformat(),
        },
        "working_dir": SANDBOX_WORKDIR,
        "volumes": {vol_source: {"bind": SANDBOX_WORKDIR, "mode": "rw"}},
        "environment": dict(SANDBOX_ENV),
        "user": SANDBOX_USER,
        "network_mode": "bridge" if limits.network_enabled else "none",
        "mem_limit": f"{limits.mem_mb}m",
        "memswap_limit": f"{limits.mem_mb}m",
        "nano_cpus": int(limits.cpus * 1_000_000_000),
        "pids_limit": limits.pids_limit,
        "read_only": True,
        "tmpfs": dict(_WRITABLE_TMPFS),
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "ulimits": [docker.types.Ulimit(name="nofile", soft=1024, hard=2048)],
        "shm_size": "64m",
        "detach": True,
        "stdin_open": False,
        "tty": False,
        "auto_remove": False,  # explicit removal + reaper; auto-remove hides failures
        "privileged": False,
    }


def docker_client() -> docker.DockerClient:
    """Connect to the daemon, raising a clear error when it is unavailable."""
    try:
        return docker.from_env()
    except DockerException as exc:  # pragma: no cover - environment dependent
        raise SandboxUnavailableError(
            "Cannot reach the Docker daemon. Start Docker Desktop (WSL2 backend) and try again.",
            details={"reason": type(exc).__name__},
        ) from exc


def docker_available() -> bool:
    """Non-raising probe used by tests, the reaper and the health endpoint."""
    try:
        client = docker.from_env()
    except DockerException:
        return False
    try:
        client.ping()
        return True
    except DockerException:
        return False


def reap_orphans(client: docker.DockerClient, *, ttl_seconds: int = 3600, dry_run: bool = False) -> list[str]:
    """Remove managed sandbox containers older than ``ttl_seconds``."""
    removed: list[str] = []
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
    for container in client.containers.list(all=True, filters={"label": f"{MANAGED_LABEL}=true"}):
        created_raw = str(container.labels.get(CREATED_LABEL, ""))
        try:
            created = datetime.fromisoformat(created_raw) if created_raw else None
        except ValueError:
            created = None
        if created is not None and created > cutoff:
            continue
        removed.append((container.id or "")[:12])
        if dry_run:
            continue
        try:
            container.remove(force=True)
        except NotFound:
            continue
        except DockerException as exc:  # pragma: no cover - best effort cleanup
            logger.warning("sandbox_reap_failed", container=(container.id or "")[:12], error=type(exc).__name__)
    if removed:
        logger.info("sandbox_orphans_reaped", count=len(removed), dry_run=dry_run)
    return removed


def assert_workspace_is_safe(workspace: Path, settings: Settings | None = None) -> Path:
    """The mounted directory must live inside the managed workspace root."""
    resolved_settings = settings or get_settings()
    root = resolved_settings.workspaces_dir.resolve()
    resolved = ensure_within(root, workspace)
    if not resolved.is_dir():
        raise PolicyViolationError("Sandbox workspace does not exist", details={"workspace": str(resolved)})
    return resolved


class DockerSandboxExecutor:
    """Creates, uses and destroys a hardened container for one task.

    Lifecycle: ``start()`` -> ``execute()`` (repeatable) -> ``destroy()``.
    The container is reused across commands within one agent run to keep
    test-suite cycles fast, and is always destroyed in the caller's ``finally``
    block plus by the periodic reaper as a backstop.
    """

    def __init__(
        self,
        *,
        task_id: str,
        workspace: Path,
        settings: Settings | None = None,
        image: str | None = None,
        stack: str = "python",
        client: docker.DockerClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._task_id = task_id
        self._workspace = assert_workspace_is_safe(workspace, self._settings)
        self._image = image or self._settings.sandbox_image
        self._stack = stack
        self._client = client
        self._container: Container | None = None
        self._locked = False

    # ------------------------------------------------------------- lifecycle
    @property
    def container(self) -> Container | None:
        return self._container

    @property
    def container_id(self) -> str | None:
        return self._container.id if self._container is not None else None

    @property
    def stack(self) -> str:
        return self._stack

    def set_stack(self, stack: str) -> None:
        self._stack = stack

    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker_client()
        return self._client

    async def start(self) -> None:
        """Create and start the container (no-op when already running)."""
        if not self._settings.sandbox_enabled:
            raise SandboxUnavailableError("The sandbox is disabled (SANDBOX_ENABLED=false)")

        if self._container is not None and not self._locked:
            try:
                await asyncio.to_thread(self._container.reload)
            except (NotFound, DockerException):
                self._container = None
            else:
                if self._container.status == "running":
                    return
                self._container = None
        if self._locked:
            raise SandboxUnavailableError("Sandbox container was killed after a timeout and must be recreated")

        limits = SandboxLimits.from_settings(self._settings)
        kwargs = build_container_kwargs(
            image=self._image,
            workspace=self._workspace,
            task_id=self._task_id,
            limits=limits,
        )
        self._container = await asyncio.to_thread(self._create, kwargs)
        logger.info(
            "sandbox_started",
            task_id=self._task_id,
            container=(self._container.id or "")[:12] if self._container else "",
            image=self._image,
            limits=limits.summary(),
        )

    def _create(self, kwargs: dict[str, Any]) -> Container:
        client = self.client()
        try:
            client.images.get(self._image)
        except docker.errors.ImageNotFound as exc:
            raise SandboxUnavailableError(
                "Sandbox runner image is not built locally",
                details={"image": self._image, "hint": "run: make sandbox-images"},
            ) from exc
        except DockerException as exc:  # pragma: no cover - environment dependent
            raise SandboxUnavailableError("Docker daemon error", details={"reason": type(exc).__name__}) from exc
        container = cast(Container, client.containers.run(**kwargs))
        with contextlib.suppress(DockerException):
            container.reload()
        return container

    # -------------------------------------------------------------- execution
    async def execute(
        self,
        argv: Sequence[str],
        *,
        purpose: str = "command",
        cwd: str = SANDBOX_WORKDIR,
        timeout_seconds: int | None = None,
        network_enabled: bool = False,
        agent: Any = None,
    ) -> SandboxOutput:
        """Validate, then run one command inside the sandbox."""
        limits = SandboxLimits.from_settings(
            self._settings, network_enabled=network_enabled, timeout_seconds=timeout_seconds
        )
        try:
            command = validate_command(argv, stack=self._stack, cwd=cwd)
        except PolicyViolationError as exc:
            logger.warning("sandbox_command_refused", task_id=self._task_id, purpose=purpose, reason=exc.message)
            return SandboxOutput(exit_code=None, stdout="", stderr="", error=f"policy: {exc.message}")

        try:
            await self.start()
        except SandboxUnavailableError as exc:
            return SandboxOutput(exit_code=None, stdout="", stderr="", error=exc.message)

        container = self._container
        if container is None:  # pragma: no cover - start() guarantees this
            return SandboxOutput(exit_code=None, stdout="", stderr="", error="sandbox container unavailable")

        started = time.perf_counter()
        logger.info(
            "sandbox_command_started",
            task_id=self._task_id,
            purpose=purpose,
            container=(container.id or "")[:12],
            executable=command[0],
        )
        try:
            exit_code, (stdout, stderr) = await asyncio.wait_for(
                asyncio.to_thread(self._exec, container, command, cwd), timeout=limits.timeout_seconds
            )
            timed_out = False
        except TimeoutError:
            timed_out = True
            exit_code = None
            stdout, stderr = b"", b""
            await self.kill()
        except DockerException as exc:
            return SandboxOutput(
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=int((time.perf_counter() - started) * 1000),
                container_id=(container.id or "")[:12],
                error=f"docker error: {type(exc).__name__}",
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        text_out = stdout.decode("utf-8", errors="replace")
        text_err = stderr.decode("utf-8", errors="replace")
        truncated = len(text_out) > limits.output_limit_bytes or len(text_err) > limits.output_limit_bytes

        logger.info(
            "sandbox_command_finished",
            task_id=self._task_id,
            purpose=purpose,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=duration_ms,
        )
        return SandboxOutput(
            exit_code=exit_code,
            stdout=truncate_text(text_out, limits.output_limit_bytes),
            stderr=truncate_text(text_err, limits.output_limit_bytes),
            timed_out=timed_out,
            oom_killed=self._oom_killed(container),
            truncated=truncated,
            duration_ms=duration_ms,
            container_id=(container.id or "")[:12],
        )

    @staticmethod
    def _exec(container: Container, command: Sequence[str], cwd: str) -> tuple[int | None, tuple[bytes, bytes]]:
        result = container.exec_run(
            cmd=list(command),
            workdir=cwd,
            user=SANDBOX_USER,
            demux=True,
            tty=False,
            environment=None,  # container-level allowlist only
        )
        raw = result.output if isinstance(result.output, tuple) else (result.output or b"", b"")

        def _to_bytes(val: Any) -> bytes:
            if isinstance(val, (bytes, bytearray)):
                return bytes(val)
            if hasattr(val, "__iter__"):
                return b"".join(val)
            return b""

        return result.exit_code, (_to_bytes(raw[0]), _to_bytes(raw[1]))

    @staticmethod
    def _oom_killed(container: Container) -> bool:
        try:
            container.reload()
            return bool(container.attrs.get("State", {}).get("OOMKilled", False))
        except (NotFound, DockerException):  # pragma: no cover - best effort
            return False

    async def kill(self) -> None:
        """Force-stop the container (used on timeout) and require a fresh one."""
        container, self._container = self._container, None
        self._locked = True
        if container is None:
            return
        try:
            await asyncio.to_thread(container.kill)
            logger.warning("sandbox_container_killed", task_id=self._task_id, container=(container.id or "")[:12])
        except (NotFound, DockerException):  # pragma: no cover
            pass

    async def destroy(self) -> bool:
        """Remove the container. Called from a ``finally`` block by the service."""
        container, self._container = self._container, None
        if container is None:
            return True
        try:
            await asyncio.to_thread(container.remove, force=True)
            logger.info("sandbox_destroyed", task_id=self._task_id, container=(container.id or "")[:12])
            return True
        except NotFound:
            return True
        except DockerException as exc:  # pragma: no cover - reaper is the backstop
            logger.warning("sandbox_destroy_failed", task_id=self._task_id, error=type(exc).__name__)
            return False

    async def __aenter__(self) -> DockerSandboxExecutor:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.destroy()
