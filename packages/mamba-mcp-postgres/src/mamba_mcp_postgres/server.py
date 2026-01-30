"""MCP server initialization using FastMCP.

This module creates the FastMCP server instance with lifespan management
for database connection pooling.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncEngine

from mamba_mcp_postgres.config import Settings, get_settings
from mamba_mcp_postgres.database.engine import create_engine, dispose_engine, test_connection

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Application context with shared resources."""

    engine: AsyncEngine
    settings: Settings


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle - database connection pool.

    Args:
        server: The FastMCP server instance.

    Yields:
        AppContext with initialized resources.

    Raises:
        SystemExit: If database connection test fails.
    """
    settings = get_settings()

    # Initialize database engine on startup
    engine = await create_engine(settings.database)

    # Test connection before server starts
    try:
        await test_connection(engine)
        logger.info("Database connection verified")
    except Exception as e:
        await dispose_engine(engine)
        logger.error(f"Database connection failed: {e}")
        raise SystemExit(1) from e

    try:
        yield AppContext(engine=engine, settings=settings)
    finally:
        # Cleanup on shutdown
        await dispose_engine(engine)


# Create MCP server with lifespan
mcp = FastMCP(
    "PostgreSQL MCP Server",
    lifespan=app_lifespan,
)
