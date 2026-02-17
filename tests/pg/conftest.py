"""Pytest fixtures for PostgreSQL MCP Server tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from mamba_mcp_pg.config import DatabaseSettings, ServerSettings, Settings, set_env_file_path
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@pytest.fixture(autouse=True)
def reset_env_file_path() -> Generator[None, None, None]:
    """Reset env file path state before and after each test."""
    set_env_file_path(None)
    yield
    set_env_file_path(None)


@pytest.fixture
def database_settings() -> DatabaseSettings:
    """Create test database settings."""
    return DatabaseSettings(
        db_host="localhost",
        db_port=5432,
        db_name="test_db",
        db_user="test_user",
        db_password="test_password",  # type: ignore
        pool_size=2,
        statement_timeout=5000,
        default_schema="public",
    )


@pytest.fixture
def server_settings() -> ServerSettings:
    """Create test server settings."""
    return ServerSettings(
        transport="stdio",
        log_level="DEBUG",
    )


@pytest.fixture
def settings(database_settings: DatabaseSettings, server_settings: ServerSettings) -> Settings:
    """Create combined test settings."""
    settings = Settings()
    # Use object.__setattr__ to bypass frozen model
    object.__setattr__(settings, "database", database_settings)
    object.__setattr__(settings, "server", server_settings)
    return settings


def create_mock_result(rows: list[dict[str, Any]]) -> MagicMock:
    """Create a mock database result.

    Args:
        rows: List of row dictionaries to return.

    Returns:
        Mock result object with fetchall/fetchone methods.
    """
    mock_result = MagicMock()

    # Create mock rows with _mapping attribute
    mock_rows = []
    for row_data in rows:
        mock_row = MagicMock()
        mock_row._mapping = row_data
        mock_rows.append(mock_row)

    mock_result.fetchall.return_value = mock_rows
    mock_result.fetchone.return_value = mock_rows[0] if mock_rows else None
    return mock_result


@pytest_asyncio.fixture
async def mock_connection() -> AsyncMock:
    """Create mock async connection."""
    conn = AsyncMock(spec=AsyncConnection)

    # Default execute returns empty result
    mock_result = create_mock_result([])
    conn.execute.return_value = mock_result

    return conn


@pytest_asyncio.fixture
async def mock_engine(mock_connection: AsyncMock) -> AsyncMock:
    """Create mock async engine."""
    engine = AsyncMock(spec=AsyncEngine)

    # Make connect() return async context manager
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_connection
    cm.__aexit__.return_value = None
    engine.connect.return_value = cm

    return engine
