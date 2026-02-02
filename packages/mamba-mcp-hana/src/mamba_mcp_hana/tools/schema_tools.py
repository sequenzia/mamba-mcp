"""Layer 1: Schema Discovery MCP Tools.

Registers 4 MCP tools for schema discovery operations with the FastMCP
server instance. Each tool extracts the connection pool from the server
context, delegates to SchemaService, and returns JSON-serialized output.

Based on Spec Section 5.1, 9.2.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_hana.database.schema_service import SchemaService
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error
from mamba_mcp_hana.server import AppContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_schemas(
    include_system: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """List all database schemas in the SAP HANA instance.

    Enumerates available schemas with their names, owners, and table counts.
    System schemas (_SYS_*, SYS, SYSTEM) are excluded by default. Use this
    as the first step to explore an unknown HANA database structure.

    Args:
        include_system: Include system schemas in the listing. Default: False

    Returns:
        JSON string with schema information including names, owners, and table counts.

    Example:
        list_schemas() -> {"schemas": [{"name": "MY_SCHEMA", ...}], "count": 1}
    """
    logger.debug("list_schemas called with include_system=%s", include_system)

    if ctx is None:
        logger.error("list_schemas: No context available")
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="list_schemas",
        )
        return error.model_dump_json()

    app_ctx = ctx.request_context.lifespan_context
    service = SchemaService(app_ctx.pool)

    try:
        result = await service.list_schemas(include_system=include_system)
    except Exception as exc:
        logger.error("list_schemas failed: %s", exc)
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to list schemas: {exc}",
            tool_name="list_schemas",
            input_received={"include_system": include_system},
        )
        return error.model_dump_json()

    if isinstance(result, ToolError):
        return result.model_dump_json()

    return result.model_dump_json()


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_tables(
    schema_name: str,
    include_views: bool = True,
    name_pattern: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """List all tables and views in a specific SAP HANA schema.

    Returns tables and optionally views with metadata including record counts,
    column counts, and store type (COLUMN/ROW). Use name_pattern for SQL LIKE
    filtering to narrow results in large schemas.

    Args:
        schema_name: Schema to list tables from.
        include_views: Include views in the listing. Default: True
        name_pattern: Optional SQL LIKE pattern to filter table names (e.g., 'USER%').

    Returns:
        JSON string with table information including names, types, and record counts.

    Example:
        list_tables(schema_name="MY_SCHEMA") -> {"tables": [...], "count": 15}
    """
    logger.debug(
        "list_tables called with schema_name=%s, include_views=%s, name_pattern=%s",
        schema_name,
        include_views,
        name_pattern,
    )

    if ctx is None:
        logger.error("list_tables: No context available")
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="list_tables",
        )
        return error.model_dump_json()

    app_ctx = ctx.request_context.lifespan_context
    service = SchemaService(app_ctx.pool)

    try:
        result = await service.list_tables(
            schema_name=schema_name,
            include_views=include_views,
            name_pattern=name_pattern,
        )
    except Exception as exc:
        logger.error("list_tables failed: %s", exc)
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to list tables: {exc}",
            tool_name="list_tables",
            input_received={
                "schema_name": schema_name,
                "include_views": include_views,
                "name_pattern": name_pattern,
            },
        )
        return error.model_dump_json()

    if isinstance(result, ToolError):
        return result.model_dump_json()

    return result.model_dump_json()


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def describe_table(
    table_name: str,
    schema_name: str,
    include_indexes: bool = True,
    include_constraints: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get detailed structure of a SAP HANA table or view.

    Returns comprehensive table information including columns with data types,
    lengths, nullability, defaults, and comments. Also includes indexes and
    constraints for tables (skipped for views).

    Args:
        table_name: Name of the table or view to describe.
        schema_name: Schema containing the table.
        include_indexes: Include index information. Default: True
        include_constraints: Include constraint information. Default: True

    Returns:
        JSON string with columns, indexes, and constraints.

    Example:
        describe_table(table_name="USERS", schema_name="MY_SCHEMA")
    """
    logger.debug(
        "describe_table called with table_name=%s, schema_name=%s, "
        "include_indexes=%s, include_constraints=%s",
        table_name,
        schema_name,
        include_indexes,
        include_constraints,
    )

    if ctx is None:
        logger.error("describe_table: No context available")
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="describe_table",
        )
        return error.model_dump_json()

    app_ctx = ctx.request_context.lifespan_context
    service = SchemaService(app_ctx.pool)

    try:
        result = await service.describe_table(
            schema_name=schema_name,
            table_name=table_name,
            include_indexes=include_indexes,
            include_constraints=include_constraints,
        )
    except Exception as exc:
        logger.error("describe_table failed: %s", exc)
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to describe table: {exc}",
            tool_name="describe_table",
            input_received={
                "table_name": table_name,
                "schema_name": schema_name,
                "include_indexes": include_indexes,
                "include_constraints": include_constraints,
            },
        )
        return error.model_dump_json()

    if isinstance(result, ToolError):
        return result.model_dump_json()

    return result.model_dump_json()


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def get_sample_rows(
    table_name: str,
    schema_name: str,
    limit: int = 10,
    columns: list[str] | None = None,
    where_clause: str | None = None,
    randomize: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get sample rows from a SAP HANA table.

    Retrieves example rows to understand data patterns, formats, and values.
    Supports column selection for wide tables, WHERE filtering, and random
    row selection via ORDER BY RAND().

    Args:
        table_name: Name of the table to sample.
        schema_name: Schema containing the table.
        limit: Number of sample rows to retrieve (1-100). Default: 10
        columns: Specific columns to include (None for all columns).
        where_clause: Optional WHERE clause without the 'WHERE' keyword.
        randomize: Randomize row selection (slower on large tables). Default: False

    Returns:
        JSON string with sample rows, column names, and total row count.

    Example:
        get_sample_rows(table_name="ORDERS", schema_name="MY_SCHEMA", limit=5)
    """
    logger.debug(
        "get_sample_rows called with table_name=%s, schema_name=%s, limit=%d, randomize=%s",
        table_name,
        schema_name,
        limit,
        randomize,
    )

    if ctx is None:
        logger.error("get_sample_rows: No context available")
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="get_sample_rows",
        )
        return error.model_dump_json()

    # Validate limit range before calling service
    if limit < 1 or limit > 100:
        error = create_tool_error(
            code=ErrorCode.PARAMETER_ERROR,
            message=f"limit must be between 1 and 100, got {limit}",
            tool_name="get_sample_rows",
            input_received={"table_name": table_name, "schema_name": schema_name, "limit": limit},
        )
        return error.model_dump_json()

    app_ctx = ctx.request_context.lifespan_context
    service = SchemaService(app_ctx.pool)

    try:
        result = await service.get_sample_rows(
            schema_name=schema_name,
            table_name=table_name,
            limit=limit,
            columns=columns,
            where_clause=where_clause,
            randomize=randomize,
        )
    except Exception as exc:
        logger.error("get_sample_rows failed: %s", exc)
        input_received: dict[str, Any] = {
            "table_name": table_name,
            "schema_name": schema_name,
            "limit": limit,
        }
        if columns is not None:
            input_received["columns"] = columns
        if where_clause is not None:
            input_received["where_clause"] = where_clause
        if randomize:
            input_received["randomize"] = randomize

        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to get sample rows: {exc}",
            tool_name="get_sample_rows",
            input_received=input_received,
        )
        return error.model_dump_json()

    if isinstance(result, ToolError):
        return result.model_dump_json()

    return result.model_dump_json()
