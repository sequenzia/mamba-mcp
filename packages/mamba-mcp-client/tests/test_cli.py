"""Tests for CLI validation and configuration building."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from mamba_mcp_client.cli import build_config, validate_connection_options
from mamba_mcp_client.config import TransportType


class TestValidateConnectionOptions:
    """Tests for validate_connection_options()."""

    def test_no_connection_method_raises(self) -> None:
        """Test that no connection method raises BadParameter."""
        with pytest.raises(typer.BadParameter, match="Must specify a connection method"):
            validate_connection_options(
                stdio=None,
                sse=None,
                http=None,
                uv=None,
                uv_local_path=None,
                uv_local_name=None,
            )

    def test_multiple_methods_raises(self) -> None:
        """Test that multiple connection methods raise BadParameter."""
        with pytest.raises(typer.BadParameter, match="Only one connection method"):
            validate_connection_options(
                stdio="python server.py",
                sse="http://localhost:8000/sse",
                http=None,
                uv=None,
                uv_local_path=None,
                uv_local_name=None,
            )

    def test_stdio_and_uv_raises(self) -> None:
        """Test that stdio + uv raises BadParameter."""
        with pytest.raises(typer.BadParameter, match="Only one connection method"):
            validate_connection_options(
                stdio="python server.py",
                sse=None,
                http=None,
                uv="mcp-server-fs",
                uv_local_path=None,
                uv_local_name=None,
            )

    def test_uv_local_path_without_name_raises(self) -> None:
        """Test that --uv-local-path without --uv-local-name raises."""
        with pytest.raises(
            typer.BadParameter, match="--uv-local-path and --uv-local-name must be used together"
        ):
            validate_connection_options(
                stdio=None,
                sse=None,
                http=None,
                uv=None,
                uv_local_path=Path("/path/to/server"),
                uv_local_name=None,
            )

    def test_uv_local_name_without_path_raises(self) -> None:
        """Test that --uv-local-name without --uv-local-path raises."""
        with pytest.raises(
            typer.BadParameter, match="--uv-local-path and --uv-local-name must be used together"
        ):
            validate_connection_options(
                stdio=None,
                sse=None,
                http=None,
                uv=None,
                uv_local_path=None,
                uv_local_name="my-server",
            )

    def test_valid_stdio(self) -> None:
        """Test that single stdio method passes validation."""
        validate_connection_options(
            stdio="python server.py",
            sse=None,
            http=None,
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
        )

    def test_valid_sse(self) -> None:
        """Test that single SSE method passes validation."""
        validate_connection_options(
            stdio=None,
            sse="http://localhost:8000/sse",
            http=None,
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
        )

    def test_valid_http(self) -> None:
        """Test that single HTTP method passes validation."""
        validate_connection_options(
            stdio=None,
            sse=None,
            http="http://localhost:8000/mcp",
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
        )

    def test_valid_uv(self) -> None:
        """Test that single UV method passes validation."""
        validate_connection_options(
            stdio=None,
            sse=None,
            http=None,
            uv="mcp-server-filesystem",
            uv_local_path=None,
            uv_local_name=None,
        )

    def test_valid_uv_local(self) -> None:
        """Test that uv-local-path + uv-local-name together passes validation."""
        validate_connection_options(
            stdio=None,
            sse=None,
            http=None,
            uv=None,
            uv_local_path=Path("/path/to/server"),
            uv_local_name="my-server",
        )


class TestBuildConfig:
    """Tests for build_config()."""

    def test_build_stdio_config(self) -> None:
        """Test building config from stdio options."""
        config = build_config(
            stdio="python server.py --verbose",
            sse=None,
            http=None,
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
            python_version=None,
            with_packages=None,
            timeout=30.0,
        )
        assert config.transport_type == TransportType.STDIO
        assert config.stdio is not None
        assert config.stdio.command == "python"
        assert config.stdio.args == ["server.py", "--verbose"]

    def test_build_stdio_config_with_extra_args(self) -> None:
        """Test building stdio config passes extra_args."""
        config = build_config(
            stdio="python server.py",
            sse=None,
            http=None,
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
            python_version=None,
            with_packages=None,
            timeout=30.0,
            extra_args=["--port", "8080"],
        )
        assert config.extra_args == ["--port", "8080"]

    def test_build_sse_config(self) -> None:
        """Test building config from SSE options."""
        config = build_config(
            stdio=None,
            sse="http://localhost:8000/sse",
            http=None,
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
            python_version=None,
            with_packages=None,
            timeout=60.0,
        )
        assert config.transport_type == TransportType.SSE
        assert config.http is not None
        assert config.http.url == "http://localhost:8000/sse"
        assert config.http.timeout == 60.0

    def test_build_http_config(self) -> None:
        """Test building config from HTTP options."""
        config = build_config(
            stdio=None,
            sse=None,
            http="http://localhost:8000/mcp",
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
            python_version=None,
            with_packages=None,
            timeout=45.0,
        )
        assert config.transport_type == TransportType.HTTP
        assert config.http is not None
        assert config.http.url == "http://localhost:8000/mcp"

    def test_build_uv_installed_config(self) -> None:
        """Test building config from UV-installed options."""
        config = build_config(
            stdio=None,
            sse=None,
            http=None,
            uv="mcp-server-filesystem",
            uv_local_path=None,
            uv_local_name=None,
            python_version="3.11",
            with_packages=["httpx"],
            timeout=30.0,
        )
        assert config.transport_type == TransportType.UV_INSTALLED
        assert config.uv_installed is not None
        assert config.uv_installed.server_name == "mcp-server-filesystem"
        assert config.uv_installed.python_version == "3.11"
        assert config.uv_installed.with_packages == ["httpx"]

    def test_build_uv_local_config(self) -> None:
        """Test building config from UV-local options."""
        config = build_config(
            stdio=None,
            sse=None,
            http=None,
            uv=None,
            uv_local_path=Path("/path/to/my-server"),
            uv_local_name="my-mcp",
            python_version="3.12",
            with_packages=None,
            timeout=30.0,
        )
        assert config.transport_type == TransportType.UV_LOCAL
        assert config.uv_local is not None
        assert config.uv_local.project_path == "/path/to/my-server"
        assert config.uv_local.server_name == "my-mcp"
        assert config.uv_local.python_version == "3.12"

    def test_build_no_method_raises(self) -> None:
        """Test that build_config raises when no method specified."""
        with pytest.raises(ValueError, match="No connection method"):
            build_config(
                stdio=None,
                sse=None,
                http=None,
                uv=None,
                uv_local_path=None,
                uv_local_name=None,
                python_version=None,
                with_packages=None,
                timeout=30.0,
            )

    def test_build_stdio_shlex_splitting(self) -> None:
        """Test that stdio command is properly split with shlex."""
        config = build_config(
            stdio='python -m my_server --config "path with spaces/config.json"',
            sse=None,
            http=None,
            uv=None,
            uv_local_path=None,
            uv_local_name=None,
            python_version=None,
            with_packages=None,
            timeout=30.0,
        )
        assert config.stdio is not None
        assert config.stdio.command == "python"
        assert config.stdio.args == ["-m", "my_server", "--config", "path with spaces/config.json"]

    def test_build_uv_installed_no_packages(self) -> None:
        """Test that None with_packages passes through to factory (normalizes to empty)."""
        config = build_config(
            stdio=None,
            sse=None,
            http=None,
            uv="mcp-server-git",
            uv_local_path=None,
            uv_local_name=None,
            python_version=None,
            with_packages=None,
            timeout=30.0,
        )
        assert config.uv_installed is not None
        # Factory normalizes None -> [] via `with_packages or []`
        assert config.uv_installed.with_packages == []
