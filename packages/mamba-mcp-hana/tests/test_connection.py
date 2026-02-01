"""Tests for async connection pool management."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mamba_mcp_sap_hana.config import DatabaseSettings
from mamba_mcp_sap_hana.database.connection import (
    HanaConnectionPool,
    _check_connection_health,
    _close_connection,
    _create_connection,
    build_connection_params,
    create_pool,
)


class TestBuildConnectionParams:
    """Tests for building hdbcli connection parameters."""

    def test_user_password_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test connection params with user/password authentication."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana.example.com")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["address"] == "hana.example.com"
        assert params["port"] == 30015
        assert params["user"] == "myuser"
        assert params["password"] == "mypass"
        assert "userkey" not in params

    def test_userkey_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test connection params with hdbuserstore key authentication."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana.example.com")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "MY_HANA_KEY")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["address"] == "hana.example.com"
        assert params["port"] == 30015
        assert params["userkey"] == "MY_HANA_KEY"
        assert "user" not in params
        assert "password" not in params

    def test_user_password_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test user/password auth takes precedence when both modes provided."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "MY_KEY")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["user"] == "myuser"
        assert params["password"] == "mypass"
        assert "userkey" not in params

    def test_tls_encryption_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test TLS parameters included when encryption is enabled."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana-cloud.example.com")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "443")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["encrypt"] is True
        assert params["sslValidateCertificate"] is True

    def test_tls_encryption_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test TLS parameters excluded when encryption is disabled."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana.local")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert "encrypt" not in params
        assert "sslValidateCertificate" not in params

    def test_ssl_validate_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslValidateCertificate=False when ssl_validate disabled."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "443")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_SSL_VALIDATE", "false")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["encrypt"] is True
        assert params["sslValidateCertificate"] is False

    def test_tenant_database_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test databaseName included when db_name is set."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_NAME", "TENANT1")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["databaseName"] == "TENANT1"

    def test_no_tenant_database_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test databaseName excluded when db_name is not set."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert "databaseName" not in params


def _make_mock_connection(healthy: bool = True) -> MagicMock:
    """Create a mock hdbcli connection.

    Args:
        healthy: If True, the mock responds to health checks. If False, raises on execute.

    Returns:
        A MagicMock simulating an hdbcli connection.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    if not healthy:
        cursor.execute.side_effect = Exception("Connection lost")

    return conn


def _make_pool(
    pool_size: int = 3,
    pool_timeout: float = 1.0,
) -> HanaConnectionPool:
    """Create a HanaConnectionPool with test defaults.

    Args:
        pool_size: Maximum connections.
        pool_timeout: Timeout in seconds.

    Returns:
        A new HanaConnectionPool instance.
    """
    return HanaConnectionPool(
        connection_params={"address": "localhost", "port": 30015},
        pool_size=pool_size,
        pool_timeout=pool_timeout,
    )


class TestHanaConnectionPoolCreation:
    """Tests for pool initialization and properties."""

    def test_pool_properties(self) -> None:
        """Test pool initializes with correct properties."""
        pool = _make_pool(pool_size=10, pool_timeout=60.0)

        assert pool.pool_size == 10
        assert pool.pool_timeout == 60.0
        assert pool.created_count == 0
        assert pool.available_count == 0
        assert pool.is_closed is False

    def test_default_pool_size(self) -> None:
        """Test pool default size is 5."""
        pool = HanaConnectionPool(
            connection_params={"address": "localhost", "port": 30015},
        )
        assert pool.pool_size == 5
        assert pool.pool_timeout == 30.0


class TestHanaConnectionPoolAcquireRelease:
    """Tests for acquiring and releasing connections."""

    @pytest.mark.asyncio
    async def test_acquire_creates_new_connection(self) -> None:
        """Test acquire creates a new connection when pool is empty."""
        pool = _make_pool(pool_size=3)
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            conn = await pool.acquire()

        assert conn is mock_conn
        assert pool.created_count == 1

    @pytest.mark.asyncio
    async def test_release_returns_connection_to_pool(self) -> None:
        """Test release puts connection back in the pool."""
        pool = _make_pool(pool_size=3)
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            conn = await pool.acquire()
            assert pool.available_count == 0

            await pool.release(conn)
            assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_acquire_reuses_released_connection(self) -> None:
        """Test acquire returns a previously released connection."""
        pool = _make_pool(pool_size=3)
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ) as mock_create:
            conn1 = await pool.acquire()
            await pool.release(conn1)

            conn2 = await pool.acquire()

        # Same connection reused; create only called once
        assert conn2 is mock_conn
        assert mock_create.call_count == 1
        assert pool.created_count == 1

    @pytest.mark.asyncio
    async def test_acquire_multiple_connections(self) -> None:
        """Test acquiring multiple connections up to pool size."""
        pool = _make_pool(pool_size=3)
        connections: list[Any] = []
        mock_conns = [_make_mock_connection() for _ in range(3)]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=mock_conns,
        ):
            for _ in range(3):
                conn = await pool.acquire()
                connections.append(conn)

        assert pool.created_count == 3
        assert pool.available_count == 0
        assert len(connections) == 3


class TestHanaConnectionPoolSizeLimit:
    """Tests for pool size enforcement."""

    @pytest.mark.asyncio
    async def test_pool_exhaustion_timeout(self) -> None:
        """Test TimeoutError when all connections in use and timeout expires."""
        pool = _make_pool(pool_size=1, pool_timeout=0.1)
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            # Acquire the only connection
            await pool.acquire()

            # Second acquire should timeout
            with pytest.raises(TimeoutError) as exc_info:
                await pool.acquire()

            assert "Connection pool exhausted" in str(exc_info.value)
            assert "timed out after" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_pool_size_not_exceeded(self) -> None:
        """Test that created_count never exceeds pool_size."""
        pool = _make_pool(pool_size=2)
        mock_conns = [_make_mock_connection() for _ in range(2)]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=mock_conns,
        ):
            conn1 = await pool.acquire()
            conn2 = await pool.acquire()

            assert pool.created_count == 2
            assert pool.pool_size == 2

            # Release one and re-acquire: should reuse, not create new
            await pool.release(conn1)

        conn3 = await pool.acquire()
        assert conn3 is conn1
        assert pool.created_count == 2

        # Cleanup
        await pool.release(conn2)
        await pool.release(conn3)


class TestHanaConnectionPoolHealthCheck:
    """Tests for connection health checking."""

    @pytest.mark.asyncio
    async def test_stale_connection_removed_on_acquire(self) -> None:
        """Test stale connections are detected and removed during acquire."""
        pool = _make_pool(pool_size=3)
        stale_conn = _make_mock_connection(healthy=False)
        fresh_conn = _make_mock_connection(healthy=True)

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=[stale_conn, fresh_conn],
        ):
            # First acquire creates stale_conn
            conn1 = await pool.acquire()
            assert conn1 is stale_conn
            assert pool.created_count == 1

            # Put stale_conn back in pool
            await pool.release(conn1)
            assert pool.available_count == 1

            # Next acquire: finds stale_conn unhealthy, removes it, creates fresh_conn
            conn2 = await pool.acquire()
            assert conn2 is fresh_conn
            assert pool.created_count == 1  # stale removed (-1), fresh added (+1)

            # Verify stale connection was closed
            stale_conn.close.assert_called_once()


class TestHanaConnectionPoolClose:
    """Tests for graceful pool shutdown."""

    @pytest.mark.asyncio
    async def test_close_drains_idle_connections(self) -> None:
        """Test close() drains and closes all idle connections."""
        pool = _make_pool(pool_size=3)
        mock_conns = [_make_mock_connection() for _ in range(3)]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=mock_conns,
        ):
            conns = [await pool.acquire() for _ in range(3)]
            for c in conns:
                await pool.release(c)

        assert pool.available_count == 3

        await pool.close()

        assert pool.is_closed is True
        assert pool.available_count == 0
        assert pool.created_count == 0

        # All connections should have been closed
        for mc in mock_conns:
            mc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_prevents_new_acquires(self) -> None:
        """Test acquire raises RuntimeError after pool is closed."""
        pool = _make_pool(pool_size=3)
        await pool.close()

        with pytest.raises(RuntimeError, match="Connection pool is closed"):
            await pool.acquire()

    @pytest.mark.asyncio
    async def test_release_after_close_closes_connection(self) -> None:
        """Test releasing a connection after pool close closes the connection."""
        pool = _make_pool(pool_size=3)
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            conn = await pool.acquire()

        await pool.close()

        # Release after close should close the connection
        await pool.release(conn)
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        """Test calling close() multiple times is safe."""
        pool = _make_pool(pool_size=3)

        await pool.close()
        await pool.close()  # Should not raise

        assert pool.is_closed is True


class TestHanaConnectionPoolConnectionError:
    """Tests for connection failure handling."""

    @pytest.mark.asyncio
    async def test_create_connection_failure(self) -> None:
        """Test ConnectionError with host/port context when connection fails."""
        pool = _make_pool(pool_size=3)

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError(
                "Failed to connect to SAP HANA at localhost:30015: timeout"
            ),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                await pool.acquire()

            assert "localhost:30015" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_test_connection_success(self) -> None:
        """Test test_connection succeeds with a working pool."""
        pool = _make_pool(pool_size=1)
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            await pool.test_connection()

        # Connection should be back in the pool
        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_test_connection_failure(self) -> None:
        """Test test_connection raises when connection fails."""
        pool = _make_pool(pool_size=1)

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Failed to connect"),
        ):
            with pytest.raises(ConnectionError):
                await pool.test_connection()


class TestCreatePool:
    """Tests for the create_pool factory function."""

    @pytest.mark.asyncio
    async def test_create_pool_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test create_pool builds a pool from DatabaseSettings."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana.example.com")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "443")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "10")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_TIMEOUT", "60.0")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        pool = await create_pool(settings)

        assert pool.pool_size == 10
        assert pool.pool_timeout == 60.0
        assert pool.created_count == 0
        assert pool.is_closed is False

    @pytest.mark.asyncio
    async def test_create_pool_default_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test create_pool with default pool settings."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "myuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "mypass")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        pool = await create_pool(settings)

        assert pool.pool_size == 5
        assert pool.pool_timeout == 30.0

    @pytest.mark.asyncio
    async def test_create_pool_userkey_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test create_pool with hdbuserstore key authentication."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "MY_KEY")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "3")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        pool = await create_pool(settings)

        assert pool.pool_size == 3
        assert pool.is_closed is False


class TestModuleLevelFunctions:
    """Tests for module-level private functions used by the pool."""

    def test_create_connection_wraps_exception(self) -> None:
        """Test _create_connection wraps hdbcli errors in ConnectionError."""
        with patch(
            "mamba_mcp_sap_hana.database.connection.dbapi.connect",
            side_effect=Exception("Cannot connect"),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                _create_connection({"address": "hana.test", "port": 30015})

            assert "hana.test:30015" in str(exc_info.value)
            assert "Cannot connect" in str(exc_info.value)

    def test_create_connection_success(self) -> None:
        """Test _create_connection returns connection on success."""
        mock_conn = MagicMock()
        with patch(
            "mamba_mcp_sap_hana.database.connection.dbapi.connect",
            return_value=mock_conn,
        ):
            result = _create_connection({"address": "localhost", "port": 30015})

        assert result is mock_conn

    def test_create_connection_unknown_address(self) -> None:
        """Test _create_connection handles missing address/port gracefully."""
        with patch(
            "mamba_mcp_sap_hana.database.connection.dbapi.connect",
            side_effect=Exception("timeout"),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                _create_connection({})

            assert "unknown:unknown" in str(exc_info.value)

    def test_check_connection_health_success(self) -> None:
        """Test _check_connection_health returns True for healthy connection."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        result = _check_connection_health(conn)

        assert result is True
        cursor.execute.assert_called_once_with("SELECT 1 FROM DUMMY")
        cursor.close.assert_called_once()

    def test_check_connection_health_failure(self) -> None:
        """Test _check_connection_health returns False for broken connection."""
        conn = MagicMock()
        conn.cursor.side_effect = Exception("Connection lost")

        result = _check_connection_health(conn)

        assert result is False

    def test_check_connection_health_execute_fails(self) -> None:
        """Test _check_connection_health returns False when execute raises."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("Statement timeout")

        result = _check_connection_health(conn)

        assert result is False

    def test_close_connection_success(self) -> None:
        """Test _close_connection closes connection without raising."""
        conn = MagicMock()
        _close_connection(conn)
        conn.close.assert_called_once()

    def test_close_connection_suppresses_error(self) -> None:
        """Test _close_connection suppresses errors on close."""
        conn = MagicMock()
        conn.close.side_effect = Exception("Already closed")

        # Should not raise
        _close_connection(conn)
        conn.close.assert_called_once()


class TestPoolDeadConnectionRecovery:
    """Tests for pool timeout and dead connection recovery scenarios."""

    @pytest.mark.asyncio
    async def test_multiple_stale_connections_drained(self) -> None:
        """Test pool drains multiple stale connections before creating new one."""
        pool = _make_pool(pool_size=3)
        stale1 = _make_mock_connection(healthy=False)
        stale2 = _make_mock_connection(healthy=False)
        fresh = _make_mock_connection(healthy=True)

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=[stale1, stale2, fresh],
        ):
            # Acquire and release two stale connections
            c1 = await pool.acquire()
            c2 = await pool.acquire()
            await pool.release(c1)
            await pool.release(c2)
            assert pool.available_count == 2

            # Next acquire drains both stale conns, creates fresh
            conn = await pool.acquire()
            assert conn is fresh

        # Both stale connections should have been closed
        stale1.close.assert_called_once()
        stale2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_connection_after_wait_creates_new(self) -> None:
        """Test stale connection returned after wait triggers replacement."""
        pool = _make_pool(pool_size=1, pool_timeout=2.0)
        stale = _make_mock_connection(healthy=False)
        fresh = _make_mock_connection(healthy=True)

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=[stale, fresh],
        ):
            # Acquire the only connection (stale, but we don't know yet)
            conn1 = await pool.acquire()
            assert conn1 is stale

            # Release it back so it's available for the next acquire
            # Then release it in a concurrent task after a short delay
            async def release_later() -> None:
                await asyncio.sleep(0.05)
                await pool.release(conn1)

            # Start the release task
            task = asyncio.create_task(release_later())

            # This acquire will wait for the released stale conn, detect it as
            # unhealthy, then create a new one
            conn2 = await pool.acquire()
            assert conn2 is fresh

            await task

        stale.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_pool_timeout_message_includes_details(self) -> None:
        """Test TimeoutError message includes pool size and timeout details."""
        pool = _make_pool(pool_size=2, pool_timeout=0.1)
        conns = [_make_mock_connection() for _ in range(2)]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=conns,
        ):
            await pool.acquire()
            await pool.acquire()

            with pytest.raises(TimeoutError) as exc_info:
                await pool.acquire()

        msg = str(exc_info.value)
        assert "2" in msg  # pool_size
        assert "0.1" in str(pool.pool_timeout)

    @pytest.mark.asyncio
    async def test_release_decrements_count_when_pool_closed(self) -> None:
        """Test releasing connection after close decrements created_count."""
        pool = _make_pool(pool_size=2)
        mock_conns = [_make_mock_connection() for _ in range(2)]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=mock_conns,
        ):
            conn1 = await pool.acquire()
            conn2 = await pool.acquire()

        assert pool.created_count == 2

        # Close the pool (drains idle, but these are still "in use")
        await pool.close()

        # Release both after close -- each should be closed + decrement count
        await pool.release(conn1)
        assert pool.created_count == 1

        await pool.release(conn2)
        assert pool.created_count == 0


class TestPoolWithUserkeyConfig:
    """Tests for pool created with hdbuserstore key authentication."""

    @pytest.mark.asyncio
    async def test_pool_with_userkey_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pool creation with userkey auth (no user/password)."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "DEV_KEY")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana-dev.local")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["userkey"] == "DEV_KEY"
        assert "user" not in params
        assert "password" not in params

        pool = await create_pool(settings)
        assert pool.pool_size == 5
        assert pool.is_closed is False

    def test_build_connection_params_userkey_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test build_connection_params with only userkey (no user or password)."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "PROD_KEY")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        params = build_connection_params(settings)

        assert params["userkey"] == "PROD_KEY"
        assert "user" not in params
        assert "password" not in params
        # host/port use defaults
        assert params["address"] == "localhost"
        assert params["port"] == 30015
