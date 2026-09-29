"""Generates a reproducible buggy fixture git repository for testing DevAgent."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent
REPO_DIR = FIXTURES_DIR / "buggy-auth-service"


def build_repo() -> None:
    if REPO_DIR.exists():
        shutil.rmtree(REPO_DIR)
    REPO_DIR.mkdir(parents=True, exist_ok=True)

    # 1. pyproject.toml
    pyproject_content = """[project]
name = "buggy-auth-service"
version = "0.1.0"
description = "Sample buggy authentication microservice for DevAgent integration tests"
dependencies = []

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
"""
    (REPO_DIR / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")

    # 2. README.md
    readme_content = """# Buggy Auth Service
Sample service with an intentional permission validation bug in `src/auth.py`.
"""
    (REPO_DIR / "README.md").write_text(readme_content, encoding="utf-8")

    # 3. Source code with the bug
    src_dir = REPO_DIR / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    auth_py_content = '''"""Authentication and role-based access control."""

from __future__ import annotations

import time

ROLES = {"admin", "editor", "viewer"}


class AuthService:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, str]] = {}
        self.tokens: dict[str, dict[str, float | str]] = {}

    def register(self, username: str, role: str = "viewer") -> None:
        if role not in ROLES:
            raise ValueError(f"Invalid role: {role}")
        self.users[username] = {"role": role}

    def authenticate(self, username: str) -> str:
        if username not in self.users:
            raise ValueError("User not found")
        token = f"tok_{username}_{int(time.time())}"
        self.tokens[token] = {"username": username, "expires_at": time.time() + 3600}
        return token

    def check_permission(self, token: str, required_role: str) -> bool:
        """Validate if token holder has the required role.

        BUG: Checks '>' instead of '>=' or permission hierarchy!
        'admin' should have access to 'editor' and 'viewer' operations.
        Currently strictly matches exact role only or fails.
        """
        token_info = self.tokens.get(token)
        if not token_info:
            return False

        if time.time() > float(token_info["expires_at"]):
            return False

        user = self.users.get(str(token_info["username"]))
        if not user:
            return False

        user_role = user["role"]
        hierarchy = {"viewer": 1, "editor": 2, "admin": 3}
        # Intentional Bug: strict inequality instead of >=
        return hierarchy.get(user_role, 0) > hierarchy.get(required_role, 0)
'''
    (src_dir / "auth.py").write_text(auth_py_content, encoding="utf-8")

    # 4. Tests
    test_dir = REPO_DIR / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_py_content = '''"""Tests for the auth service."""

import pytest
from src.auth import AuthService


def test_permission_hierarchy():
    service = AuthService()
    service.register("alice", role="admin")
    service.register("bob", role="editor")
    service.register("charlie", role="viewer")

    alice_token = service.authenticate("alice")
    bob_token = service.authenticate("bob")
    charlie_token = service.authenticate("charlie")

    # Admin should have access to admin, editor, and viewer
    assert service.check_permission(alice_token, "admin") is True  # Fails due to strict > bug!
    assert service.check_permission(alice_token, "editor") is True
    assert service.check_permission(alice_token, "viewer") is True

    # Editor should have access to editor and viewer
    assert service.check_permission(bob_token, "editor") is True   # Fails due to strict > bug!
    assert service.check_permission(bob_token, "viewer") is True
    assert service.check_permission(bob_token, "admin") is False

    # Viewer should have access to viewer only
    assert service.check_permission(charlie_token, "viewer") is True # Fails due to strict > bug!
    assert service.check_permission(charlie_token, "editor") is False
'''
    (test_dir / "test_auth.py").write_text(test_py_content, encoding="utf-8")

    # 5. Initialize git repository
    try:
        subprocess.run(["git", "init"], cwd=str(REPO_DIR), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "devagent@example.com"], cwd=str(REPO_DIR), check=True)
        subprocess.run(["git", "config", "user.name", "DevAgent Bot"], cwd=str(REPO_DIR), check=True)
        subprocess.run(["git", "add", "."], cwd=str(REPO_DIR), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit with buggy auth service"], cwd=str(REPO_DIR), check=True, capture_output=True)
        print(f"Successfully generated fixture git repository at {REPO_DIR}")
    except Exception as exc:
        print(f"Warning: git init failed: {exc}")


if __name__ == "__main__":
    build_repo()
