"""Configuration management for the GitLab MCP Server.

Uses pydantic-settings to load configuration from environment variables
and .env files. Based on spec Section 7.6, following mamba-mcp-pg patterns.

Five settings classes handle different configuration scopes:
- GitLabSettings: GitLab instance connection and auth token
- OAuthSettings: OAuth 2.0 client credentials
- ServerSettings: MCP server transport and logging
- RateLimitSettings: Client-side rate limiting
- Settings: Root combining all configuration with nested delimiter support
"""

from __future__ import annotations

from typing import Any

from mamba_mcp_core.config import get_env_file_path, set_env_file_path
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Re-export for backward compatibility
__all__ = ["get_env_file_path", "set_env_file_path", "get_settings", "Settings"]


class GitLabSettings(BaseSettings):
    """GitLab instance connection configuration.

    Loaded from MAMBA_MCP_GITLAB_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_GITLAB_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(..., description="GitLab instance URL (e.g., https://gitlab.example.com)")
    token: SecretStr | None = Field(default=None, description="Personal Access Token")
    verify_ssl: bool = Field(default=True, description="SSL certificate verification")
    default_project_id: int | None = Field(
        default=None, description="Optional default project scope"
    )
    default_group_id: int | None = Field(default=None, description="Optional default group scope")
    read_only: bool = Field(default=False, description="Read-only mode flag")

    @field_validator("url", mode="before")
    @classmethod
    def validate_url_not_empty(cls, v: str | None) -> str:
        """Validate that url is a non-empty string."""
        if v is None or (isinstance(v, str) and v.strip() == ""):
            msg = "url must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("default_project_id", "default_group_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: int | str | None) -> int | str | None:
        """Treat empty strings as None for optional integer fields."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class OAuthSettings(BaseSettings):
    """OAuth 2.0 client configuration.

    Loaded from MAMBA_MCP_GITLAB_OAUTH_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_GITLAB_OAUTH_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str | None = Field(default=None, description="OAuth 2.0 client ID")
    client_secret: SecretStr | None = Field(default=None, description="OAuth 2.0 client secret")
    redirect_uri: str | None = Field(default=None, description="OAuth 2.0 redirect URI")

    @field_validator("client_id", "redirect_uri", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: str | None) -> str | None:
        """Treat empty strings as None for optional string fields."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class ServerSettings(BaseSettings):
    """MCP server configuration.

    Loaded from MAMBA_MCP_GITLAB_SERVER_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_GITLAB_SERVER_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: str = Field(
        default="stdio",
        pattern=r"^(stdio|http|streamable-http)$",
        description="Transport type (stdio, http, or streamable-http)",
    )
    server_host: str = Field(default="127.0.0.1", description="HTTP server bind host")
    server_port: int = Field(default=8004, ge=1, le=65535, description="HTTP server bind port")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="text",
        pattern=r"^(json|text)$",
        description="Log output format (json or text)",
    )
    max_connections: int = Field(
        default=10, ge=1, le=100, description="Maximum concurrent HTTP connections"
    )


class RateLimitSettings(BaseSettings):
    """Client-side rate limiting configuration.

    Loaded from MAMBA_MCP_GITLAB_RATE_LIMIT_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_GITLAB_RATE_LIMIT_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_requests: int = Field(default=100, ge=1, description="Maximum requests per time window")
    window_seconds: int = Field(
        default=60, ge=1, description="Time window in seconds for rate limiting"
    )


class Settings(BaseSettings):
    """Root settings combining all configuration.

    Supports nested delimiter ``__`` for environment variables
    (e.g., ``MAMBA_MCP_GITLAB_SERVER__TRANSPORT``).
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
    )

    gitlab: GitLabSettings = Field(default=None)  # type: ignore[assignment]
    oauth: OAuthSettings = Field(default=None)  # type: ignore[assignment]
    server: ServerSettings = Field(default=None)  # type: ignore[assignment]
    rate_limit: RateLimitSettings = Field(default=None)  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def load_nested_settings(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Load nested settings with the configured env file path."""
        env_file = get_env_file_path()
        if "gitlab" not in data or data["gitlab"] is None:
            data["gitlab"] = GitLabSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "oauth" not in data or data["oauth"] is None:
            data["oauth"] = OAuthSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "server" not in data or data["server"] is None:
            data["server"] = ServerSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "rate_limit" not in data or data["rate_limit"] is None:
            data["rate_limit"] = RateLimitSettings(_env_file=env_file)  # type: ignore[call-arg]
        return data


def get_settings() -> Settings:
    """Factory function to create settings instance."""
    return Settings()
