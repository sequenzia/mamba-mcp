"""MCP tool handlers for search operations.

Implements 1 tool following the 7-step handler skeleton:
- Read tool: search

Always registered (read-only). Based on Spec Section 5.4.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_gitlab.errors import (
    ErrorCode,
    build_error_context,
    clamp_pagination,
    create_tool_error,
)
from mamba_mcp_gitlab.models.search import SearchOutput, SearchResult
from mamba_mcp_gitlab.server import AppContext, mcp
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.search_service import SearchService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read Tools (always registered)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def search(
    query: str,
    scope: str,
    project_id: int | str | None = None,
    group_id: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> SearchOutput | dict[str, Any]:
    """Search across GitLab resources.

    Performs instance-wide, project-scoped, or group-scoped searches across
    issues, merge requests, and projects. Use the scope parameter to filter
    which resource type to search.

    Scoping priority: explicit project_id > explicit group_id > configured
    default project > configured default group > instance-wide.

    Args:
        query: Search query string.
        scope: Search scope: issues, merge_requests, or projects.
        project_id: Project ID or URL-encoded path for project-scoped search.
        group_id: Group ID for group-scoped search.
        page: Page number (1-based). Defaults to 1.
        per_page: Items per page (1-100). Defaults to 20.
    """
    start_time = time.perf_counter()
    logger.debug(
        "search called with query=%s, scope=%s, project_id=%s, group_id=%s, page=%s, per_page=%s",
        query,
        scope,
        project_id,
        group_id,
        page,
        per_page,
    )

    # Step 1: Null-check context
    if ctx is None:
        logger.error("search: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "search",
        )

    # Step 2: Extract AppContext
    app_ctx = ctx.request_context.lifespan_context
    service = SearchService(app_ctx.client, app_ctx.settings)

    # Step 3: Clamp pagination
    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    try:
        # Step 4: Delegate to service
        result = await service.search(
            query=query,
            scope=scope,
            project_id=project_id,
            group_id=group_id,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        # Step 5: Convert to Pydantic output
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        items = result["items"]
        logger.debug(
            "search completed in %.2fms, returned %d items",
            elapsed_ms,
            len(items),
        )

        return SearchOutput(
            items=[SearchResult(type=scope, data=item) for item in items],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
            query=result["query"],
            scope=result["scope"],
        )

    # Step 6: Catch GitLabAPIError
    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("search failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "search",
            {"query": query, "scope": scope, "project_id": project_id, "group_id": group_id},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    # Step 7: Catch unexpected errors
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("search failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "search",
            {"query": query, "scope": scope, "project_id": project_id, "group_id": group_id},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )
