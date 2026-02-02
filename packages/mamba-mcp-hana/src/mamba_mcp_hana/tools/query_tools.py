"""Layer 3: Query Execution MCP Tools.

Registers execute_query and explain_query tools with the FastMCP server.
Both tools enforce read-only validation before execution -- write operations
(INSERT, UPDATE, DELETE, DROP, etc.) are blocked at the tool layer.

Based on Spec Sections 5.3 and 9.2.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from mamba_mcp_hana.database.query_service import QueryService
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error
from mamba_mcp_hana.models.query import ExecuteQueryOutput, ExplainQueryOutput
from mamba_mcp_hana.server import AppContext, mcp

logger = logging.getLogger(__name__)


def _truncate_for_log(text: str, max_length: int = 100) -> str:
    """Truncate text for logging to avoid huge log entries."""
    return text[:max_length] + "..." if len(text) > max_length else text


@mcp.tool()
async def execute_query(
    sql: str,
    params: dict[str, Any] | list[Any] | None = None,
    limit: int = 1000,
    timeout_ms: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ExecuteQueryOutput | dict[str, Any]:
    """Execute a read-only SQL query against SAP HANA.

    Runs SELECT/WITH queries with optional parameterized values. Use ? for
    positional parameters or :name for named parameters. All write operations
    (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, etc.) are blocked for safety.

    Args:
        sql: SQL SELECT query. Use ? for positional or :name for named params.
        params: Bind parameter values (dict for named :param, list for positional ?).
        limit: Maximum rows to return (1-10000). Default: 1000.
        timeout_ms: Query timeout in milliseconds (uses server default if not set).

    Returns:
        Query results with columns, rows, and metadata.

    Security:
        Only SELECT and WITH...SELECT queries are allowed.
        INSERT, UPDATE, DELETE, DROP, and other write operations are blocked.
    """
    param_count = len(params) if params else 0
    logger.debug(
        "execute_query called with sql=%r, param_count=%d, limit=%d",
        _truncate_for_log(sql),
        param_count,
        limit,
    )

    if ctx is None:
        logger.error("execute_query: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="execute_query",
        ).model_dump()

    # Clamp limit to valid range (1-10000)
    limit = max(1, min(10000, limit))

    app_ctx = ctx.request_context.lifespan_context
    service = QueryService(
        pool=app_ctx.pool,
        statement_timeout=app_ctx.settings.database.statement_timeout,
    )

    result = await service.execute_query(
        sql=sql,
        params=params,
        max_rows=limit,
        timeout_ms=timeout_ms,
    )

    if isinstance(result, ToolError):
        return result.model_dump()

    return result


@mcp.tool()
async def explain_query(
    sql: str,
    params: dict[str, Any] | list[Any] | None = None,
    format: str = "text",
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ExplainQueryOutput | dict[str, Any]:
    """Get the execution plan for a read-only SQL query on SAP HANA.

    Uses HANA's EXPLAIN PLAN mechanism to analyze query performance without
    executing the query. Returns plan details including operator names,
    costs, cardinality, and execution engine information.

    This tool is read-only -- it transparently handles the write-read-cleanup
    cycle of HANA's EXPLAIN_PLAN_TABLE.

    Args:
        sql: SQL query to explain (SELECT/WITH only).
        params: Bind parameter values for accurate cost estimates.
        format: Output format for the plan ("text" or "json"). Default: "text".

    Returns:
        Execution plan with plan nodes and cost estimates.

    Security:
        Only SELECT and WITH...SELECT queries are accepted for explanation.
    """
    logger.debug(
        "explain_query called with sql=%r, format=%s",
        _truncate_for_log(sql),
        format,
    )

    if ctx is None:
        logger.error("explain_query: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="explain_query",
        ).model_dump()

    # Validate format (fallback to text)
    if format not in ("text", "json"):
        format = "text"

    app_ctx = ctx.request_context.lifespan_context
    service = QueryService(
        pool=app_ctx.pool,
        statement_timeout=app_ctx.settings.database.statement_timeout,
    )

    result = await service.explain_query(
        sql=sql,
        params=params,
        format=format,
    )

    if isinstance(result, ToolError):
        return result.model_dump()

    return result
