"""Typed application errors and the single API error envelope.

Every failure raised by DevAgent services/tools should be one of these types so
that the API can map it to a stable HTTP status and a machine-readable code
without leaking internals (or secrets) to the client.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.core.redaction import redact_value


class ErrorCode(StrEnum):
    INTERNAL = "internal_error"
    VALIDATION = "validation_error"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    UNAUTHENTICATED = "unauthenticated"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    POLICY_VIOLATION = "policy_violation"
    APPROVAL_REQUIRED = "approval_required"
    PATCH_INVALID = "patch_invalid"
    INVALID_STATE = "invalid_state_transition"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_ERROR = "provider_error"
    REPOSITORY_INGESTION = "repository_ingestion_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    SANDBOX_TIMEOUT = "sandbox_timeout"
    NOT_IMPLEMENTED_YET = "not_implemented_yet"


class DevAgentError(Exception):
    """Base class for all expected (non-bug) failures."""

    code: ErrorCode = ErrorCode.INTERNAL
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.retryable = retryable

    def to_payload(self, trace_id: str | None = None) -> dict[str, Any]:
        """Serialise to the wire envelope, redacting every detail value."""
        error: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "details": redact_value(self.details),
            "retryable": self.retryable,
        }
        if trace_id:
            error["trace_id"] = trace_id
        return {"error": error}

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"


class ValidationError(DevAgentError):
    code = ErrorCode.VALIDATION
    status_code = 422


class NotFoundError(DevAgentError):
    code = ErrorCode.NOT_FOUND
    status_code = 404


class UnauthenticatedError(DevAgentError):
    code = ErrorCode.UNAUTHENTICATED
    status_code = 401


class ForbiddenError(DevAgentError):
    code = ErrorCode.FORBIDDEN
    status_code = 403


class ConflictError(DevAgentError):
    code = ErrorCode.CONFLICT
    status_code = 409


class RateLimitedError(DevAgentError):
    code = ErrorCode.RATE_LIMITED
    status_code = 429


class PolicyViolationError(DevAgentError):
    """A tool or command was refused by a security policy."""

    code = ErrorCode.POLICY_VIOLATION
    status_code = 403


class ApprovalRequiredError(DevAgentError):
    """The action is only permitted after an explicit human approval."""

    code = ErrorCode.APPROVAL_REQUIRED
    status_code = 409


class PatchError(DevAgentError):
    code = ErrorCode.PATCH_INVALID
    status_code = 422


class InvalidStateTransitionError(DevAgentError):
    code = ErrorCode.INVALID_STATE
    status_code = 409


class BudgetExhaustedError(DevAgentError):
    """An agent hit its step/tool/token/time budget (loop protection)."""

    code = ErrorCode.BUDGET_EXHAUSTED
    status_code = 409


class ProviderError(DevAgentError):
    """The configured LLM or embedding provider failed."""

    code = ErrorCode.PROVIDER_ERROR
    status_code = 502
    retryable = True


class RepositoryIngestionError(DevAgentError):
    code = ErrorCode.REPOSITORY_INGESTION
    status_code = 422


class SandboxUnavailableError(DevAgentError):
    code = ErrorCode.SANDBOX_UNAVAILABLE
    status_code = 503
    retryable = True


class SandboxTimeoutError(DevAgentError):
    code = ErrorCode.SANDBOX_TIMEOUT
    status_code = 504
    retryable = True


class NotImplementedForPhaseError(DevAgentError):
    """Deliberately unimplemented feature, documented in the MVP roadmap.

    This exists so that scaffolding never masquerades as finished functionality.
    """

    code = ErrorCode.NOT_IMPLEMENTED_YET
    status_code = 501

    def __init__(self, feature: str, *, phase: str) -> None:
        super().__init__(
            f"'{feature}' is not part of the MVP and is scheduled for {phase}.",
            details={"feature": feature, "scheduled_phase": phase},
        )
