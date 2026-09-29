"""Domain enumerations shared by models, schemas, agents and the frontend."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle of a task. Transitions live in app/orchestration/state_machine.py."""

    CREATED = "CREATED"
    PLANNING = "PLANNING"
    ANALYZING = "ANALYZING"
    INVESTIGATING = "INVESTIGATING"
    FIX_PROPOSED = "FIX_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPLYING = "APPLYING"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class TaskType(StrEnum):
    BUG = "bug"
    FEATURE = "feature"
    QUESTION = "question"
    SECURITY = "security"
    DOCS = "docs"


class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    CODEBASE = "codebase"
    RETRIEVAL = "retrieval"
    DEBUGGER = "debugger"
    TESTER = "tester"
    SECURITY = "security"
    DOCUMENTATION = "documentation"
    GIT = "git"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"


class StepKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    DECISION = "decision"
    NOTE = "note"


class EventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Confidence(StrEnum):
    """How strongly a root-cause hypothesis is supported by evidence."""

    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    POSSIBLE = "POSSIBLE"


class ChangeStatus(StrEnum):
    DRAFT = "DRAFT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class ChangeType(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


class ApprovalKind(StrEnum):
    APPLY_CHANGES = "APPLY_CHANGES"
    GIT_PUSH = "GIT_PUSH"
    PULL_REQUEST = "PULL_REQUEST"
    DANGEROUS_COMMAND = "DANGEROUS_COMMAND"
    SECURITY_FIX = "SECURITY_FIX"
    NETWORK_INSTALL = "NETWORK_INSTALL"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFICATION_REQUESTED = "MODIFICATION_REQUESTED"


class TestOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class RepositorySourceType(StrEnum):
    GIT_URL = "git_url"
    LOCAL_PATH = "local_path"


class CloneStatus(StrEnum):
    PENDING = "PENDING"
    CLONING = "CLONING"
    READY = "READY"
    FAILED = "FAILED"


class IndexStatus(StrEnum):
    NOT_INDEXED = "NOT_INDEXED"
    PENDING = "PENDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class AnalysisStatus(StrEnum):
    NOT_ANALYZED = "NOT_ANALYZED"
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class GitOperationKind(StrEnum):
    STATUS = "status"
    BRANCH = "branch"
    COMMIT = "commit"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    FETCH = "fetch"


class GitOperationStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TechKind(StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    PACKAGE_MANAGER = "package_manager"
    TEST_FRAMEWORK = "test_framework"
    BUILD_TOOL = "build_tool"
    CI = "ci"


class ChunkType(StrEnum):
    SYMBOL = "symbol"
    BLOCK = "block"
    WINDOW = "window"
    DOC = "doc"
    CONFIG = "config"
    TEST = "test"


class SymbolKind(StrEnum):
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    CLASS = "class"
    MODULE = "module"
    CONSTANT = "constant"
