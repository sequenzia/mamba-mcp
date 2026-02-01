"""Tests for FastMCP server initialization and lifespan management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_sap_hana.server import SERVER_NAME, AppContext, app_lifespan, mcp


class TestServerInstance:
    """Tests for the FastMCP server instance."""

    def test_server_name(self) -> None:
        """Test server is created with correct name."""
        assert mcp.name == SERVER_NAME

    def test_server_name_value(self) -> None:
        """Test server name is 'mamba-mcp-hana'."""
        assert SERVER_NAME == "mamba-mcp-hana"

    def test_server_has_lifespan(self) -> None:
        """Test server has lifespan configured."""
        # FastMCP wraps the lifespan internally; verify via low-level server
        assert mcp._mcp_server.lifespan is not None


class TestAppContext:
    """Tests for the AppContext dataclass."""

    def test_context_fields(self) -> None:
        """Test AppContext holds pool and settings."""
        mock_pool = MagicMock()
        mock_settings = MagicMock()

        ctx = AppContext(pool=mock_pool, settings=mock_settings)

        assert ctx.pool is mock_pool
        assert ctx.settings is mock_settings


class TestAppLifespan:
    """Tests for the app_lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_creates_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test lifespan creates a connection pool from settings."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_pool = MagicMock()
        mock_pool.test_connection = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ) as mock_create:
            async with app_lifespan(mock_server) as ctx:
                # Pool should have been created
                mock_create.assert_called_once()
                # Connection should have been tested
                mock_pool.test_connection.assert_called_once()
                # Context should contain the pool
                assert ctx.pool is mock_pool

        # Pool should be closed on exit
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_closes_pool_on_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test lifespan closes pool during shutdown."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_pool = MagicMock()
        mock_pool.test_connection = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            async with app_lifespan(mock_server):
                # Pool is open during lifespan
                mock_pool.close.assert_not_called()

            # Pool is closed after exiting
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_context_provides_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test lifespan context includes settings."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_pool = MagicMock()
        mock_pool.test_connection = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings is not None
                assert ctx.settings.database is not None
                assert ctx.settings.server is not None

    @pytest.mark.asyncio
    async def test_lifespan_pool_creation_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SystemExit when pool creation fails."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Failed to connect to SAP HANA"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server):
                    pass  # pragma: no cover

            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_lifespan_connection_test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SystemExit when connection test fails after pool creation."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_pool = MagicMock()
        mock_pool.test_connection = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_pool.close = AsyncMock()

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server):
                    pass  # pragma: no cover

            assert exc_info.value.code == 1
            # Pool should still be closed during error cleanup
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_error_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test shutdown errors are logged but don't crash the process."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_pool = MagicMock()
        mock_pool.test_connection = AsyncMock()
        mock_pool.close = AsyncMock(side_effect=RuntimeError("Shutdown error"))

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            # Should not raise despite pool.close() error
            async with app_lifespan(mock_server) as ctx:
                assert ctx.pool is mock_pool

        # close was called even though it raised
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_connection_test_failure_with_close_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test startup failure when both connection test and close fail."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        mock_pool = MagicMock()
        mock_pool.test_connection = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_pool.close = AsyncMock(side_effect=RuntimeError("Close failed"))

        mock_server = MagicMock()

        with patch(
            "mamba_mcp_sap_hana.server.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server):
                    pass  # pragma: no cover

            assert exc_info.value.code == 1
            # Close was attempted even though it also failed
            mock_pool.close.assert_called_once()
