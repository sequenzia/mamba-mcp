"""Configuration management for the SAP HANA MCP Server.

Uses pydantic-settings to load configuration from environment variables
and .env files. Based on spec Sections 5.5, 13.4.

Three settings classes handle different configuration scopes:
- DatabaseSettings: HANA connection, pool, and query settings
- ServerSettings: MCP server transport and logging
- Settings: Root combining all configuration with nested delimiter support

Supports cascading env file resolution: explicit path > ./mamba.env > ~/mamba.env
Auto-detects TLS encryption when port is 443 (HANA Cloud).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, model_validator
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


def resolve_env_file(explicit_path: str | None) -> str | None:
    """Resolve env file path with cascading fallback.

    Resolution order:
    1. Explicit path (if provided) - raises FileNotFoundError if not found
    2. ./mamba.env (current working directory)
    3. ~/mamba.env (home directory)
    4. None (no env file)

    Args:
        explicit_path: Explicitly provided env file path, or None.

    Returns:
        Resolved env file path, or None if no env file found.

    Raises:
        FileNotFoundError: If an explicit path is provided but does not exist or is not a file.
    """
    if explicit_path is not None:
        resolved = Path(explicit_path).resolve()
        if not resolved.exists():
            msg = f"Environment file not found: {explicit_path}"
            raise FileNotFoundError(msg)
        if not resolved.is_file():
            msg = f"Environment file path is not a file: {explicit_path}"
            raise FileNotFoundError(msg)
        return str(resolved)

    # Check ./mamba.env
    cwd_env = Path.cwd() / "mamba.env"
    if cwd_env.is_file():
        return str(cwd_env.resolve())

    # Check ~/mamba.env
    home_env = Path.home() / "mamba.env"
    if home_env.is_file():
        return str(home_env.resolve())

    return None


class DatabaseSettings(BaseSettings):
    """SAP HANA database connection configuration.

    Loaded from MAMBA_MCP_HANA_* environment variables or mamba.env file.

    Supports two authentication modes:
    - User/password: DB_USER + DB_PASSWORD (standard)
    - hdbuserstore key: DB_USERKEY (alternative, no user/password needed)

    When both are provided, user/password takes precedence.
    Auto-detects TLS encryption when port is 443 (HANA Cloud).
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_HANA_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = Field(default="localhost", description="HANA server hostname")
    db_port: int = Field(default=30015, ge=1, le=65535, description="HANA server port")
    db_name: str | None = Field(
        default=None, description="Tenant database name (optional, for tenant routing)"
    )
    db_user: str | None = Field(default=None, description="Database username")
    db_password: SecretStr | None = Field(default=None, description="Database password")
    db_encrypt: bool | None = Field(
        default=None, description="Enable TLS encryption (auto-true for port 443)"
    )
    db_ssl_validate: bool = Field(default=True, description="Validate SSL certificate")
    db_userkey: str | None = Field(
        default=None, description="hdbuserstore key (alternative to user/password)"
    )

    # Connection pool settings
    pool_size: int = Field(default=5, ge=1, le=20, description="Connection pool size (1-20)")
    pool_timeout: float = Field(
        default=30.0, gt=0, description="Pool connection acquire timeout in seconds"
    )

    # Query settings
    statement_timeout: int = Field(
        default=30000, ge=1000, description="Query timeout in milliseconds"
    )
    default_schema: str | None = Field(default=None, description="Default schema for tool queries")

    @model_validator(mode="after")
    def validate_auth_and_tls(self) -> DatabaseSettings:
        """Validate authentication credentials and auto-detect TLS.

        - Either db_userkey or (db_user + db_password) must be provided.
        - Auto-enables TLS when port is 443 (HANA Cloud) unless manually overridden.
        """
        has_userkey = self.db_userkey is not None
        has_credentials = self.db_user is not None and self.db_password is not None

        if not has_userkey and not has_credentials:
            msg = (
                "Authentication required: provide either DB_USER and DB_PASSWORD, "
                "or DB_USERKEY for hdbuserstore authentication."
            )
            raise ValueError(msg)

        # Auto-detect TLS for HANA Cloud (port 443)
        if self.db_encrypt is None:
            object.__setattr__(self, "db_encrypt", self.db_port == 443)

        return self

    @property
    def effective_encrypt(self) -> bool:
        """Get the effective encryption setting (after auto-detection)."""
        if self.db_encrypt is None:
            return self.db_port == 443
        return self.db_encrypt


class ServerSettings(BaseSettings):
    """MCP server configuration.

    Loaded from MAMBA_MCP_HANA_* environment variables or mamba.env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_HANA_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: str = Field(
        default="stdio",
        pattern=r"^(stdio|http)$",
        description="Transport type (stdio or http)",
    )
    server_host: str = Field(default="0.0.0.0", description="HTTP server bind host")
    server_port: int = Field(default=8080, ge=1, le=65535, description="HTTP server bind port")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json",
        pattern=r"^(json|text)$",
        description="Log output format (json or text)",
    )


class Settings(BaseSettings):
    """Root settings combining all configuration.

    Supports nested delimiter ``__`` for environment variables
    (e.g., ``MAMBA_MCP_HANA_DB__HOST``).
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
    )

    database: DatabaseSettings = Field(default=None)  # type: ignore[assignment]
    server: ServerSettings = Field(default=None)  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def load_nested_settings(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Load nested settings with the configured env file path."""
        env_file = _env_file_path
        if "database" not in data or data["database"] is None:
            data["database"] = DatabaseSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "server" not in data or data["server"] is None:
            data["server"] = ServerSettings(_env_file=env_file)  # type: ignore[call-arg]
        return data


def get_settings() -> Settings:
    """Factory function to create settings instance."""
    return Settings()
