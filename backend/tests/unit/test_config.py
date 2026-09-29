"""Unit tests for Settings and configuration."""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.mark.unit
def test_settings_initialization() -> None:
    settings = Settings(
        env="test",
        secret_key="some-secret-key-1234567890",
        jwt_secret="some-jwt-secret-key-1234567890",
    )
    assert settings.env == "test"
    assert settings.is_test is True
    assert settings.is_production is False
    assert settings.app_name == "DevAgent"
    assert settings.task_queue_name() == "devagent:tasks"


@pytest.mark.unit
def test_production_safety_checks() -> None:
    # In production, insecure default keys must be rejected
    with pytest.raises(ValueError, match="SECRET_KEY must be set to a real secret"):
        Settings(
            env="production",
            allow_dev_providers=False,
            secret_key="devagent-insecure-development-key",
            jwt_secret="devagent-insecure-development-jwt-key",
        )


@pytest.mark.unit
def test_public_config() -> None:
    settings = Settings(
        env="test",
        secret_key="some-secret-key-1234567890",
        jwt_secret="some-jwt-secret-key-1234567890",
    )
    pub = settings.public_config()
    assert "secret_key" not in pub
    assert "jwt_secret" not in pub
    assert pub["app_name"] == "DevAgent"
    assert pub["env"] == "test"
