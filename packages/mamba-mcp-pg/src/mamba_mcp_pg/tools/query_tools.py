"""Layer 3: Query Execution Tools.

These tools allow LLMs to execute read-only SQL queries and analyze
query execution plans.
"""

import logging
import time
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_pg.database.queries import QueryService, QueryValidationError
from mamba_mcp_pg.errors import ErrorCode, create_tool_error
from mamba_mcp_pg.models.results import (
    ExecuteQueryOutput,
    ExplainQueryOutput,
    QueryColumn,
)
from mamba_mcp_pg.server import AppContext, mcp

logger = logging.getLogger(__name__)


def _truncate_for_log(text: str, max_length: int = 100) -> str:
    """Truncate text for logging to avoid huge log entries."""
    return text[:max_length] + "..." if len(text) > max_length else text


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def execute_query(
    sql: str,
    params: list[Any] | None = None,
    limit: int = 1000,
    timeout_ms: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ExecuteQueryOutput | dict[str, Any]:
    """Execute a read-only SQL query.

    Executes SELECT queries with parameterized values. Use $1, $2, etc. for
    parameter placeholders. Write operations are blocked for security.

    Args:
        sql: SQL SELECT query. Use $1, $2, etc. for parameters.
        params: Parameter values matching $1, $2, etc.
        limit: Maximum rows to return (1-10000). Default: 1000
        timeout_ms: Query timeout in milliseconds

    Returns:
        Query results with columns and rows.

    Example:
        execute_query(
            sql="SELECT * FROM users WHERE status = $1",
            params=["active"]
        ) -> {"rows": [...], "row_count": 42}

    Security:
        Only SELECT and WITH...SELECT queries are allowed.
        INSERT, UPDATE, DELETE, DROP, etc. are blocked.
    """
    start_time = time.perf_counter()
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
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "execute_query",
        )

    # Clamp limit to valid range
    limit = max(1, min(10000, limit))

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = QueryService(conn, app_ctx.settings.database.statement_timeout)
            result = await service.execute_query(
                sql=sql,
                params=params,
                limit=limit,
                timeout_ms=timeout_ms,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "execute_query completed in %.2fms, rows=%d, has_more=%s",
            elapsed_ms,
            result["row_count"],
            result["has_more"],
        )
        return ExecuteQueryOutput(
            columns=[QueryColumn(**c) for c in result["columns"]],
            rows=result["rows"],
            row_count=result["row_count"],
            has_more=result["has_more"],
            execution_time_ms=result["execution_time_ms"],
            query_hash=result["query_hash"],
        )
    except QueryValidationError as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("execute_query validation failed after %.2fms: %s", elapsed_ms, e.message)
        return create_tool_error(
            e.code,
            e.message,
            "execute_query",
            {"sql": sql, "params": params},
            suggestion=e.suggestion,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("execute_query failed after %.2fms: %s", elapsed_ms, str(e))

        error_str = str(e).lower()
        if "timeout" in error_str:
            code = ErrorCode.QUERY_TIMEOUT
        elif "permission" in error_str or "denied" in error_str:
            code = ErrorCode.PERMISSION_DENIED
        elif "syntax" in error_str:
            code = ErrorCode.INVALID_SQL
        else:
            code = ErrorCode.CONNECTION_ERROR

        return create_tool_error(
            code,
            str(e),
            "execute_query",
            {"sql": sql, "params": params},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,  # Unless analyze=True
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def explain_query(
    sql: str,
    params: list[Any] | None = None,
    analyze: bool = False,
    format: str = "text",
    verbose: bool = False,
    buffers: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ExplainQueryOutput | dict[str, Any]:
    """Get the execution plan for a query.

    Returns PostgreSQL's query execution plan without executing the query.
    Useful for understanding query performance before execution.

    Args:
        sql: SQL query to explain
        params: Parameter values for accurate estimates
        analyze: Actually execute query for real timings. Default: False
        format: Output format (text, json, yaml). Default: "text"
        verbose: Include additional detail. Default: False
        buffers: Include buffer statistics (requires analyze=True). Default: False

    Returns:
        Query execution plan with cost estimates.

    Example:
        explain_query(sql="SELECT * FROM orders WHERE status = 'pending'")
    """
    start_time = time.perf_counter()
    logger.debug(
        "explain_query called with sql=%r, analyze=%s, format=%s",
        _truncate_for_log(sql),
        analyze,
        format,
    )

    if ctx is None:
        logger.error("explain_query: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "explain_query",
        )

    # Validate format
    if format not in ("text", "json", "yaml"):
        format = "text"

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = QueryService(conn, app_ctx.settings.database.statement_timeout)
            result = await service.explain_query(
                sql=sql,
                params=params,
                analyze=analyze,
                format=format,
                verbose=verbose,
                buffers=buffers,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "explain_query completed in %.2fms, format=%s, analyze=%s",
            elapsed_ms,
            format,
            analyze,
        )
        return ExplainQueryOutput(**result)
    except QueryValidationError as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("explain_query validation failed after %.2fms: %s", elapsed_ms, e.message)
        return create_tool_error(
            e.code,
            e.message,
            "explain_query",
            {"sql": sql, "params": params},
            suggestion=e.suggestion,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("explain_query failed after %.2fms: %s", elapsed_ms, str(e))

        error_str = str(e).lower()
        if "timeout" in error_str:
            code = ErrorCode.QUERY_TIMEOUT
        elif "syntax" in error_str:
            code = ErrorCode.INVALID_SQL
        else:
            code = ErrorCode.CONNECTION_ERROR

        return create_tool_error(
            code,
            str(e),
            "explain_query",
            {"sql": sql, "params": params},
        )
