"""Tool permissions and capability sets.

Permissions are the mechanism that makes the approval workflow real rather than
cosmetic: during investigation an agent is handed ``READ`` (+ sandboxed
``EXECUTE``) only, so a write tool is not merely disallowed, it is *absent* from
the registry. ``GIT_REMOTE`` is never granted by a task status - it requires an
explicit approval record (see the git phase of the roadmap).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.models.enums import TaskStatus


class Permission(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    NETWORK = "NETWORK"
    GIT_REMOTE = "GIT_REMOTE"


@dataclass(frozen=True, slots=True)
class PermissionSet:
    """An immutable capability set granted to one agent run."""

    permissions: frozenset[Permission]

    @classmethod
    def of(cls, *permissions: Permission) -> PermissionSet:
        return cls(frozenset(permissions))

    @classmethod
    def from_names(cls, names: Iterable[str]) -> PermissionSet:
        return cls(frozenset(Permission(name) for name in names))

    def allows(self, permission: Permission) -> bool:
        return permission in self.permissions

    def plus(self, *extra: Permission) -> PermissionSet:
        return PermissionSet(self.permissions.union(extra))

    def without(self, *removed: Permission) -> PermissionSet:
        return PermissionSet(self.permissions.difference(removed))

    def as_names(self) -> list[str]:
        return sorted(permission.value for permission in self.permissions)

    def __contains__(self, permission: object) -> bool:
        return isinstance(permission, Permission) and permission in self.permissions

    def __repr__(self) -> str:
        return f"PermissionSet({','.join(self.as_names()) or 'none'})"


READ_ONLY: PermissionSet = PermissionSet.of(Permission.READ)
INVESTIGATION: PermissionSet = PermissionSet.of(Permission.READ, Permission.EXECUTE)


def permissions_for_status(status: TaskStatus) -> PermissionSet:
    """Map a task status onto the capability set agents may use.

    * CREATED / PLANNING / ANALYZING / INVESTIGATING / FIX_PROPOSED
      -> read-only plus sandboxed execution (running existing tests is safe).
    * AWAITING_APPROVAL -> read-only (the pipeline is parked for a human).
    * APPLYING -> writes allowed, but only because an Approval row exists; the
      orchestrator re-checks that before granting it.
    * TESTING -> back to read-only + execution.
    * COMPLETED / FAILED / REJECTED -> read-only (terminal).
    """
    if status in {
        TaskStatus.CREATED,
        TaskStatus.PLANNING,
        TaskStatus.ANALYZING,
        TaskStatus.INVESTIGATING,
        TaskStatus.FIX_PROPOSED,
        TaskStatus.TESTING,
    }:
        return INVESTIGATION
    if status is TaskStatus.APPLYING:
        return PermissionSet.of(Permission.READ, Permission.WRITE, Permission.EXECUTE)
    return READ_ONLY
