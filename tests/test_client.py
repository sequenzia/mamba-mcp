"""Tests for the MCPTestClient."""

import pytest

from mamba_mcp_client.client import MCPTestClient, ServerCapabilities, ServerInfo
from mamba_mcp_client.config import (
    ClientConfig,
    TransportType,
    UvInstalledConfig,
    UvLocalConfig,
)


class TestClientConfig:
    """Tests for ClientConfig."""

    def test_for_stdio(self) -> None:
        """Test creating stdio configuration."""
        config = ClientConfig.for_stdio(
            command="python",
            args=["server.py"],
            env={"API_KEY": "test"},
        )
        assert config.transport_type == TransportType.STDIO
        assert config.stdio is not None
        assert config.stdio.command == "python"
        assert config.stdio.args == ["server.py"]
        assert config.stdio.env == {"API_KEY": "test"}

    def test_for_sse(self) -> None:
        """Test creating SSE configuration."""
        config = ClientConfig.for_sse(
            url="http://localhost:8000/sse",
            headers={"Authorization": "Bearer token"},
            timeout=60.0,
        )
        assert config.transport_type == TransportType.SSE
        assert config.http is not None
        assert config.http.url == "http://localhost:8000/sse"
        assert config.http.headers == {"Authorization": "Bearer token"}
        assert config.http.timeout == 60.0

    def test_for_http(self) -> None:
        """Test creating HTTP configuration."""
        config = ClientConfig.for_http(
            url="http://localhost:8000/mcp",
            timeout=30.0,
        )
        assert config.transport_type == TransportType.HTTP
        assert config.http is not None
        assert config.http.url == "http://localhost:8000/mcp"

    def test_for_uv_installed(self) -> None:
        """Test creating UV-installed configuration."""
        config = ClientConfig.for_uv_installed(
            server_name="mcp-server-filesystem",
            args=["--root", "/tmp"],
            python_version="3.11",
            with_packages=["httpx"],
            env={"DEBUG": "1"},
        )
        assert config.transport_type == TransportType.UV_INSTALLED
        assert config.uv_installed is not None
        assert config.uv_installed.server_name == "mcp-server-filesystem"
        assert config.uv_installed.args == ["--root", "/tmp"]
        assert config.uv_installed.python_version == "3.11"
        assert config.uv_installed.with_packages == ["httpx"]
        assert config.uv_installed.env == {"DEBUG": "1"}

    def test_for_uv_installed_minimal(self) -> None:
        """Test creating UV-installed configuration with minimal options."""
        config = ClientConfig.for_uv_installed(server_name="mcp-server-git")
        assert config.transport_type == TransportType.UV_INSTALLED
        assert config.uv_installed is not None
        assert config.uv_installed.server_name == "mcp-server-git"
        assert config.uv_installed.args == []
        assert config.uv_installed.python_version is None
        assert config.uv_installed.with_packages == []
        assert config.uv_installed.env == {}

    def test_for_uv_local(self) -> None:
        """Test creating UV-local configuration."""
        config = ClientConfig.for_uv_local(
            project_path="/path/to/my-server",
            server_name="my-mcp",
            args=["--verbose"],
            python_version="3.12",
            with_packages=["pydantic", "httpx"],
            env={"API_KEY": "test"},
        )
        assert config.transport_type == TransportType.UV_LOCAL
        assert config.uv_local is not None
        assert config.uv_local.project_path == "/path/to/my-server"
        assert config.uv_local.server_name == "my-mcp"
        assert config.uv_local.args == ["--verbose"]
        assert config.uv_local.python_version == "3.12"
        assert config.uv_local.with_packages == ["pydantic", "httpx"]
        assert config.uv_local.env == {"API_KEY": "test"}

    def test_for_uv_local_minimal(self) -> None:
        """Test creating UV-local configuration with minimal options."""
        config = ClientConfig.for_uv_local(
            project_path="./my-server",
            server_name="my-mcp",
        )
        assert config.transport_type == TransportType.UV_LOCAL
        assert config.uv_local is not None
        assert config.uv_local.project_path == "./my-server"
        assert config.uv_local.server_name == "my-mcp"
        assert config.uv_local.args == []
        assert config.uv_local.python_version is None
        assert config.uv_local.with_packages == []
        assert config.uv_local.env == {}


class TestUvConfigModels:
    """Tests for UV config models."""

    def test_uv_installed_config(self) -> None:
        """Test UvInstalledConfig model."""
        config = UvInstalledConfig(
            server_name="mcp-server-filesystem",
            args=["--root", "/tmp"],
            python_version="3.11",
            with_packages=["httpx"],
            env={"DEBUG": "1"},
        )
        assert config.server_name == "mcp-server-filesystem"
        assert config.args == ["--root", "/tmp"]
        assert config.python_version == "3.11"
        assert config.with_packages == ["httpx"]
        assert config.env == {"DEBUG": "1"}

    def test_uv_local_config(self) -> None:
        """Test UvLocalConfig model."""
        config = UvLocalConfig(
            project_path="/path/to/my-server",
            server_name="my-mcp",
            args=["--verbose"],
            python_version="3.12",
            with_packages=["pydantic"],
            env={"API_KEY": "test"},
        )
        assert config.project_path == "/path/to/my-server"
        assert config.server_name == "my-mcp"
        assert config.args == ["--verbose"]
        assert config.python_version == "3.12"
        assert config.with_packages == ["pydantic"]
        assert config.env == {"API_KEY": "test"}


class TestMCPTestClient:
    """Tests for MCPTestClient."""

    def test_create_client(self) -> None:
        """Test creating a client."""
        config = ClientConfig.for_stdio(command="python", args=["server.py"])
        client = MCPTestClient(config)
        assert client.config == config
        assert not client.connected
        assert client.server_info is None

    def test_not_connected_raises(self) -> None:
        """Test that operations fail when not connected."""
        config = ClientConfig.for_stdio(command="python", args=["server.py"])
        client = MCPTestClient(config)

        with pytest.raises(RuntimeError, match="not connected"):
            client._ensure_connected()


class TestServerCapabilities:
    """Tests for ServerCapabilities."""

    def test_defaults(self) -> None:
        """Test default capability values."""
        caps = ServerCapabilities()
        assert caps.tools is False
        assert caps.resources is False
        assert caps.prompts is False
        assert caps.logging is False
        assert caps.experimental == {}


class TestServerInfo:
    """Tests for ServerInfo."""

    def test_create(self) -> None:
        """Test creating server info."""
        info = ServerInfo(
            name="test-server",
            version="1.0.0",
            protocol_version="2024-11-05",
            instructions="Test instructions",
        )
        assert info.name == "test-server"
        assert info.version == "1.0.0"
        assert info.protocol_version == "2024-11-05"
        assert info.instructions == "Test instructions"


class TestExtraArgs:
    """Tests for extra_args functionality."""

    def test_stdio_config_with_extra_args(self) -> None:
        """Test that extra_args is stored in stdio config."""
        config = ClientConfig.for_stdio(
            command="python",
            args=["server.py"],
            extra_args=["--verbose", "--port", "8080"],
        )
        assert config.extra_args == ["--verbose", "--port", "8080"]

    def test_sse_config_with_extra_args(self) -> None:
        """Test that extra_args is stored in SSE config."""
        config = ClientConfig.for_sse(
            url="http://localhost:8000/sse",
            extra_args=["env=prod", "debug=true"],
        )
        assert config.extra_args == ["env=prod", "debug=true"]

    def test_http_config_with_extra_args(self) -> None:
        """Test that extra_args is stored in HTTP config."""
        config = ClientConfig.for_http(
            url="http://localhost:8000/mcp",
            extra_args=["key=value"],
        )
        assert config.extra_args == ["key=value"]

    def test_uv_installed_config_with_extra_args(self) -> None:
        """Test that extra_args is stored in UV-installed config."""
        config = ClientConfig.for_uv_installed(
            server_name="mcp-server-fs",
            extra_args=["--root", "/home/user"],
        )
        assert config.extra_args == ["--root", "/home/user"]

    def test_uv_local_config_with_extra_args(self) -> None:
        """Test that extra_args is stored in UV-local config."""
        config = ClientConfig.for_uv_local(
            project_path="./my-server",
            server_name="my-mcp",
            extra_args=["--config", "prod.json"],
        )
        assert config.extra_args == ["--config", "prod.json"]

    def test_extra_args_default_empty(self) -> None:
        """Test that extra_args defaults to empty list."""
        config = ClientConfig.for_stdio(command="python", args=["server.py"])
        assert config.extra_args == []

    def test_extra_args_combined_with_stdio_args(self) -> None:
        """Test that extra_args are combined with stdio args in transport."""
        config = ClientConfig.for_stdio(
            command="python",
            args=["server.py"],
            extra_args=["--verbose", "--port", "8080"],
        )
        client = MCPTestClient(config)
        transport = client._create_transport()

        # StdioTransport should have combined args
        assert transport.args == ["server.py", "--verbose", "--port", "8080"]

    def test_query_params_appended_to_url(self) -> None:
        """Test that extra_args become query params for SSE/HTTP."""
        result = MCPTestClient._append_query_params(
            "http://localhost:8000/sse",
            ["env=prod", "debug=true"],
        )
        assert result == "http://localhost:8000/sse?env=prod&debug=true"

    def test_query_params_merged_with_existing(self) -> None:
        """Test that existing query params are preserved."""
        result = MCPTestClient._append_query_params(
            "http://localhost:8000/sse?token=abc",
            ["env=prod"],
        )
        # Order may vary, check both params are present
        assert "token=abc" in result
        assert "env=prod" in result

    def test_bare_args_become_true(self) -> None:
        """Test that bare args become arg=true query params."""
        result = MCPTestClient._append_query_params(
            "http://localhost:8000/sse",
            ["debug", "verbose"],
        )
        assert "debug=true" in result
        assert "verbose=true" in result

    def test_empty_extra_args_no_change(self) -> None:
        """Test that empty extra_args doesn't modify URL."""
        url = "http://localhost:8000/sse"
        result = MCPTestClient._append_query_params(url, [])
        assert result == url
