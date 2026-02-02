"""Tests for MCP server initialization and lifespan management."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_pg.server import AppContext, app_lifespan, mcp
from mcp.server.fastmcp import FastMCP


class TestServerInstance:
    """Tests for the module-level MCP server instance."""

    def test_mcp_is_fastmcp_instance(self) -> None:
        """Test that mcp is a FastMCP instance."""
        assert isinstance(mcp, FastMCP)

    def test_mcp_server_name(self) -> None:
        """Test that server name is correctly set."""
        assert mcp.name == "PostgreSQL MCP Server"

    def test_mcp_has_lifespan(self) -> None:
        """Test that server has a lifespan configured."""
        assert mcp.settings.lifespan is app_lifespan


class TestAppContext:
    """Tests for the AppContext dataclass."""

    def test_has_engine_field(self) -> None:
        """Test that AppContext has an engine field."""
        engine = MagicMock()
        settings = MagicMock()
        ctx = AppContext(engine=engine, settings=settings)
        assert ctx.engine is engine

    def test_has_settings_field(self) -> None:
        """Test that AppContext has a settings field."""
        engine = MagicMock()
        settings = MagicMock()
        ctx = AppContext(engine=engine, settings=settings)
        assert ctx.settings is settings


class TestAppLifespan:
    """Tests for the app_lifespan async context manager."""

    async def test_creates_engine_and_yields_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that lifespan creates engine and yields AppContext on success."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "testpass")

        mock_engine = AsyncMock()
        mock_server = MagicMock(spec=FastMCP)

        with (
            patch("mamba_mcp_pg.server.create_engine", return_value=mock_engine) as mock_create,
            patch("mamba_mcp_pg.server.test_connection") as mock_test,
            patch("mamba_mcp_pg.server.dispose_engine") as mock_dispose,
        ):
            async with app_lifespan(mock_server) as ctx:
                assert isinstance(ctx, AppContext)
                assert ctx.engine is mock_engine
                assert ctx.settings.database.db_name == "testdb"
                mock_create.assert_called_once()
                mock_test.assert_called_once_with(mock_engine)

            mock_dispose.assert_called_once_with(mock_engine)

    async def test_disposes_engine_on_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that engine is disposed when context manager exits normally."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "testpass")

        mock_engine = AsyncMock()
        mock_server = MagicMock(spec=FastMCP)

        with (
            patch("mamba_mcp_pg.server.create_engine", return_value=mock_engine),
            patch("mamba_mcp_pg.server.test_connection"),
            patch("mamba_mcp_pg.server.dispose_engine") as mock_dispose,
        ):
            async with app_lifespan(mock_server):
                mock_dispose.assert_not_called()

            mock_dispose.assert_called_once_with(mock_engine)

    async def test_raises_system_exit_on_connection_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that SystemExit(1) is raised when connection test fails."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "testpass")

        mock_engine = AsyncMock()
        mock_server = MagicMock(spec=FastMCP)

        with (
            patch("mamba_mcp_pg.server.create_engine", return_value=mock_engine),
            patch(
                "mamba_mcp_pg.server.test_connection",
                side_effect=Exception("Connection refused"),
            ),
            patch("mamba_mcp_pg.server.dispose_engine") as mock_dispose,
        ):
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server):
                    pass  # pragma: no cover

            assert exc_info.value.code == 1
            mock_dispose.assert_called_once_with(mock_engine)

    async def test_disposes_engine_when_yield_body_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that engine is disposed even if code inside the context raises."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "testpass")

        mock_engine = AsyncMock()
        mock_server = MagicMock(spec=FastMCP)

        with (
            patch("mamba_mcp_pg.server.create_engine", return_value=mock_engine),
            patch("mamba_mcp_pg.server.test_connection"),
            patch("mamba_mcp_pg.server.dispose_engine") as mock_dispose,
        ):
            with pytest.raises(RuntimeError, match="something broke"):
                async with app_lifespan(mock_server):
                    raise RuntimeError("something broke")

            mock_dispose.assert_called_once_with(mock_engine)
