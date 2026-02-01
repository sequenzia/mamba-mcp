"""Async connection pool management for SAP HANA using hdbcli.

Wraps hdbcli's synchronous PEP 249 connections in an async-compatible
pool using asyncio.Queue and asyncio.to_thread for non-blocking operation.

Based on Spec Section 5.6 and Architecture Section 7.1.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from hdbcli import dbapi  # type: ignore[import-untyped]

from mamba_mcp_sap_hana.config import DatabaseSettings

logger = logging.getLogger(__name__)


def build_connection_params(settings: DatabaseSettings) -> dict[str, Any]:
    """Build hdbcli connection parameters from DatabaseSettings.

    Supports two authentication modes:
    - User/password: uses db_user + db_password (takes precedence)
    - hdbuserstore key: uses db_userkey

    Args:
        settings: Database configuration settings.

    Returns:
        Dictionary of hdbcli connection parameters.
    """
    params: dict[str, Any] = {
        "address": settings.db_host,
        "port": settings.db_port,
    }

    # Authentication: user/password takes precedence over userkey
    if settings.db_user is not None and settings.db_password is not None:
        params["user"] = settings.db_user
        params["password"] = settings.db_password.get_secret_value()
    elif settings.db_userkey is not None:
        params["userkey"] = settings.db_userkey
    # Validator on DatabaseSettings ensures at least one auth mode is present

    # Optional tenant database name
    if settings.db_name is not None:
        params["databaseName"] = settings.db_name

    # TLS/encryption settings
    if settings.effective_encrypt:
        params["encrypt"] = True
        params["sslValidateCertificate"] = settings.db_ssl_validate

    return params


def _create_connection(params: dict[str, Any]) -> dbapi.Connection:
    """Create a single hdbcli connection (synchronous).

    Args:
        params: hdbcli connection parameters from build_connection_params.

    Returns:
        An hdbcli Connection object.

    Raises:
        ConnectionError: If connection fails, with host/port context.
    """
    address = params.get("address", "unknown")
    port = params.get("port", "unknown")
    try:
        return dbapi.connect(**params)
    except Exception as exc:
        msg = f"Failed to connect to SAP HANA at {address}:{port}: {exc}"
        raise ConnectionError(msg) from exc


def _check_connection_health(conn: dbapi.Connection) -> bool:
    """Check if an hdbcli connection is still alive.

    Executes a simple validation query against HANA's DUMMY table.

    Args:
        conn: An hdbcli Connection to validate.

    Returns:
        True if the connection is healthy, False if stale or broken.
    """
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUMMY")
        cursor.close()
        return True
    except Exception:
        return False


def _close_connection(conn: dbapi.Connection) -> None:
    """Close an hdbcli connection, suppressing errors.

    Args:
        conn: An hdbcli Connection to close.
    """
    try:
        conn.close()
    except Exception:
        pass


class HanaConnectionPool:
    """Async connection pool managing hdbcli connections.

    Uses asyncio.Queue for async-compatible connection management and
    asyncio.to_thread to run synchronous hdbcli operations without
    blocking the event loop.

    The pool lazily creates connections up to pool_size. When all
    connections are in use, acquire() waits up to pool_timeout seconds
    before raising a TimeoutError.
    """

    def __init__(
        self,
        connection_params: dict[str, Any],
        pool_size: int = 5,
        pool_timeout: float = 30.0,
    ) -> None:
        """Initialize the connection pool.

        Args:
            connection_params: hdbcli connection params from build_connection_params.
            pool_size: Maximum number of connections in the pool.
            pool_timeout: Timeout in seconds when waiting to acquire a connection.
        """
        self._connection_params = connection_params
        self._pool_size = pool_size
        self._pool_timeout = pool_timeout
        self._pool: asyncio.Queue[dbapi.Connection] = asyncio.Queue(maxsize=pool_size)
        self._created_count = 0
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def pool_size(self) -> int:
        """Maximum number of connections allowed."""
        return self._pool_size

    @property
    def pool_timeout(self) -> float:
        """Timeout in seconds for acquiring a connection."""
        return self._pool_timeout

    @property
    def created_count(self) -> int:
        """Number of connections currently created."""
        return self._created_count

    @property
    def available_count(self) -> int:
        """Number of idle connections available in the pool."""
        return self._pool.qsize()

    @property
    def is_closed(self) -> bool:
        """Whether the pool has been closed."""
        return self._closed

    async def _create_new_connection(self) -> dbapi.Connection:
        """Create a new hdbcli connection via asyncio.to_thread.

        Returns:
            A new hdbcli Connection.

        Raises:
            ConnectionError: If connection creation fails.
        """
        conn = await asyncio.to_thread(_create_connection, self._connection_params)
        self._created_count += 1
        return conn

    async def acquire(self) -> dbapi.Connection:
        """Acquire a connection from the pool.

        If idle connections are available, returns one after health-checking it.
        If the pool is below capacity, creates a new connection.
        If at capacity with all connections in use, waits up to pool_timeout.

        Returns:
            A healthy hdbcli Connection.

        Raises:
            TimeoutError: If no connection becomes available within pool_timeout.
            RuntimeError: If the pool has been closed.
            ConnectionError: If connection creation fails.
        """
        if self._closed:
            msg = "Connection pool is closed"
            raise RuntimeError(msg)

        # Try to get an idle connection from the pool (non-blocking)
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                break

            # Health check the connection
            healthy = await asyncio.to_thread(_check_connection_health, conn)
            if healthy:
                return conn

            # Connection is stale; close it and decrement count
            await asyncio.to_thread(_close_connection, conn)
            self._created_count -= 1
            logger.debug("Removed stale connection from pool (created: %d)", self._created_count)

        # Try to create a new connection if below capacity
        async with self._lock:
            if self._created_count < self._pool_size:
                return await self._create_new_connection()

        # Pool is at capacity; wait for a connection to be released
        try:
            conn = await asyncio.wait_for(self._pool.get(), timeout=self._pool_timeout)
        except TimeoutError:
            msg = (
                f"Connection pool exhausted: all {self._pool_size} connections in use, "
                f"timed out after {self._pool_timeout}s"
            )
            raise TimeoutError(msg) from None

        # Health check the returned connection
        healthy = await asyncio.to_thread(_check_connection_health, conn)
        if healthy:
            return conn

        # Stale connection; close and create a fresh one
        await asyncio.to_thread(_close_connection, conn)
        self._created_count -= 1
        return await self._create_new_connection()

    async def release(self, conn: dbapi.Connection) -> None:
        """Return a connection to the pool.

        If the pool is closed, the connection is closed instead of being returned.

        Args:
            conn: The hdbcli Connection to return.
        """
        if self._closed:
            await asyncio.to_thread(_close_connection, conn)
            self._created_count -= 1
            return

        try:
            self._pool.put_nowait(conn)
        except asyncio.QueueFull:
            # Pool is somehow overfull; close the extra connection
            await asyncio.to_thread(_close_connection, conn)
            self._created_count -= 1

    async def close(self) -> None:
        """Close all connections in the pool.

        After calling close, no new connections can be acquired.
        All idle connections are closed immediately. In-use connections
        will be closed when released back to the pool.
        """
        self._closed = True

        # Drain and close all idle connections
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                await asyncio.to_thread(_close_connection, conn)
                self._created_count -= 1
            except asyncio.QueueEmpty:
                break

        logger.info("Connection pool closed (remaining in-use: %d)", self._created_count)

    async def test_connection(self) -> None:
        """Test pool connectivity by acquiring and releasing a connection.

        Raises:
            ConnectionError: If unable to connect to the database.
        """
        conn = await self.acquire()
        await self.release(conn)


async def create_pool(settings: DatabaseSettings) -> HanaConnectionPool:
    """Factory function to create a connection pool from Settings config.

    Builds connection parameters from DatabaseSettings and initializes
    a HanaConnectionPool with the configured pool size and timeout.

    Args:
        settings: Database configuration with connection and pool settings.

    Returns:
        An initialized HanaConnectionPool ready for use.
    """
    params = build_connection_params(settings)
    return HanaConnectionPool(
        connection_params=params,
        pool_size=settings.pool_size,
        pool_timeout=settings.pool_timeout,
    )
