"""Tests for database engine functions."""

from unittest.mock import AsyncMock

import pytest
from mamba_mcp_pg.database.engine import test_connection as db_test_connection


class TestTestConnection:
    """Tests for test_connection function."""

    @pytest.mark.asyncio
    async def test_test_connection_success(self, mock_engine: AsyncMock) -> None:
        """Test successful connection test."""
        # Should not raise any exception
        await db_test_connection(mock_engine)

        # Verify execute was called
        mock_engine.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_connection_failure(self, mock_engine: AsyncMock) -> None:
        """Test connection test failure propagates exception."""
        # Make connect raise an exception
        mock_engine.connect.side_effect = Exception("Connection refused")

        with pytest.raises(Exception) as exc_info:
            await db_test_connection(mock_engine)

        assert "Connection refused" in str(exc_info.value)
