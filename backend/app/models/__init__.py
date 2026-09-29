"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata`` (Alembic
autogenerate relies on it, see backend/alembic/env.py).
"""

from app.database.base import Base
from app.models.agent import AgentRun, AgentStep, ToolExecution
from app.models.audit import AuditLog
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.chat import ChatMessage, ChatSession
from app.models.chunk import CodeChunk, Dependency, TechStackFinding
from app.models.code import RepoFile, Symbol
from app.models.git import GitOperation
from app.models.repository import Repository, RepositoryBranch
from app.models.sandbox import SandboxRun
from app.models.task import Task, TaskEvent
from app.models.testing import TestCase, TestRun
from app.models.user import User

__all__ = [
    "AgentRun",
    "AgentStep",
    "Approval",
    "AuditLog",
    "Base",
    "ChangeFile",
    "ChatMessage",
    "ChatSession",
    "CodeChunk",
    "Dependency",
    "GitOperation",
    "ProposedChange",
    "RepoFile",
    "Repository",
    "RepositoryBranch",
    "SandboxRun",
    "Symbol",
    "Task",
    "TaskEvent",
    "TechStackFinding",
    "TestCase",
    "TestRun",
    "ToolExecution",
    "User",
]
