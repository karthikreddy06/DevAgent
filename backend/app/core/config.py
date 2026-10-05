"""Application settings.

All configuration comes from environment variables (optionally through a
``.env`` file). Secrets are held in :class:`pydantic.SecretStr` so they cannot be
printed by accident, and are only read through the explicit ``*_value`` helpers.
"""

from __future__ import annotations

import functools
import secrets
import urllib.parse
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Env = Literal["development", "test", "production"]
LogFormat = Literal["json", "console"]
LLMProviderName = Literal["openai", "anthropic", "ollama", "replay"]
EmbeddingProviderName = Literal["openai", "ollama", "hashing"]

DEV_ONLY_LLM_PROVIDERS: frozenset[str] = frozenset({"replay"})
DEV_ONLY_EMBEDDING_PROVIDERS: frozenset[str] = frozenset({"hashing"})


class Settings(BaseSettings):
    """Runtime configuration. Instantiate through :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------- app
    env: Env = "development"
    debug: bool = False
    app_name: str = "DevAgent"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    log_format: LogFormat = "console"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080", "http://localhost:8010"]
    )

    # -------------------------------------------------------------- security
    secret_key: SecretStr = SecretStr("devagent-insecure-development-key")
    jwt_secret: SecretStr = SecretStr("devagent-insecure-development-jwt-key")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    password_min_length: int = 10

    # --------------------------------------------------------------- storage
    database_url: str = "postgresql+asyncpg://devagent:devagent@localhost:5432/devagent"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    db_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    workspaces_dir: Path = Path("data/workspaces")
    artifacts_dir: Path = Path("data/artifacts")

    # ------------------------------------------------------------------- llm
    llm_provider: LLMProviderName = "openai"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.1
    llm_max_output_tokens: int = 4096
    dev_llm_script: str | None = None
    allow_dev_providers: bool = False

    # ------------------------------------------------------------- retrieval
    embedding_provider: EmbeddingProviderName = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 64
    retrieval_vector_k: int = 40
    retrieval_fts_k: int = 40
    retrieval_top_n: int = 12
    context_token_budget: int = 8000

    # ---------------------------------------------------------------- github
    github_token: SecretStr | None = None
    github_api_base: str = "https://api.github.com"
    allowed_git_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["github.com"])

    # ------------------------------------------------------------- ingestion
    allow_local_repo_import: bool = False
    local_import_roots: Annotated[list[Path], NoDecode] = Field(default_factory=lambda: [Path("./fixtures")])
    max_repo_size_mb: int = 100
    clone_timeout_seconds: int = 300
    clone_depth: int = 50
    index_max_files: int = 3000
    index_max_file_bytes: int = 400_000

    # ---------------------------------------------------------------- agents
    agent_max_steps: int = 18
    agent_max_tool_calls: int = 36
    agent_max_tokens: int = 150_000
    agent_timeout_seconds: int = 900
    task_timeout_seconds: int = 900
    max_fix_attempts: int = 3

    # --------------------------------------------------------------- sandbox
    sandbox_enabled: bool = True
    sandbox_image: str = "devagent/runner-python:3.12"
    sandbox_max_seconds: int = 300
    sandbox_cpus: float = 1.0
    sandbox_mem_mb: int = 1024
    sandbox_pids_limit: int = 256
    sandbox_network: str = "none"
    sandbox_output_limit_bytes: int = 1_048_576
    sandbox_allow_network_install: bool = False
    sandbox_ttl_seconds: int = 3600
    max_concurrent_sandboxes: int = 2

    # --------------------------------------------------------- rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10

    # ------------------------------------------------------------ validators
    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str):
            val = value.strip()
            while val.startswith("DATABASE_URL="):
                val = val[len("DATABASE_URL=") :].strip()
            val = val.strip("\"'")
            if val.startswith("postgres://"):
                val = "postgresql+asyncpg://" + val[len("postgres://") :]
            elif val.startswith("postgresql://") and not val.startswith("postgresql+"):
                val = "postgresql+asyncpg://" + val[len("postgresql://") :]
            if "://" in val:
                scheme, rest = val.split("://", 1)
                if "@" in rest:
                    userinfo, host_part = rest.rsplit("@", 1)
                    if ":" in userinfo:
                        user, pwd = userinfo.split(":", 1)
                        safe_user = urllib.parse.quote(urllib.parse.unquote(user), safe="")
                        safe_pwd = urllib.parse.quote(urllib.parse.unquote(pwd), safe="")
                        rest = f"{safe_user}:{safe_pwd}@{host_part}"
                    else:
                        safe_user = urllib.parse.quote(urllib.parse.unquote(userinfo), safe="")
                        rest = f"{safe_user}@{host_part}"
                    val = f"{scheme}://{rest}"
            if "sslmode=" in val:
                val = val.replace("sslmode=", "ssl=")
            return val
        return value

    @field_validator("cors_origins", "allowed_git_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("local_import_roots", mode="before")
    @classmethod
    def _split_paths(cls, value: object) -> object:
        if isinstance(value, str):
            return [Path(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_security_posture(self) -> Settings:
        """Fail fast on unsafe or impossible configurations."""
        if self.env == "production":
            if self.allow_dev_providers:
                raise ValueError("ALLOW_DEV_PROVIDERS must be false when ENV=production")
            if self.llm_provider in DEV_ONLY_LLM_PROVIDERS:
                raise ValueError(f"LLM_PROVIDER={self.llm_provider} is dev-only and forbidden when ENV=production")
            if self.embedding_provider in DEV_ONLY_EMBEDDING_PROVIDERS:
                raise ValueError(
                    f"EMBEDDING_PROVIDER={self.embedding_provider} is dev-only and forbidden when ENV=production"
                )
            if self.secret_key.get_secret_value().startswith("devagent-insecure"):
                raise ValueError("SECRET_KEY must be set to a real secret when ENV=production")
            if self.jwt_secret.get_secret_value().startswith("devagent-insecure"):
                raise ValueError("JWT_SECRET must be set to a real secret when ENV=production")
            if self.debug:
                raise ValueError("DEBUG must be false when ENV=production")
        # Provider credentials are validated when a provider is constructed
        # (app/llm/factory.py) rather than here, so the API can boot and report
        # "provider not configured" instead of refusing to start at all.
        if self.llm_provider in DEV_ONLY_LLM_PROVIDERS and not self.allow_dev_providers:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider} is a dev-only non-AI stub; set ALLOW_DEV_PROVIDERS=true to use it"
            )
        if self.embedding_provider in DEV_ONLY_EMBEDDING_PROVIDERS and not self.allow_dev_providers:
            raise ValueError(
                f"EMBEDDING_PROVIDER={self.embedding_provider} is a dev-only non-semantic stub; "
                "set ALLOW_DEV_PROVIDERS=true to use it"
            )
        return self

    # --------------------------------------------------------------- helpers
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_test(self) -> bool:
        return self.env == "test"

    @property
    def secret_key_value(self) -> str:
        return self.secret_key.get_secret_value()

    @property
    def jwt_secret_value(self) -> str:
        return self.jwt_secret.get_secret_value()

    @property
    def llm_api_key_value(self) -> str | None:
        return self.llm_api_key.get_secret_value() if self.llm_api_key else None

    @property
    def github_token_value(self) -> str | None:
        return self.github_token.get_secret_value() if self.github_token else None

    @property
    def uses_dev_llm_provider(self) -> bool:
        """True when the configured LLM is a clearly labelled dev-only stub."""
        return self.llm_provider in DEV_ONLY_LLM_PROVIDERS

    @property
    def uses_dev_embedding_provider(self) -> bool:
        return self.embedding_provider in DEV_ONLY_EMBEDDING_PROVIDERS

    def task_queue_name(self) -> str:
        return "devagent:tasks"

    def event_channel(self, task_id: str) -> str:
        return f"devagent:events:task:{task_id}"

    def ensure_directories(self) -> None:
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def public_config(self) -> dict[str, object]:
        """Non-sensitive configuration that is safe to expose to the browser."""
        return {
            "app_name": self.app_name,
            "env": self.env,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "sandbox_enabled": self.sandbox_enabled,
            "sandbox_image": self.sandbox_image,
            "dev_providers_in_use": self.uses_dev_llm_provider or self.uses_dev_embedding_provider,
            "local_repo_import_enabled": self.allow_local_repo_import,
            "max_fix_attempts": self.max_fix_attempts,
        }


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor (import-safe, does not touch the filesystem)."""
    return Settings()


def generate_secret() -> str:
    """Mint a new secret value (used by docs and scripts)."""
    return secrets.token_urlsafe(48)
