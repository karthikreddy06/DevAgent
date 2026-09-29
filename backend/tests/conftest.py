"""Global pytest fixtures."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.security import TokenIssuer

# Test environment settings
os.environ["ENV"] = "test"
os.environ["ALLOW_DEV_PROVIDERS"] = "true"
os.environ["ALLOW_LOCAL_REPO_IMPORT"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key-1234567890"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-1234567890"


@pytest.fixture
def temp_workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        # Create a sample workspace
        src_dir = ws / "src"
        src_dir.mkdir()
        (src_dir / "calculator.py").write_text(
            'def add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n\n'
            "def subtract(a: int, b: int) -> int:\n    return a - b\n",
            encoding="utf-8",
        )
        (ws / "README.md").write_text("# Test Repo\nThis is a sample repository.", encoding="utf-8")
        yield ws


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        env="test",
        secret_key="test-secret-key-1234567890",
        jwt_secret="test-jwt-secret-key-1234567890",
        allow_dev_providers=True,
        allow_local_repo_import=True,
    )


@pytest.fixture
def token_issuer(test_settings: Settings) -> TokenIssuer:
    return TokenIssuer.from_settings(test_settings)
