"""MCP server initialization using FastMCP.

This module creates the FastMCP server instance with lifespan management
for GitLab API client resources. Follows the PG server pattern with
AppContext and app_lifespan.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import FastMCP

from mamba_mcp_gitlab.auth import AuthenticationError, AuthInfo, detect_auth_strategy
from mamba_mcp_gitlab.config import Settings, get_settings
from mamba_mcp_gitlab.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Application context with shared resources.

    Holds the httpx client, settings, rate limiter, and auth info
    for use by all MCP tool handlers.
    """

    client: httpx.AsyncClient
    settings: Settings
    rate_limiter: RateLimiter
    auth_info: AuthInfo


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle -- httpx client and auth validation.

    Steps:
        1. Load settings via get_settings()
        2. Detect auth strategy (PAT vs OAuth)
        3. Create httpx.AsyncClient with base_url, auth headers, connection limits
        4. Validate token/credentials against GitLab API
        5. Initialize rate limiter from settings
        6. Log read-only mode status
        7. Yield AppContext
        8. Close httpx client on shutdown

    Args:
        server: The FastMCP server instance.

    Yields:
        AppContext with initialized resources.

    Raises:
        SystemExit: If auth validation fails or GitLab is unreachable.
    """
    settings = get_settings()

    # 1. Detect auth strategy
    try:
        auth_strategy = detect_auth_strategy(settings)
    except AuthenticationError as exc:
        logger.error("Authentication configuration error: %s", exc)
        sys.exit(1)

    # 2. Build httpx client with base_url, auth headers, and connection limits
    base_url = settings.gitlab.url.rstrip("/")
    auth_headers = auth_strategy.get_headers()
    max_connections = settings.server.max_connections

    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_connections,
    )

    client = httpx.AsyncClient(
        base_url=base_url,
        headers=auth_headers,
        limits=limits,
        verify=settings.gitlab.verify_ssl,
    )

    # 3. Validate token/credentials against GitLab API
    try:
        auth_info = await auth_strategy.validate(client)
        logger.info(
            "Authenticated as %s (%s) with scopes: %s",
            auth_info.username,
            auth_info.auth_type,
            auth_info.scopes,
        )
    except AuthenticationError as exc:
        await client.aclose()
        logger.error("Authentication failed: %s", exc)
        sys.exit(1)

    # 4. Initialize rate limiter from settings
    rate_limiter = RateLimiter(
        max_requests=settings.rate_limit.max_requests,
        window_seconds=settings.rate_limit.window_seconds,
    )
    if rate_limiter.enabled:
        logger.info(
            "Rate limiting enabled: %d requests per %ds window",
            settings.rate_limit.max_requests,
            settings.rate_limit.window_seconds,
        )

    # 5. Log read-only mode status
    if settings.gitlab.read_only:
        logger.info("Running in READ-ONLY mode -- mutation tools are disabled")
    else:
        logger.info("Running in read-write mode")

    try:
        yield AppContext(
            client=client,
            settings=settings,
            rate_limiter=rate_limiter,
            auth_info=auth_info,
        )
    finally:
        # 6. Close httpx client on shutdown
        await client.aclose()
        logger.info("GitLab HTTP client closed")


# Create MCP server with lifespan
mcp = FastMCP(
    "GitLab MCP Server",
    lifespan=app_lifespan,
)
