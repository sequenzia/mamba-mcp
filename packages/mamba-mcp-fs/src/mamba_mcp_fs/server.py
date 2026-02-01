"""FastMCP server definition for the Filesystem MCP Server.

Creates the FastMCP server instance with lifespan management for backend
initialization, security validation, and conditional tool registration.

Based on spec Section 7.1, following the mamba-mcp-pg pattern.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from mamba_mcp_fs.backends.base import BackendManager
from mamba_mcp_fs.config import Settings, get_settings
from mamba_mcp_fs.rate_limit import RateLimiter
from mamba_mcp_fs.security import SecurityValidator

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Application context with shared resources.

    Stored in the MCP server's lifespan context, accessible to all tools
    via ``ctx.request_context.lifespan_context``.

    Attributes:
        settings: Root settings instance with server, local, and s3 config.
        security: SecurityValidator for path validation and policy enforcement.
        backend_manager: BackendManager for routing operations to backends.
        rate_limiter: RateLimiter for per-server-instance operation rate limiting.
    """

    settings: Settings
    security: SecurityValidator
    backend_manager: BackendManager
    rate_limiter: RateLimiter


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle -- backend initialization and cleanup.

    Loads configuration, creates the security validator and backend manager,
    validates that at least one backend is enabled, and yields the context
    for tools to use. On shutdown, cleans up any open filesystem connections.

    Args:
        server: The FastMCP server instance.

    Yields:
        AppContext with initialized resources.

    Raises:
        SystemExit: If no backends are enabled.
    """
    settings = get_settings()

    logger.info("Initializing Filesystem MCP Server")

    # Validate at least one backend is enabled
    if not settings.local.enabled and not settings.s3.enabled:
        logger.error("No backends enabled. Enable at least one of: local, s3")
        raise SystemExit(1)

    # Create security validator with all settings
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local if settings.local.enabled else None,
        s3_settings=settings.s3 if settings.s3.enabled else None,
    )

    # Create backend manager (backends will be instantiated later when
    # backend modules are implemented; for now just pass the settings
    # and security validator)
    backend_manager = BackendManager(
        settings=settings,
        security=security,
    )

    # Create rate limiter from config
    rate_limiter = RateLimiter(ops_per_minute=settings.server.rate_limit)

    logger.info(
        "Server initialized: local=%s, s3=%s, read_only=%s, rate_limit=%s",
        settings.local.enabled,
        settings.s3.enabled,
        settings.server.read_only,
        settings.server.rate_limit if rate_limiter.enabled else "disabled",
    )

    try:
        yield AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=rate_limiter,
        )
    finally:
        # Cleanup on shutdown -- close any open fsspec connections
        logger.info("Shutting down Filesystem MCP Server")


def _register_tools(mcp_server: FastMCP, settings: Settings) -> list[str]:
    """Register tool modules with the MCP server based on configuration.

    Layer 1 (discovery_tools) is always registered.
    Layer 2 (s3_tools) is registered only when S3 is enabled.
    Layer 3 (mutation_tools) is registered only when read_only is False.

    Tool modules are imported here to trigger their @mcp.tool registrations.
    Since tool modules may not be implemented yet, ImportError is caught
    and logged as a warning.

    Args:
        mcp_server: The FastMCP server to register tools with.
        settings: Settings instance for checking feature flags.

    Returns:
        List of module names that were successfully registered.
    """
    registered: list[str] = []

    # Layer 1: Discovery tools -- always registered
    try:
        import mamba_mcp_fs.tools.discovery_tools  # noqa: F401

        registered.append("discovery_tools")
        logger.info("Registered Layer 1: discovery tools")
    except ImportError:
        logger.warning("Layer 1 discovery_tools module not yet implemented")

    # Layer 2: S3 tools -- registered when S3 is enabled
    if settings.s3.enabled:
        try:
            import mamba_mcp_fs.tools.s3_tools  # noqa: F401

            registered.append("s3_tools")
            logger.info("Registered Layer 2: S3 tools")
        except ImportError:
            logger.warning("Layer 2 s3_tools module not yet implemented")

    # Layer 3: Mutation tools -- registered when read_only is False
    if not settings.server.read_only:
        try:
            import mamba_mcp_fs.tools.mutation_tools  # noqa: F401

            registered.append("mutation_tools")
            logger.info("Registered Layer 3: mutation tools")
        except ImportError:
            logger.warning("Layer 3 mutation_tools module not yet implemented")

    return registered


# Create MCP server with lifespan
mcp = FastMCP(
    "mamba-mcp-fs",
    lifespan=app_lifespan,
)
