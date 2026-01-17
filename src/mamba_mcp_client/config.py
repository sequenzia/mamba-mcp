"""Configuration management for mamba-mcp-client using pydantic-settings."""

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TransportType(str, Enum):
    """Supported MCP transport types."""

    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"
    UV_INSTALLED = "uv_installed"
    UV_LOCAL = "uv_local"


class StdioConfig(BaseModel):
    """Configuration for stdio transport."""

    command: str = Field(..., description="Command to run the MCP server")
    args: list[str] = Field(default_factory=list, description="Arguments for the command")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")


class HttpConfig(BaseModel):
    """Configuration for HTTP-based transports (SSE and Streamable HTTP)."""

    url: str = Field(..., description="URL of the MCP server")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")
    timeout: float = Field(default=30.0, description="Request timeout in seconds")


class UvInstalledConfig(BaseModel):
    """Configuration for UV-installed MCP server (runs via 'uv run <server-name>')."""

    server_name: str = Field(..., description="Name of the UV-installed server")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to server")
    python_version: str | None = Field(default=None, description="Python version (e.g., '3.11')")
    with_packages: list[str] = Field(default_factory=list, description="Additional packages")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")


class UvLocalConfig(BaseModel):
    """Configuration for local UV-based MCP server (uvx --from /path <server-name>)."""

    project_path: str = Field(..., description="Path to the local MCP server project")
    server_name: str = Field(..., description="Name of the server entry point")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to server")
    python_version: str | None = Field(default=None, description="Python version (e.g., '3.11')")
    with_packages: list[str] = Field(default_factory=list, description="Additional packages")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")


class LogConfig(BaseModel):
    """Configuration for logging."""

    enabled: bool = Field(default=True, description="Enable request/response logging")
    level: str = Field(default="INFO", description="Log level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )
    log_file: Path | None = Field(default=None, description="Log file path (optional)")
    log_requests: bool = Field(default=True, description="Log outgoing requests")
    log_responses: bool = Field(default=True, description="Log incoming responses")


class ClientConfig(BaseSettings):
    """Main configuration for the MCP test client."""

    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Transport configuration
    transport_type: TransportType = Field(
        default=TransportType.STDIO,
        description="Type of transport to use",
    )

    # Stdio configuration (for stdio transport)
    stdio: StdioConfig | None = Field(default=None, description="Stdio transport configuration")

    # HTTP configuration (for SSE and HTTP transports)
    http: HttpConfig | None = Field(default=None, description="HTTP transport configuration")

    # UV-installed configuration (for uv run <server-name>)
    uv_installed: UvInstalledConfig | None = Field(
        default=None, description="UV-installed server configuration"
    )

    # UV-local configuration (for uvx --from /path <server-name>)
    uv_local: UvLocalConfig | None = Field(
        default=None, description="Local UV-based server configuration"
    )

    # Logging configuration
    logging: LogConfig = Field(default_factory=LogConfig, description="Logging configuration")

    # Client metadata
    client_name: str = Field(default="mamba-mcp-client", description="Client name")
    client_version: str = Field(default="1.0.0", description="Client version")

    @classmethod
    def for_stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> "ClientConfig":
        """Create a configuration for stdio transport."""
        return cls(
            transport_type=TransportType.STDIO,
            stdio=StdioConfig(
                command=command,
                args=args or [],
                env=env or {},
            ),
            **kwargs,
        )

    @classmethod
    def for_sse(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> "ClientConfig":
        """Create a configuration for SSE transport."""
        return cls(
            transport_type=TransportType.SSE,
            http=HttpConfig(
                url=url,
                headers=headers or {},
                timeout=timeout,
            ),
            **kwargs,
        )

    @classmethod
    def for_http(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> "ClientConfig":
        """Create a configuration for Streamable HTTP transport."""
        return cls(
            transport_type=TransportType.HTTP,
            http=HttpConfig(
                url=url,
                headers=headers or {},
                timeout=timeout,
            ),
            **kwargs,
        )

    @classmethod
    def for_uv_installed(
        cls,
        server_name: str,
        args: list[str] | None = None,
        python_version: str | None = None,
        with_packages: list[str] | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> "ClientConfig":
        """Create a configuration for UV-installed MCP server (runs via 'uv run <server-name>')."""
        return cls(
            transport_type=TransportType.UV_INSTALLED,
            uv_installed=UvInstalledConfig(
                server_name=server_name,
                args=args or [],
                python_version=python_version,
                with_packages=with_packages or [],
                env=env or {},
            ),
            **kwargs,
        )

    @classmethod
    def for_uv_local(
        cls,
        project_path: str,
        server_name: str,
        args: list[str] | None = None,
        python_version: str | None = None,
        with_packages: list[str] | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> "ClientConfig":
        """Create a configuration for local UV-based MCP server."""
        return cls(
            transport_type=TransportType.UV_LOCAL,
            uv_local=UvLocalConfig(
                project_path=project_path,
                server_name=server_name,
                args=args or [],
                python_version=python_version,
                with_packages=with_packages or [],
                env=env or {},
            ),
            **kwargs,
        )
