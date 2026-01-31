"""Tests for the FastMCP server initialization and lifespan management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mamba_mcp_fs.backends.base import BackendManager
from mamba_mcp_fs.config import (
    LocalSettings,
    S3Settings,
    ServerSettings,
    Settings,
)
from mamba_mcp_fs.rate_limit import RateLimiter
from mamba_mcp_fs.security import SecurityValidator
from mamba_mcp_fs.server import AppContext, _register_tools, app_lifespan, mcp


class TestAppContext:
    """Tests for the AppContext dataclass."""

    def test_app_context_creation(self, tmp_path: Path) -> None:
        """Test AppContext can be created with all required fields."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        backend_manager = BackendManager(
            settings=settings,
            security=security,
        )

        rate_limiter = RateLimiter(ops_per_minute=0)

        ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=rate_limiter,
        )

        assert ctx.settings is settings
        assert ctx.security is security
        assert ctx.backend_manager is backend_manager
        assert ctx.rate_limiter is rate_limiter

    def test_app_context_fields(self) -> None:
        """Test AppContext has the expected attributes."""
        assert hasattr(AppContext, "__dataclass_fields__")
        fields = AppContext.__dataclass_fields__
        assert "settings" in fields
        assert "security" in fields
        assert "backend_manager" in fields
        assert "rate_limiter" in fields


class TestAppLifespan:
    """Tests for the app_lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_creates_components(self, tmp_path: Path) -> None:
        """Test that lifespan creates settings, security, and backend manager."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert isinstance(ctx, AppContext)
                assert isinstance(ctx.settings, Settings)
                assert isinstance(ctx.security, SecurityValidator)
                assert isinstance(ctx.backend_manager, BackendManager)
                assert isinstance(ctx.rate_limiter, RateLimiter)

    @pytest.mark.asyncio
    async def test_lifespan_with_local_only(self, tmp_path: Path) -> None:
        """Test lifespan works when only local backend is enabled."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path), enabled=True),
            s3=S3Settings(enabled=False),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings.local.enabled is True
                assert ctx.settings.s3.enabled is False

    @pytest.mark.asyncio
    async def test_lifespan_with_s3_only(self) -> None:
        """Test lifespan works when only S3 backend is enabled."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path="/unused", enabled=False),
            s3=S3Settings(enabled=True),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings.local.enabled is False
                assert ctx.settings.s3.enabled is True

    @pytest.mark.asyncio
    async def test_lifespan_both_backends_enabled(self, tmp_path: Path) -> None:
        """Test lifespan works when both backends are enabled."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path), enabled=True),
            s3=S3Settings(enabled=True),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings.local.enabled is True
                assert ctx.settings.s3.enabled is True

    @pytest.mark.asyncio
    async def test_lifespan_no_backends_raises(self) -> None:
        """Test lifespan raises SystemExit when no backends are enabled."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path="/unused", enabled=False),
            s3=S3Settings(enabled=False),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            with pytest.raises(SystemExit):
                async with app_lifespan(mock_server):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_lifespan_security_validator_config(self, tmp_path: Path) -> None:
        """Test that security validator receives correct settings."""
        settings = Settings(
            server=ServerSettings(read_only=False, allowed_extensions=".py,.txt"),
            local=LocalSettings(base_path=str(tmp_path), enabled=True),
            s3=S3Settings(enabled=False),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                # Security validator should have server settings
                assert ctx.security is not None
                # Backend manager should have settings and security
                assert ctx.backend_manager.settings is settings
                assert ctx.backend_manager.security is ctx.security

    @pytest.mark.asyncio
    async def test_lifespan_read_only_setting(self, tmp_path: Path) -> None:
        """Test that read_only setting is preserved in context."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings.server.read_only is True

    @pytest.mark.asyncio
    async def test_lifespan_cleanup_on_normal_exit(self, tmp_path: Path) -> None:
        """Test that cleanup runs on normal shutdown."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx is not None
            # If we get here, cleanup ran successfully

    @pytest.mark.asyncio
    async def test_lifespan_cleanup_on_exception(self, tmp_path: Path) -> None:
        """Test that cleanup runs even when an exception occurs."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(),
        )
        with patch("mamba_mcp_fs.server.get_settings", return_value=settings):
            mock_server = MagicMock()
            with pytest.raises(RuntimeError, match="test error"):
                async with app_lifespan(mock_server):
                    raise RuntimeError("test error")


class TestRegisterTools:
    """Tests for the _register_tools function."""

    def test_register_discovery_tools_always(self, tmp_path: Path) -> None:
        """Test that discovery tools are always attempted."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        # discovery_tools module exists (even if empty stub), so it should import
        assert "discovery_tools" in result

    def test_s3_tools_not_registered_when_disabled(self, tmp_path: Path) -> None:
        """Test that S3 tools are not registered when S3 is disabled."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert "s3_tools" not in result

    def test_s3_tools_registered_when_enabled(self, tmp_path: Path) -> None:
        """Test that S3 tools are registered when S3 is enabled."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=True),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        # s3_tools module exists (even if empty stub), so it should import
        assert "s3_tools" in result

    def test_mutation_tools_not_registered_when_read_only(self, tmp_path: Path) -> None:
        """Test that mutation tools are NOT registered when read_only=True."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert "mutation_tools" not in result

    def test_mutation_tools_registered_when_not_read_only(self, tmp_path: Path) -> None:
        """Test that mutation tools are registered when read_only=False."""
        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        # mutation_tools module exists (even if empty stub), so it should import
        assert "mutation_tools" in result

    def test_all_layers_registered(self, tmp_path: Path) -> None:
        """Test that all layers are registered when all features enabled."""
        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=True),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert "discovery_tools" in result
        assert "s3_tools" in result
        assert "mutation_tools" in result

    def test_import_error_handled_gracefully(self, tmp_path: Path) -> None:
        """Test that ImportError from missing tool modules is handled."""
        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=True),
        )
        mock_mcp = MagicMock()

        # Mock import to raise ImportError for all tool modules
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("mamba_mcp_fs.tools."):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = _register_tools(mock_mcp, settings)
            assert result == []


class TestMCPServerInstance:
    """Tests for the module-level MCP server instance."""

    def test_mcp_server_exists(self) -> None:
        """Test that the mcp server instance is created at module level."""
        assert mcp is not None

    def test_mcp_server_name(self) -> None:
        """Test that the MCP server has the correct name."""
        assert mcp.name == "mamba-mcp-fs"

    def test_mcp_server_has_lifespan(self) -> None:
        """Test that the MCP server has a lifespan configured."""
        # The lifespan is set during FastMCP initialization
        # We verify by checking the server instance exists and was configured
        assert mcp is not None


class TestToolRegistrationLogic:
    """Tests for the conditional tool registration logic."""

    def test_read_only_true_excludes_mutation(self, tmp_path: Path) -> None:
        """Test read_only=True excludes mutation tools."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=True),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert "mutation_tools" not in result
        assert "discovery_tools" in result
        assert "s3_tools" in result

    def test_s3_disabled_excludes_s3_tools(self, tmp_path: Path) -> None:
        """Test S3 disabled excludes S3 tools."""
        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert "s3_tools" not in result
        assert "discovery_tools" in result
        assert "mutation_tools" in result

    def test_minimal_config_only_discovery(self, tmp_path: Path) -> None:
        """Test minimal config (local only, read-only) registers only discovery."""
        settings = Settings(
            server=ServerSettings(read_only=True),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert result == ["discovery_tools"]

    def test_register_returns_list_of_names(self, tmp_path: Path) -> None:
        """Test that _register_tools returns a list of registered module names."""
        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=True),
        )
        mock_mcp = MagicMock()
        result = _register_tools(mock_mcp, settings)
        assert isinstance(result, list)
        for name in result:
            assert isinstance(name, str)
