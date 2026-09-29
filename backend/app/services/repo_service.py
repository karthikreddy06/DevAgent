"""Repository workspace management and file tree exploration."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, PolicyViolationError, ValidationError
from app.core.ignore import load_ignore_matcher
from app.core.paths import safe_join
from app.models.enums import CloneStatus, IndexStatus, RepositorySourceType
from app.models.repository import Repository
from app.models.user import User
from app.schemas.repository import FileContentRead, FileTreeItem, RepositoryCreate


class RepoService:
    """Manages cloning, workspace storage, and file tree operations."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def workspace_path(self, repo_id: uuid.UUID) -> Path:
        return (self.settings.workspaces_dir / str(repo_id)).resolve()

    async def create_repository(self, req: RepositoryCreate, owner: User) -> Repository:
        full_name = req.full_name or f"{owner.email.split('@')[0]}/{req.name}"
        repo = Repository(
            owner_id=owner.id,
            name=req.name,
            full_name=full_name,
            source_type=req.source_type,
            source_url=req.source_url,
            local_path=req.local_path,
            default_branch=req.default_branch,
            clone_status=CloneStatus.PENDING,
            index_status=IndexStatus.NOT_INDEXED,
        )
        self.session.add(repo)
        await self.session.commit()
        await self.session.refresh(repo)

        target_dir = self.workspace_path(repo.id)
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        if req.source_type == RepositorySourceType.LOCAL_PATH:
            if not self.settings.allow_local_repo_import and not self.settings.is_test:
                raise PolicyViolationError("Local repository import is disabled in this environment")

            if not req.local_path or not Path(req.local_path).exists():  # noqa: ASYNC240
                raise ValidationError("Specified local path does not exist", details={"path": req.local_path})

            src = Path(req.local_path).resolve()  # noqa: ASYNC240
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(src, target_dir, symlinks=True, ignore=shutil.ignore_patterns(".venv", "node_modules"))
            repo.clone_status = CloneStatus.READY
            repo.cloned_at = datetime.now(UTC)
            await self.session.commit()
            await self.session.refresh(repo)

        elif req.source_type == RepositorySourceType.GIT_URL:
            if not req.source_url:
                raise ValidationError("source_url is required for git repositories")

            # Check allowed git hosts
            allowed = any(host in req.source_url for host in self.settings.allowed_git_hosts)
            if not allowed:
                raise PolicyViolationError(
                    "Git host is not in ALLOWED_GIT_HOSTS",
                    details={"allowed": self.settings.allowed_git_hosts, "url": req.source_url},
                )

            repo.clone_status = CloneStatus.CLONING
            await self.session.commit()

            try:
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
                    repo.clone_status = CloneStatus.FAILED
                    repo.clone_error = stderr.decode("utf-8", errors="replace").strip()
                else:
                    repo.clone_status = CloneStatus.READY
                    repo.cloned_at = datetime.now(UTC)
            except Exception as exc:
                repo.clone_status = CloneStatus.FAILED
                repo.clone_error = str(exc)

            await self.session.commit()
            await self.session.refresh(repo)

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
