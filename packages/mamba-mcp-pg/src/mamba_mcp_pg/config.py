"""Configuration management using pydantic-settings."""

from typing import Any

from mamba_mcp_core.config import get_env_file_path, set_env_file_path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Re-export for backward compatibility
__all__ = ["get_env_file_path", "set_env_file_path", "get_settings", "Settings"]


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_PG_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = Field(default="localhost", description="Database host")
    db_port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    db_name: str = Field(..., description="Database name")
    db_user: str = Field(..., description="Database user")
    db_password: SecretStr = Field(..., description="Database password")

    # Connection pool settings
    pool_size: int = Field(default=5, ge=1, le=20, description="Connection pool size")
    pool_timeout: float = Field(
        default=30.0, gt=0, description="Pool connection timeout in seconds"
    )

    # Query settings
    statement_timeout: int = Field(
        default=30000, ge=1000, description="Statement timeout in milliseconds"
    )
    default_schema: str = Field(default="public", description="Default schema for operations")

    @property
    def async_url(self) -> str:
        """Build async connection URL for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.db_user}:"
            f"{self.db_password.get_secret_value()}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )


class ServerSettings(BaseSettings):
    """MCP server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_PG_",
        env_file="mamba.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: str = Field(
        default="stdio",
        pattern=r"^(stdio|http|streamable-http)$",
        description="Transport type",
    )
    server_host: str = Field(default="0.0.0.0", description="HTTP server host")
    server_port: int = Field(default=8080, ge=1, le=65535, description="HTTP server port")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json", pattern="^(json|text)$", description="Log output format"
    )


class Settings(BaseSettings):
    """Root settings combining all configuration."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
    )

    database: DatabaseSettings = Field(default=None)  # type: ignore[assignment]
    server: ServerSettings = Field(default=None)  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def load_nested_settings(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Load nested settings with the configured env file path."""
        env_file = get_env_file_path()
        if "database" not in data or data["database"] is None:
            # _env_file is a valid pydantic-settings init parameter
            data["database"] = DatabaseSettings(_env_file=env_file)  # type: ignore[call-arg]
        if "server" not in data or data["server"] is None:
            data["server"] = ServerSettings(_env_file=env_file)  # type: ignore[call-arg]
        return data


def get_settings() -> Settings:
    """Factory function to create settings instance."""
    return Settings()
