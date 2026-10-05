"""Unit tests for password hashing and JWT token handling."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.errors import UnauthenticatedError, ValidationError
from app.core.security import (
    TokenIssuer,
    constant_time_equals,
    hash_password,
    validate_password_strength,
    verify_password,
)


@pytest.mark.unit
def test_password_strength_validation() -> None:
    # Too short
    with pytest.raises(ValidationError):
        validate_password_strength("Short1!", min_length=10)

    # All alpha without numbers or symbols
    with pytest.raises(ValidationError):
        validate_password_strength("passwordsecret", min_length=10)

    # Valid
    validate_password_strength("SuperSecretP@ssword2026", min_length=10)


@pytest.mark.unit
def test_password_hashing_and_verification() -> None:
    pw = "CorrectBatteryHorseStaple99!"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False
    assert verify_password(pw, None) is False


@pytest.mark.unit
def test_jwt_token_issue_and_decode() -> None:
    issuer = TokenIssuer(secret="test-secret-12345678901234567890")
    user_id = uuid.uuid4()
    pair = issuer.issue_pair(user_id=user_id, token_version=2)

    assert pair.access_token
    assert pair.refresh_token

    claims = issuer.decode(pair.access_token, expected_type="access")
    assert claims.subject == str(user_id)
    assert claims.token_type == "access"
    assert claims.token_version == 2

    # Refresh token should fail when decoded as access token
    with pytest.raises(UnauthenticatedError, match="Invalid token type"):
        issuer.decode(pair.refresh_token, expected_type="access")


@pytest.mark.unit
def test_constant_time_equals() -> None:
    assert constant_time_equals("abc123xyz", "abc123xyz") is True
    assert constant_time_equals("abc123xyz", "abc123xyw") is False


@pytest.mark.unit
def test_null_byte_path_rejection() -> None:
    from app.core.paths import normalize_relative_path

    with pytest.raises(ValidationError, match="illegal character"):
        normalize_relative_path("src/sneaky\x00file.py")


@pytest.mark.unit
def test_symlink_and_workspace_containment(tmp_path: Path) -> None:
    from app.core.paths import ensure_within

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside_file = workspace / "allowed.py"
    inside_file.write_text("ok")

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("secret")

    # Valid inside path
    assert ensure_within(workspace, inside_file) == inside_file.resolve()

    # Symlink pointing outside workspace root must raise PolicyViolationError
    link_to_outside = workspace / "link_escape.py"
    try:
        link_to_outside.symlink_to(outside_file)
        from app.core.errors import PolicyViolationError

        with pytest.raises(PolicyViolationError):
            ensure_within(workspace, link_to_outside)
    except OSError:
        # On Windows without developer mode/admin symlink creation may require privilege, skip if OS denies symlink creation
        pass
