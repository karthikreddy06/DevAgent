"""Unit tests for tool registry and filesystem/search/write tools."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import PolicyViolationError
from app.models.enums import AgentName, TaskStatus
from app.tools.base import ToolContext
from app.tools.filesystem import ListFilesArgs, ListFilesTool, ReadFileArgs, ReadFileTool
from app.tools.permissions import READ_ONLY, Permission, PermissionSet
from app.tools.registry import ToolRegistry
from app.tools.search import SearchInFilesArgs, SearchInFilesTool
from app.tools.write import (
    ApplyPatchArgs,
    ApplyPatchTool,
    ProposePatchArgs,
    ProposePatchTool,
    WriteFileArgs,
    WriteFileTool,
)


@pytest.mark.unit
async def test_tool_registry_permissions() -> None:
    registry = ToolRegistry([ReadFileTool(), WriteFileTool()])

    # READ_ONLY allows ReadFileTool, rejects WriteFileTool
    assert "read_file" in registry.tool_names(READ_ONLY)
    assert "write_file" not in registry.tool_names(READ_ONLY)

    with pytest.raises(PolicyViolationError):
        registry.check("write_file", READ_ONLY)

    write_perms = PermissionSet.of(Permission.READ, Permission.WRITE)
    assert "write_file" in registry.tool_names(write_perms)
    assert registry.check("write_file", write_perms).name == "write_file"


@pytest.mark.unit
async def test_filesystem_tools(temp_workspace: Path, test_settings: Settings) -> None:
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.CODEBASE,
        workspace=temp_workspace,
        settings=test_settings,
    )

    read_tool = ReadFileTool()
    res = await read_tool.run(ReadFileArgs(path="src/calculator.py"), ctx)
    assert res.ok is True
    assert "def add" in res.output

    # Credential read attempt should fail
    env_file = temp_workspace / ".env"
    env_file.write_text("SECRET=123", encoding="utf-8")
    env_res = await read_tool.run(ReadFileArgs(path=".env"), ctx)
    assert env_res.ok is False
    assert "credential" in env_res.error.lower()

    list_tool = ListFilesTool()
    l_res = await list_tool.run(ListFilesArgs(path="."), ctx)
    assert l_res.ok is True
    assert "src/calculator.py" in l_res.output


@pytest.mark.unit
async def test_search_in_files_tool(temp_workspace: Path, test_settings: Settings) -> None:
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.CODEBASE,
        workspace=temp_workspace,
        settings=test_settings,
    )

    search_tool = SearchInFilesTool()
    res = await search_tool.run(SearchInFilesArgs(query="def add"), ctx)
    assert res.ok is True
    assert "calculator.py:1: def add" in res.output


@pytest.mark.unit
async def test_write_and_patch_tools(temp_workspace: Path, test_settings: Settings) -> None:
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=TaskStatus.APPLYING,
    )

    write_tool = WriteFileTool()
    w_res = await write_tool.run(WriteFileArgs(path="src/utils.py", content="def util(): pass\n"), ctx)
    assert w_res.ok is True
    assert (temp_workspace / "src" / "utils.py").exists()

    patch_tool = ApplyPatchTool()
    p_res = await patch_tool.run(
        ApplyPatchArgs(path="src/utils.py", old_str="def util(): pass", new_str="def util(): return 42"), ctx
    )
    assert p_res.ok is True
    assert "return 42" in (temp_workspace / "src" / "utils.py").read_text(encoding="utf-8")


@pytest.mark.unit
async def test_awaiting_approval_write_rejection(temp_workspace: Path, test_settings: Settings) -> None:
    """Requirement 9.1: Write attempts during AWAITING_APPROVAL must be rejected."""
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=TaskStatus.AWAITING_APPROVAL,
    )
    registry = ToolRegistry([WriteFileTool(), ApplyPatchTool()])
    capabilities = PermissionSet.of(Permission.READ, Permission.WRITE)

    # 1. Direct tool invocation rejected
    w_res = await WriteFileTool().run(WriteFileArgs(path="src/sneaky.py", content="evil"), ctx)
    assert w_res.ok is False
    assert "APPLYING" in w_res.error
    assert not (temp_workspace / "src" / "sneaky.py").exists()

    # 2. Registry execution rejected with PolicyViolationError
    with pytest.raises(PolicyViolationError) as exc_info:
        await registry.execute("write_file", {"path": "src/sneaky.py", "content": "evil"}, ctx, capabilities)
    assert "APPLYING" in str(exc_info.value)
    assert not (temp_workspace / "src" / "sneaky.py").exists()

    # 3. ApplyPatch rejected
    p_res = await ApplyPatchTool().run(
        ApplyPatchArgs(path="src/calculator.py", old_str="def add", new_str="def sub"), ctx
    )
    assert p_res.ok is False
    assert "APPLYING" in p_res.error


@pytest.mark.unit
async def test_forged_write_permission_rejection(temp_workspace: Path, test_settings: Settings) -> None:
    """Requirement 9.2: Forged WRITE permission in non-APPLYING states must not modify workspace."""
    non_applying_statuses = [
        TaskStatus.CREATED,
        TaskStatus.PLANNING,
        TaskStatus.ANALYZING,
        TaskStatus.INVESTIGATING,
        TaskStatus.FIX_PROPOSED,
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.TESTING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.REJECTED,
        None,
    ]
    registry = ToolRegistry([WriteFileTool(), ApplyPatchTool()])
    forged_capabilities = PermissionSet.of(Permission.READ, Permission.WRITE, Permission.EXECUTE)

    for st in non_applying_statuses:
        ctx = ToolContext(
            task_id=uuid.uuid4(),
            agent=AgentName.DEBUGGER,
            workspace=temp_workspace,
            settings=test_settings,
            task_status=st,
        )
        target_name = f"src/forged_{st.value if st else 'none'}.py"
        with pytest.raises(PolicyViolationError) as exc_info:
            await registry.execute(
                "write_file",
                {"path": target_name, "content": "hacked"},
                ctx,
                forged_capabilities,
            )
        assert "APPLYING" in str(exc_info.value)
        assert not (temp_workspace / target_name).exists()


@pytest.mark.unit
async def test_direct_write_tool_rejection(temp_workspace: Path, test_settings: Settings) -> None:
    """Requirement 9.3: Directly calling write-capable tools outside APPLYING must fail."""
    ctx_no_status = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=None,
    )
    w_res1 = await WriteFileTool().run(WriteFileArgs(path="src/direct.py", content="content"), ctx_no_status)
    assert w_res1.ok is False
    assert "APPLYING" in w_res1.error
    assert not (temp_workspace / "src" / "direct.py").exists()

    ctx_investigating = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=TaskStatus.INVESTIGATING,
    )
    p_res1 = await ApplyPatchTool().run(
        ApplyPatchArgs(path="src/calculator.py", old_str="def add", new_str="def modified"), ctx_investigating
    )
    assert p_res1.ok is False
    assert "APPLYING" in p_res1.error
    assert "def add" in (temp_workspace / "src" / "calculator.py").read_text(encoding="utf-8")


@pytest.mark.unit
async def test_path_traversal_rejection(temp_workspace: Path, test_settings: Settings) -> None:
    """Requirement 9.4: Path traversal attempts must be rejected for all write/apply operations."""
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=TaskStatus.APPLYING,
    )

    write_tool = WriteFileTool()
    traversal_paths = [
        "../escape.py",
        "../../escape.py",
        "src/../../escape.py",
        "src/subdir/../../../escape.py",
    ]
    for path in traversal_paths:
        res = await write_tool.run(WriteFileArgs(path=path, content="evil"), ctx)
        assert res.ok is False
        assert "traversal" in res.error.lower() or "escapes" in res.error.lower() or "not allowed" in res.error.lower()

    patch_tool = ApplyPatchTool()
    for path in traversal_paths:
        res = await patch_tool.run(ApplyPatchArgs(path=path, old_str="a", new_str="b"), ctx)
        assert res.ok is False
        assert "traversal" in res.error.lower() or "escapes" in res.error.lower() or "not allowed" in res.error.lower()

    propose_tool = ProposePatchTool()
    for path in traversal_paths:
        res = await propose_tool.run(ProposePatchArgs(path=path, old_str="", new_str="evil", is_new_file=True), ctx)
        assert res.ok is False
        assert "traversal" in res.error.lower() or "escapes" in res.error.lower() or "not allowed" in res.error.lower()


@pytest.mark.unit
async def test_absolute_path_rejection(temp_workspace: Path, test_settings: Settings) -> None:
    """Requirement 9.5: Absolute paths must be rejected for all write/apply operations."""
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=TaskStatus.APPLYING,
    )

    write_tool = WriteFileTool()
    absolute_paths = [
        "/etc/passwd",
        "/var/log/syslog",
        "C:/Windows/System32/cmd.exe",
        "D:\\data\\file.txt",
    ]
    for path in absolute_paths:
        res = await write_tool.run(WriteFileArgs(path=path, content="evil"), ctx)
        assert res.ok is False
        assert "absolute" in res.error.lower() or "not allowed" in res.error.lower()

    patch_tool = ApplyPatchTool()
    for path in absolute_paths:
        res = await patch_tool.run(ApplyPatchArgs(path=path, old_str="a", new_str="b"), ctx)
        assert res.ok is False
        assert "absolute" in res.error.lower() or "not allowed" in res.error.lower()


@pytest.mark.unit
async def test_authorized_applying_write_path(temp_workspace: Path, test_settings: Settings) -> None:
    """Requirement 9.6: Authorized APPLYING write path succeeds within workspace."""
    ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent=AgentName.DEBUGGER,
        workspace=temp_workspace,
        settings=test_settings,
        task_status=TaskStatus.APPLYING,
    )
    registry = ToolRegistry([WriteFileTool(), ApplyPatchTool()])
    capabilities = PermissionSet.of(Permission.READ, Permission.WRITE)

    # 1. Write new file via registry
    w_res = await registry.execute(
        "write_file",
        {"path": "src/module.py", "content": "def run():\n    return 10\n"},
        ctx,
        capabilities,
    )
    assert w_res.ok is True
    target_file = temp_workspace / "src" / "module.py"
    assert target_file.exists()
    assert "return 10" in target_file.read_text(encoding="utf-8")

    # 2. Apply patch via registry
    p_res = await registry.execute(
        "apply_patch",
        {"path": "src/module.py", "old_str": "return 10", "new_str": "return 20"},
        ctx,
        capabilities,
    )
    assert p_res.ok is True
    assert "return 20" in target_file.read_text(encoding="utf-8")
