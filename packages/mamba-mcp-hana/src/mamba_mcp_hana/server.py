"""FastMCP server initialization with lifespan management.

Creates the FastMCP server instance with async lifespan for connection pool
management. The lifespan loads settings, creates the HanaConnectionPool,
verifies connectivity, and makes the pool available to all tool functions
via the server context.

Based on spec Section 9.1, following the mamba-mcp-pg pattern.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from mamba_mcp_hana import __version__
from mamba_mcp_hana.config import Settings, get_settings
from mamba_mcp_hana.database.connection import HanaConnectionPool, create_pool

logger = logging.getLogger(__name__)

SERVER_NAME = "mamba-mcp-hana"


@dataclass
class AppContext:
    """Application context with shared resources.

    Stored in the MCP server's lifespan context, accessible to all tools
    via ``ctx.request_context.lifespan_context``.

    Attributes:
        pool: Async connection pool for SAP HANA database access.
        settings: Root settings instance with database and server config.
    """

    pool: HanaConnectionPool
    settings: Settings


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle -- connection pool creation and cleanup.

    Loads configuration, creates the connection pool from database settings,
    tests connectivity, and yields the context for tools to use. On shutdown,
    gracefully closes the pool.

    Args:
        server: The FastMCP server instance.

    Yields:
        AppContext with initialized pool and settings.

    Raises:
        SystemExit: If pool creation or connection test fails during startup.
    """
    settings = get_settings()

    logger.info(
        "Initializing %s v%s with %s transport",
        SERVER_NAME,
        __version__,
        settings.server.transport,
    )

    # Create connection pool from database settings
    try:
        pool = await create_pool(settings.database)
    except Exception as e:
        logger.error("Failed to create connection pool: %s", e)
        raise SystemExit(1) from e

    # Test connectivity before accepting requests
    try:
        await pool.test_connection()
        logger.info("Database connection verified")
    except Exception as e:
        # Clean up the pool before exiting
        try:
            await pool.close()
        except Exception as close_err:
            logger.warning("Error closing pool during failed startup: %s", close_err)
        logger.error("Database connection failed: %s", e)
        raise SystemExit(1) from e

    try:
        yield AppContext(pool=pool, settings=settings)
    finally:
        # Gracefully shut down the pool
        try:
            await pool.close()
            logger.info("Connection pool closed")
        except Exception as e:
            logger.warning("Error during pool shutdown: %s", e)


# Create MCP server with lifespan
mcp = FastMCP(
    SERVER_NAME,
    lifespan=app_lifespan,
)
