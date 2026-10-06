"""Repository workspace management and file tree exploration."""

from __future__ import annotations

import asyncio
import re
import shutil
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PolicyViolationError,
    RepositoryIngestionError,
    ValidationError,
)
from app.core.ids import new_id
from app.core.ignore import load_ignore_matcher
from app.core.paths import safe_join
from app.models.enums import CloneStatus, IndexStatus, RepositorySourceType
from app.models.repository import Repository
from app.models.user import User
from app.schemas.repository import FileContentRead, FileTreeItem, RepositoryCreate


def parse_git_url(url: str) -> tuple[str | None, str | None]:
    """Extract (owner_or_org, repo_name) from a Git remote URL.

    Handles HTTPS, HTTP, and SSH formats:
    - https://github.com/owner/repo.git -> ('owner', 'repo')
    - https://github.com/owner/repo -> ('owner', 'repo')
    - git@github.com:owner/repo.git -> ('owner', 'repo')
    - git@github.com:owner/repo -> ('owner', 'repo')
    """
    if not url:
        return None, None
    clean = url.strip()
    if clean.endswith("/"):
        clean = clean[:-1]
    if clean.endswith(".git"):
        clean = clean[:-4]

    ssh_match = re.match(r"^git@[^:]+:([^/]+)/(.+)$", clean)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    try:
        parsed = urlparse(clean)
        path = parsed.path.strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return parts[-2], parts[-1]
    except Exception:  # noqa: S110
        pass
    return None, None


class RepoService:
    """Manages cloning, workspace storage, and file tree operations."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def workspace_path(self, repo_id: uuid.UUID) -> Path:
        return (self.settings.workspaces_dir / str(repo_id)).resolve()

    async def create_repository(self, req: RepositoryCreate, owner: User) -> Repository:
        repo_name = req.name.strip()
        repo_full_name: str | None = req.full_name.strip() if req.full_name else None

        # 1. Normalize/derive GitHub namespace and full_name when remote URL is provided
        if req.source_type == RepositorySourceType.GIT_URL and req.source_url:
            derived_owner, derived_name = parse_git_url(req.source_url)
            if derived_owner and derived_name:
                repo_full_name = f"{derived_owner}/{derived_name}"
                if not repo_name or repo_name == "main":
                    repo_name = derived_name

        if not repo_full_name:
            if req.owner and req.owner.strip():
                repo_full_name = f"{req.owner.strip()}/{repo_name}"
            else:
                repo_full_name = f"{owner.email.split('@')[0]}/{repo_name}"

        # 2. Validate repository input BEFORE inserting/committing any database row
        if req.source_type == RepositorySourceType.LOCAL_PATH:
            if not self.settings.allow_local_repo_import and not self.settings.is_test:
                raise PolicyViolationError("Local repository import is disabled in this environment")

            if not req.local_path or not Path(req.local_path).exists():  # noqa: ASYNC240
                raise ValidationError("Specified local path does not exist", details={"path": req.local_path})

        elif req.source_type == RepositorySourceType.GIT_URL:
            if not req.source_url or not req.source_url.strip():
                raise ValidationError("source_url is required for git repositories")

            # Check allowed git hosts
            allowed = any(host in req.source_url for host in self.settings.allowed_git_hosts)
            if not allowed:
                raise PolicyViolationError(
                    "Git host is not in ALLOWED_GIT_HOSTS",
                    details={"allowed": self.settings.allowed_git_hosts, "url": req.source_url},
                )
        else:
            raise ValidationError(f"Unsupported repository source type: {req.source_type}")

        # 3. Check for existing repository under (owner.id, repo_full_name)
        stmt = select(Repository).where(
            Repository.owner_id == owner.id,
            Repository.full_name == repo_full_name,
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing is not None:
            if existing.clone_status == CloneStatus.READY:
                raise ConflictError(
                    f"Repository '{repo_full_name}' already exists and is ready",
                    details={"repository_id": str(existing.id), "full_name": repo_full_name},
                )
            # Existing record in failed/pending state can be recovered
            repo = existing
            repo.name = repo_name
            repo.source_type = req.source_type
            repo.source_url = req.source_url
            repo.local_path = req.local_path
            repo.default_branch = req.default_branch
            repo.clone_status = CloneStatus.PENDING
            repo.clone_error = None
            repo.index_status = IndexStatus.NOT_INDEXED
            repo.index_error = None
            is_new = False
        else:
            repo = Repository(
                id=new_id(),
                owner_id=owner.id,
                name=repo_name,
                full_name=repo_full_name,
                source_type=req.source_type,
                source_url=req.source_url,
                local_path=req.local_path,
                default_branch=req.default_branch,
                clone_status=CloneStatus.PENDING,
                index_status=IndexStatus.NOT_INDEXED,
            )
            is_new = True

        target_dir = self.workspace_path(repo.id)
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        # 4. Perform source acquisition safely
        if req.source_type == RepositorySourceType.LOCAL_PATH:
            assert req.local_path is not None
            src = Path(req.local_path).resolve()  # noqa: ASYNC240
            try:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(src, target_dir, symlinks=True, ignore=shutil.ignore_patterns(".venv", "node_modules"))
                repo.clone_status = CloneStatus.READY
                repo.cloned_at = datetime.now(UTC)
                repo.clone_error = None
                if is_new:
                    self.session.add(repo)
                await self.session.commit()
                await self.session.refresh(repo)
            except Exception as exc:
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)
                await self.session.rollback()
                raise RepositoryIngestionError(f"Failed to copy local repository: {exc}") from exc

        elif req.source_type == RepositorySourceType.GIT_URL:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)

            try:
                assert req.source_url is not None
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "clone",
                    "--depth",
                    str(self.settings.clone_depth),
                    req.source_url,
                    str(target_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    err_msg = stderr.decode("utf-8", errors="replace").strip()
                    if target_dir.exists():
                        shutil.rmtree(target_dir, ignore_errors=True)
                    await self.session.rollback()
                    raise RepositoryIngestionError(
                        f"Git clone failed: {err_msg}",
                        details={"url": req.source_url, "exit_code": proc.returncode, "error": err_msg},
                    )

                # Verify workspace contains actual non-ignored repository files
                matcher = load_ignore_matcher(target_dir)
                has_files = any(
                    item.is_file() and not matcher.is_ignored(item.relative_to(target_dir).as_posix(), is_dir=False)
                    for item in target_dir.rglob("*")
                )
                if not has_files:
                    if target_dir.exists():
                        shutil.rmtree(target_dir, ignore_errors=True)
                    await self.session.rollback()
                    raise RepositoryIngestionError(
                        "Git clone succeeded but the cloned repository is empty",
                        details={"url": req.source_url},
                    )

                repo.clone_status = CloneStatus.READY
                repo.cloned_at = datetime.now(UTC)
                repo.clone_error = None
                if is_new:
                    self.session.add(repo)
                await self.session.commit()
                await self.session.refresh(repo)
            except Exception as exc:
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)
                await self.session.rollback()
                if isinstance(exc, (RepositoryIngestionError, ValidationError, PolicyViolationError, ConflictError)):
                    raise
                raise RepositoryIngestionError(f"Git clone failed with unexpected error: {exc}") from exc

        return repo

    async def get_repository(self, repo_id: uuid.UUID) -> Repository:
        stmt = select(Repository).where(Repository.id == repo_id)
        res = await self.session.execute(stmt)
        repo = res.scalar_one_or_none()
        if repo is None:
            raise NotFoundError("Repository not found", details={"repository_id": str(repo_id)})
        return repo

    async def list_repositories(self, owner_id: uuid.UUID | None = None) -> Sequence[Repository]:
        stmt = select(Repository)
        if owner_id:
            stmt = stmt.where(Repository.owner_id == owner_id)
        stmt = stmt.order_by(Repository.created_at.desc())
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def get_file_tree(self, repo_id: uuid.UUID) -> list[FileTreeItem]:
        repo = await self.get_repository(repo_id)
        workspace = self.workspace_path(repo.id)
        if not workspace.exists():
            return []

        matcher = load_ignore_matcher(workspace)

        def build_tree(current_dir: Path) -> list[FileTreeItem]:
            items: list[FileTreeItem] = []
            try:
                for entry in sorted(current_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    rel = entry.relative_to(workspace).as_posix()
                    is_dir = entry.is_dir()
                    if matcher.is_ignored(rel, is_dir=is_dir):
                        continue

                    if is_dir:
                        children = build_tree(entry)
                        items.append(FileTreeItem(name=entry.name, path=rel, is_dir=True, children=children))
                    else:
                        items.append(
                            FileTreeItem(
                                name=entry.name, path=rel, is_dir=False, size_bytes=entry.stat().st_size, children=None
                            )
                        )
            except PermissionError:
                pass
            return items

        return build_tree(workspace)

    async def read_file_content(self, repo_id: uuid.UUID, relative_path: str) -> FileContentRead:
        repo = await self.get_repository(repo_id)
        workspace = self.workspace_path(repo.id)
        target = safe_join(workspace, relative_path)
        if not target.is_file():
            raise NotFoundError("File not found in workspace", details={"path": relative_path})

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        return FileContentRead(
            path=relative_path,
            content=content,
            line_count=len(lines),
            size_bytes=target.stat().st_size,
        )
