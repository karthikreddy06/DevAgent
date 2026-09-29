"""Resource limits applied to every sandbox container.

Kept separate from the runner so the values are inspectable in tests, recorded
on each ``sandbox_runs`` row, and documented in the UI/security docs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings

SANDBOX_USER = "1000:1000"
SANDBOX_WORKDIR = "/workspace"
SANDBOX_HOME = "/home/runner"


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    cpus: float
    mem_mb: int
    pids_limit: int
    timeout_seconds: int
    output_limit_bytes: int
    network_enabled: bool = False

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        network_enabled: bool = False,
        timeout_seconds: int | None = None,
    ) -> SandboxLimits:
        resolved = settings or get_settings()
        requested = timeout_seconds or resolved.sandbox_max_seconds
        return cls(
            cpus=max(0.1, resolved.sandbox_cpus),
            mem_mb=max(128, resolved.sandbox_mem_mb),
            pids_limit=max(16, resolved.sandbox_pids_limit),
            timeout_seconds=max(5, min(requested, resolved.sandbox_max_seconds * 4)),
            output_limit_bytes=max(4096, resolved.sandbox_output_limit_bytes),
            network_enabled=network_enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpus": self.cpus,
            "mem_mb": self.mem_mb,
            "pids_limit": self.pids_limit,
            "timeout_seconds": self.timeout_seconds,
            "output_limit_bytes": self.output_limit_bytes,
            "network_enabled": self.network_enabled,
        }

    def summary(self) -> str:
        network = "bridge" if self.network_enabled else "none"
        return (
            f"{self.cpus} cpu, {self.mem_mb} MB, {self.pids_limit} pids, "
            f"timeout={self.timeout_seconds}s, network={network}"
        )
