"""Pytest fixtures for SAP HANA MCP Server tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from mamba_mcp_hana.config import DatabaseSettings, set_env_file_path
from mamba_mcp_hana.database.connection import HanaConnectionPool


@pytest.fixture(autouse=True)
def reset_env_file_path() -> Generator[None, None, None]:
    """Reset env file path state before and after each test."""
    set_env_file_path(None)
    yield
    set_env_file_path(None)


@pytest.fixture()
def mock_cursor() -> MagicMock:
    """Create a mock PEP 249 cursor with standard attributes.

    Returns a MagicMock with fetchall, fetchone, description, execute, and close
    configured for typical test usage.
    """
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.description = []
    return cursor


@pytest.fixture()
def mock_hdbcli_connection(mock_cursor: MagicMock) -> MagicMock:
    """Create a mock PEP 249 hdbcli connection with cursor support.

    The connection's cursor() method returns the mock_cursor fixture.
    Health checks (SELECT 1 FROM DUMMY) succeed by default.
    """
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    return conn


@pytest.fixture()
def mock_pool() -> MagicMock:
    """Create a mock HanaConnectionPool for tool and service tests.

    The pool's acquire/release methods are mocked as coroutines that return
    a mock connection. The pool's close method is a no-op coroutine.
    """
    pool = MagicMock(spec=HanaConnectionPool)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()

    async def _acquire() -> MagicMock:
        return mock_conn

    async def _release(conn: Any) -> None:
        pass

    async def _close() -> None:
        pass

    async def _test_connection() -> None:
        pass

    pool.acquire = _acquire
    pool.release = _release
    pool.close = _close
    pool.test_connection = _test_connection
    pool._mock_connection = mock_conn
    return pool


@pytest.fixture()
def hana_config(monkeypatch: pytest.MonkeyPatch) -> DatabaseSettings:
    """Create a DatabaseSettings instance with safe test defaults.

    Sets minimal env vars for user/password auth with default host/port.
    Returns the settings instance for use in tests.
    """
    monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "localhost")
    monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
    monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
    monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")
    return DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
