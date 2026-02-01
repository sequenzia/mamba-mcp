"""Configuration management for the Filesystem MCP Server.

Uses pydantic-settings to load configuration from environment variables
and .env files. Based on spec Section 7.4, following mamba-mcp-pg patterns.

Three settings classes handle different configuration scopes:
- ServerSettings: MCP server transport, logging, permissions, rate limiting
- LocalSettings: Local filesystem backend configuration
- S3Settings: S3 backend configuration
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Module-level state for env file path
_env_file_path: str | None = None


def set_env_file_path(path: str | None) -> None:
    """Set the env file path for settings to use.

    Args:
        path: Path to .env file, or None to use default (mamba.env in current directory).
    """
    global _env_file_path
    _env_file_path = path


def get_env_file_path() -> str | None:
    """Get the currently configured env file path.

    Returns:
        The configured env file path, or None if using default.
    """
    return _env_file_path


class ServerSettings(BaseSettings):
    """MCP server configuration.

    Loaded from MAMBA_MCP_FS_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_FS_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: str = Field(
        default="stdio",
        pattern=r"^(stdio|streamable-http)$",
        description="Transport type (stdio or streamable-http)",
    )
    server_host: str = Field(default="0.0.0.0", description="HTTP server host")
    server_port: int = Field(default=8080, ge=1, le=65535, description="HTTP server port")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json",
        pattern=r"^(json|text)$",
        description="Log output format (json or text)",
    )
    read_only: bool = Field(default=True, description="Disable mutation tools when True")
    rate_limit: int = Field(default=0, ge=0, description="Operations per minute, 0=disabled")
    allowed_extensions: str | None = Field(
        default=None, description="Comma-separated allowlist of file extensions"
    )
    denied_extensions: str | None = Field(
        default=None, description="Comma-separated denylist of file extensions"
    )

    @field_validator("allowed_extensions", "denied_extensions", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: str | None) -> str | None:
        """Treat empty strings as None for extension lists."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @property
    def parsed_allowed_extensions(self) -> set[str] | None:
        """Parse comma-separated allowed extensions into a set.

        Returns None if no allowed extensions are configured.
        Each extension is stripped of whitespace and lowercased.
        """
        if self.allowed_extensions is None:
            return None
        parts = {ext.strip().lower() for ext in self.allowed_extensions.split(",")}
        parts.discard("")
        return parts if parts else None

    @property
    def parsed_denied_extensions(self) -> set[str] | None:
        """Parse comma-separated denied extensions into a set.

        Returns None if no denied extensions are configured.
        Each extension is stripped of whitespace and lowercased.
        """
        if self.denied_extensions is None:
            return None
        parts = {ext.strip().lower() for ext in self.denied_extensions.split(",")}
        parts.discard("")
        return parts if parts else None


class LocalSettings(BaseSettings):
    """Local filesystem backend configuration.

    Loaded from MAMBA_MCP_FS_LOCAL_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_FS_LOCAL_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(default=True, description="Enable local filesystem backend")
    base_path: str = Field(..., description="Sandbox root directory (required)")
    max_file_size: int = Field(
        default=10_485_760, description="Max file size in bytes (default 10MB)"
    )
    follow_symlinks: bool = Field(default=False, description="Follow symbolic links")
    show_hidden: bool = Field(default=False, description="Show hidden files/dotfiles")

    @field_validator("base_path")
    @classmethod
    def validate_base_path_not_empty(cls, v: str) -> str:
        """Validate that base_path is a non-empty string."""
        if not v or not v.strip():
            msg = "base_path must not be empty"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_base_path_exists(self) -> LocalSettings:
        """Validate that base_path exists when local backend is enabled."""
        if self.enabled:
            resolved = Path(self.base_path).resolve()
            if not resolved.exists():
                msg = (
                    f"base_path does not exist: {self.base_path}. "
                    "Create the directory or set MAMBA_MCP_FS_LOCAL_ENABLED=false."
                )
                raise ValueError(msg)
            if not resolved.is_dir():
                msg = (
                    f"base_path is not a directory: {self.base_path}. "
                    "Provide a valid directory path."
                )
                raise ValueError(msg)
        return self


class S3Settings(BaseSettings):
    """S3 backend configuration.

    Loaded from MAMBA_MCP_FS_S3_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_FS_S3_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(default=False, description="Enable S3 backend")
    bucket: str | None = Field(default=None, description="Default S3 bucket")
    prefix: str = Field(default="", description="Key prefix within bucket")
    region: str = Field(default="us-east-1", description="AWS region")
    endpoint_url: str | None = Field(
        default=None, description="Custom endpoint URL (for MinIO/LocalStack)"
    )
    max_file_size: int = Field(
        default=52_428_800, description="Max file size in bytes (default 50MB)"
    )


class Settings(BaseSettings):
    """Root settings combining all configuration."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
    )

    server: ServerSettings = Field(default=None)  # type: ignore[assignment]
    local: LocalSettings = Field(default=None)  # type: ignore[assignment]
    s3: S3Settings = Field(default=None)  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def load_nested_settings(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Load nested settings with the configured env file path."""
        env_file = _env_file_path
        if "server" not in data or data["server"] is None:
            data["server"] = ServerSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "local" not in data or data["local"] is None:
            data["local"] = LocalSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "s3" not in data or data["s3"] is None:
            data["s3"] = S3Settings(_env_file=env_file)  # type: ignore[call-arg]
        return data


def get_settings() -> Settings:
    """Factory function to create settings instance."""
    return Settings()
