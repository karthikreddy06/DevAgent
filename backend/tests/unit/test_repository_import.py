"""Regression tests for repository import and indexing workflow.

Covers the 12 required regression test cases:
1. Missing source_url does not create a stale committed repository.
2. Invalid Git repository input can be retried successfully.
3. Missing workspace cannot become INDEXED.
4. Empty workspace cannot become INDEXED.
5. clone_status != READY prevents successful indexing.
6. Zero indexed files results in FAILED.
7. Zero indexed chunks results in FAILED when indexable files exist but 0 chunks generated.
8. Valid Git URL import stores the correct GitHub full_name.
9. DevAgent owner_id remains the authenticated DevAgent user.
10. Existing healthy repositories continue to work.
11. Existing successful repository indexing still works.
12. Existing repository uniqueness constraints continue to work.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import ConflictError, RepositoryIngestionError, ValidationError
from app.models.enums import CloneStatus, IndexStatus, RepositorySourceType
from app.models.repository import Repository
from app.models.user import User
from app.retrieval.indexing import RepoIndexer
from app.schemas.repository import RepositoryCreate
from app.services.repo_service import RepoService


def create_mock_session() -> AsyncMock:
    """Create a mock SQLAlchemy AsyncSession that tracks added and committed objects."""
    session = AsyncMock()
    session.added_objects: list[object] = []

    def mock_add(obj: object) -> None:
        session.added_objects.append(obj)

    session.add = MagicMock(side_effect=mock_add)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    # Default execute returns None for scalar_one_or_none
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_result

    return session


@pytest.fixture
def mock_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="developer@devagent.ai",
        display_name="dev_user",
        password_hash="pw",
    )


# ---------------------------------------------------------------------------
# Test 1: Missing source_url does not create a stale committed repository
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_missing_source_url_does_not_commit_repository(mock_user: User, test_settings: Settings) -> None:
    session = create_mock_session()
    service = RepoService(session, test_settings)

    req = RepositoryCreate(
        name="test-repo",
        source_type=RepositorySourceType.GIT_URL,
        source_url=None,
    )

    with pytest.raises(ValidationError) as exc:
        await service.create_repository(req, mock_user)

    assert "source_url is required" in str(exc.value)
    # Critical invariant: no row added, no transaction committed
    assert len(session.added_objects) == 0
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: Invalid Git repository input can be retried successfully
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_invalid_git_repo_input_can_be_retried_successfully(
    mock_user: User, test_settings: Settings, tmp_path: Path
) -> None:
    settings = Settings(
        env="test",
        workspaces_dir=tmp_path / "workspaces",
        allow_local_repo_import=True,
    )
    session = create_mock_session()
    service = RepoService(session, settings)

    req_fail = RepositoryCreate(
        name="nonexistent-repo",
        source_type=RepositorySourceType.GIT_URL,
        source_url="https://github.com/karthikreddy06/does-not-exist-12345",
    )

    # Mock git clone failure
    mock_proc_fail = AsyncMock()
    mock_proc_fail.communicate.return_value = (b"", b"fatal: repository not found")
    mock_proc_fail.returncode = 128

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_fail):
        with pytest.raises(RepositoryIngestionError) as exc:
            await service.create_repository(req_fail, mock_user)
        assert "Git clone failed" in str(exc.value)

    # Rollback called, no commit
    session.rollback.assert_called()
    assert len(session.added_objects) == 0
    session.commit.assert_not_called()

    # Now retry with valid input and mock successful git clone
    req_success = RepositoryCreate(
        name="valid-repo",
        source_type=RepositorySourceType.GIT_URL,
        source_url="https://github.com/karthikreddy06/devagent-bug-test",
    )

    # Setup temporary directory containing valid files to simulate git clone
    async def fake_clone(*args: object, **kwargs: object) -> AsyncMock:
        target_dir = Path(str(args[-1]))
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "app.py").write_text("print('hello')", encoding="utf-8")
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_clone):
        repo = await service.create_repository(req_success, mock_user)

    assert repo.clone_status == CloneStatus.READY
    assert repo.full_name == "karthikreddy06/devagent-bug-test"
    assert len(session.added_objects) == 1
    session.commit.assert_called()


# ---------------------------------------------------------------------------
# Test 3: Missing workspace cannot become INDEXED
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_missing_workspace_cannot_become_indexed(test_settings: Settings, tmp_path: Path) -> None:
    session = create_mock_session()
    indexer = RepoIndexer(session=session, settings=test_settings)

    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="missing-ws",
        full_name="org/missing-ws",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.NOT_INDEXED,
        indexed_files=0,
        indexed_chunks=0,
    )

    non_existent = tmp_path / "does_not_exist_workspace"

    with pytest.raises(RepositoryIngestionError) as exc:
        await indexer.index_repository(repo, non_existent)

    assert "workspace directory does not exist" in str(exc.value)
    assert repo.index_status == IndexStatus.FAILED
    assert repo.indexed_files == 0
    assert repo.indexed_chunks == 0
    assert "does not exist" in (repo.index_error or "")
    session.commit.assert_called()


# ---------------------------------------------------------------------------
# Test 4: Empty workspace cannot become INDEXED
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_empty_workspace_cannot_become_indexed(test_settings: Settings, tmp_path: Path) -> None:
    session = create_mock_session()
    indexer = RepoIndexer(session=session, settings=test_settings)

    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="empty-ws",
        full_name="org/empty-ws",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.NOT_INDEXED,
        indexed_files=0,
        indexed_chunks=0,
    )

    empty_dir = tmp_path / "empty_workspace"
    empty_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RepositoryIngestionError) as exc:
        await indexer.index_repository(repo, empty_dir)

    assert "zero indexable source files" in str(exc.value)
    assert repo.index_status == IndexStatus.FAILED
    assert repo.indexed_files == 0
    assert repo.indexed_chunks == 0
    session.commit.assert_called()


# ---------------------------------------------------------------------------
# Test 5: clone_status != READY prevents successful indexing
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize("status", [CloneStatus.PENDING, CloneStatus.CLONING, CloneStatus.FAILED])
async def test_clone_status_not_ready_prevents_indexing(
    status: CloneStatus, test_settings: Settings, temp_workspace: Path
) -> None:
    session = create_mock_session()
    indexer = RepoIndexer(session=session, settings=test_settings)

    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="unready-repo",
        full_name="org/unready-repo",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=status,
        index_status=IndexStatus.NOT_INDEXED,
        indexed_files=0,
        indexed_chunks=0,
    )

    with pytest.raises(RepositoryIngestionError) as exc:
        await indexer.index_repository(repo, temp_workspace)

    assert "clone status is" in str(exc.value)
    assert repo.index_status == IndexStatus.FAILED
    assert repo.indexed_files == 0
    assert repo.indexed_chunks == 0
    session.commit.assert_called()


# ---------------------------------------------------------------------------
# Test 6: Zero indexed files results in FAILED
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_zero_indexed_files_results_in_failed(test_settings: Settings, tmp_path: Path) -> None:
    session = create_mock_session()
    indexer = RepoIndexer(session=session, settings=test_settings)

    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="ignored-files-repo",
        full_name="org/ignored-files-repo",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.NOT_INDEXED,
        indexed_files=0,
        indexed_chunks=0,
    )

    ws = tmp_path / "ignored_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    # Put only ignored suffixes or binary NUL files
    (ws / "model.onnx").write_bytes(b"\x00\x01\x02\x03")
    (ws / "data.pickle").write_bytes(b"pickle_data")

    with pytest.raises(RepositoryIngestionError):
        await indexer.index_repository(repo, ws)

    assert repo.index_status == IndexStatus.FAILED
    assert repo.indexed_files == 0
    assert repo.indexed_chunks == 0
    assert "zero indexable source files" in (repo.index_error or "")


# ---------------------------------------------------------------------------
# Test 7: Zero indexed chunks results in FAILED when files exist but chunks=0
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_zero_indexed_chunks_results_in_failed(test_settings: Settings, tmp_path: Path) -> None:
    session = create_mock_session()
    indexer = RepoIndexer(session=session, settings=test_settings)

    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="no-chunks-repo",
        full_name="org/no-chunks-repo",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.NOT_INDEXED,
        indexed_files=0,
        indexed_chunks=0,
    )

    ws = tmp_path / "no_chunks_ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "sample.py").write_text("print('test')", encoding="utf-8")

    # Mock chunk_file_content to return empty chunks
    with (
        patch("app.retrieval.indexing.chunk_file_content", return_value=([], [])),
        pytest.raises(RepositoryIngestionError) as exc,
    ):
        await indexer.index_repository(repo, ws)

    assert "generated 0 indexable chunks" in str(exc.value)
    assert repo.index_status == IndexStatus.FAILED
    assert repo.indexed_files == 0
    assert repo.indexed_chunks == 0


# ---------------------------------------------------------------------------
# Test 8: Valid Git URL import stores the correct GitHub full_name
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_valid_git_url_stores_correct_github_full_name(
    mock_user: User, test_settings: Settings, tmp_path: Path
) -> None:
    settings = Settings(
        env="test",
        workspaces_dir=tmp_path / "workspaces",
        allow_local_repo_import=True,
    )
    session = create_mock_session()
    service = RepoService(session, settings)

    req = RepositoryCreate(
        name="devagent-bug-test",
        source_type=RepositorySourceType.GIT_URL,
        source_url="https://github.com/karthikreddy06/devagent-bug-test",
    )

    async def fake_clone(*args: object, **kwargs: object) -> AsyncMock:
        target_dir = Path(str(args[-1]))
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "main.py").write_text("x = 1\n", encoding="utf-8")
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_clone):
        repo = await service.create_repository(req, mock_user)

    assert repo.name == "devagent-bug-test"
    assert repo.full_name == "karthikreddy06/devagent-bug-test"
    assert repo.clone_status == CloneStatus.READY


# ---------------------------------------------------------------------------
# Test 9: DevAgent owner_id remains the authenticated DevAgent user
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_owner_id_remains_authenticated_devagent_user(
    mock_user: User, test_settings: Settings, tmp_path: Path
) -> None:
    settings = Settings(
        env="test",
        workspaces_dir=tmp_path / "workspaces",
        allow_local_repo_import=True,
    )
    session = create_mock_session()
    service = RepoService(session, settings)

    req = RepositoryCreate(
        name="devagent-bug-test",
        owner="karthikreddy06",
        source_type=RepositorySourceType.GIT_URL,
        source_url="https://github.com/karthikreddy06/devagent-bug-test",
    )

    async def fake_clone(*args: object, **kwargs: object) -> AsyncMock:
        target_dir = Path(str(args[-1]))
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "main.py").write_text("x = 1\n", encoding="utf-8")
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_clone):
        repo = await service.create_repository(req, mock_user)

    # Invariant: owner_id is DevAgent user's UUID, NOT GitHub username
    assert repo.owner_id == mock_user.id
    assert isinstance(repo.owner_id, uuid.UUID)
    assert repo.full_name == "karthikreddy06/devagent-bug-test"


# ---------------------------------------------------------------------------
# Test 10: Existing healthy repositories continue to work
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_existing_healthy_repository_is_ready() -> None:
    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="multi-document-rag-assistant",
        full_name="karthik05421/multi-document-rag-assistant",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.INDEXED,
        indexed_files=144,
        indexed_chunks=745,
    )

    assert repo.is_ready is True
    assert repo.clone_status == CloneStatus.READY
    assert repo.index_status == IndexStatus.INDEXED
    assert repo.indexed_files == 144
    assert repo.indexed_chunks == 745


# ---------------------------------------------------------------------------
# Test 11: Existing successful repository indexing still works
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_existing_successful_repository_indexing(test_settings: Settings, temp_workspace: Path) -> None:
    session = create_mock_session()
    indexer = RepoIndexer(session=session, settings=test_settings)

    repo = Repository(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="calculator-repo",
        full_name="org/calculator-repo",
        source_type=RepositorySourceType.LOCAL_PATH,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.NOT_INDEXED,
        indexed_files=0,
        indexed_chunks=0,
    )

    chunks_indexed = await indexer.index_repository(repo, temp_workspace)

    assert chunks_indexed > 0
    assert repo.index_status == IndexStatus.INDEXED
    assert repo.indexed_files > 0
    assert repo.indexed_chunks > 0
    assert repo.index_error is None
    session.commit.assert_called()


# ---------------------------------------------------------------------------
# Test 12: Existing repository uniqueness constraints continue to work
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_existing_repository_uniqueness_constraint_prevents_duplicate_ready(
    mock_user: User, test_settings: Settings
) -> None:
    session = create_mock_session()

    existing_ready_repo = Repository(
        id=uuid.uuid4(),
        owner_id=mock_user.id,
        name="existing-repo",
        full_name="karthikreddy06/existing-repo",
        source_type=RepositorySourceType.GIT_URL,
        clone_status=CloneStatus.READY,
        index_status=IndexStatus.INDEXED,
    )

    # Mock session to find existing ready repo
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = existing_ready_repo
    session.execute.return_value = exec_result

    service = RepoService(session, test_settings)

    req = RepositoryCreate(
        name="existing-repo",
        source_type=RepositorySourceType.GIT_URL,
        source_url="https://github.com/karthikreddy06/existing-repo",
    )

    with pytest.raises(ConflictError) as exc:
        await service.create_repository(req, mock_user)

    assert "already exists and is ready" in str(exc.value)
