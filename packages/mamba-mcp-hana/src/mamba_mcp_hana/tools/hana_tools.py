"""Layer 4: HANA-Specific MCP Tools.

Registers 3 MCP tools for HANA-specific database operations with the FastMCP
server instance. Each tool extracts the connection pool from the server
context, delegates to HanaService, and returns typed output models.

Based on Spec Section 5.4, 9.3.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from mamba_mcp_hana.database.hana import HanaService
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error
from mamba_mcp_hana.models.hana import (
    GetTableStoreTypeOutput,
    ListCalcViewsOutput,
    ListProceduresOutput,
)
from mamba_mcp_hana.server import AppContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool()
async def list_calculation_views(
    schema_name: str,
    include_columns: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListCalcViewsOutput | dict[str, Any]:
    """List calculation views in a SAP HANA schema.

    Enumerates calculation views (CALC, JOIN, OLAP types) from SYS.VIEWS
    with their names, types, validity status, and column counts. Optionally
    includes column metadata (names, data types) for each view.

    Note: Accessing data through calculation views may require analytic
    privileges. The views are listed based on metadata visibility, but data
    queries against these views may fail if the required analytic privileges
    are not granted.

    Args:
        schema_name: Schema to list calculation views from.
        include_columns: Include column metadata for each view. Default: False

    Returns:
        Calculation view information including names, types, validity status,
        and column counts.

    Example:
        list_calculation_views(schema_name="MY_SCHEMA")
        -> {"views": [...], "schema_name": "MY_SCHEMA", "count": 5}
    """
    logger.debug(
        "list_calculation_views called with schema_name=%s, include_columns=%s",
        schema_name,
        include_columns,
    )

    if ctx is None:
        logger.error("list_calculation_views: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="list_calculation_views",
        ).model_dump()

    app_ctx = ctx.request_context.lifespan_context
    service = HanaService(app_ctx.pool)

    try:
        result = await service.list_calculation_views(
            schema_name=schema_name,
            include_columns=include_columns,
        )
    except Exception as exc:
        logger.error("list_calculation_views failed: %s", exc)
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to list calculation views: {exc}",
            tool_name="list_calculation_views",
            input_received={
                "schema_name": schema_name,
                "include_columns": include_columns,
            },
        ).model_dump()

    if isinstance(result, ToolError):
        return result.model_dump()

    return result


@mcp.tool()
async def get_table_store_type(
    table_name: str,
    schema_name: str,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> GetTableStoreTypeOutput | dict[str, Any]:
    """Get the storage type (COLUMN or ROW) for a SAP HANA table.

    Returns whether a table uses column store or row store, along with
    partitioning information, compression status, and implications text
    explaining how the store type affects query optimization and feature
    support.

    Column store: Optimized for analytical queries, aggregations, and large
    scans. Supports foreign key constraints. Data is compressed by default.
    Best for read-heavy analytical workloads and large datasets.

    Row store: Optimized for point lookups, single-row operations, and
    transactional workloads. Uses traditional row-based storage without
    columnar compression. Best for OLTP patterns with frequent single-record
    access.

    Args:
        table_name: Name of the table to check.
        schema_name: Schema containing the table.

    Returns:
        Store type details including type, partitioning, compression,
        and implications.

    Example:
        get_table_store_type(table_name="ORDERS", schema_name="SALES")
        -> {"store_info": {"store_type": "COLUMN", ...}}
    """
    logger.debug(
        "get_table_store_type called with table_name=%s, schema_name=%s",
        table_name,
        schema_name,
    )

    if ctx is None:
        logger.error("get_table_store_type: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="get_table_store_type",
        ).model_dump()

    app_ctx = ctx.request_context.lifespan_context
    service = HanaService(app_ctx.pool)

    try:
        result = await service.get_table_store_type(
            schema_name=schema_name,
            table_name=table_name,
        )
    except Exception as exc:
        logger.error("get_table_store_type failed: %s", exc)
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to get table store type: {exc}",
            tool_name="get_table_store_type",
            input_received={
                "table_name": table_name,
                "schema_name": schema_name,
            },
        ).model_dump()

    if isinstance(result, ToolError):
        return result.model_dump()

    return result


@mcp.tool()
async def list_procedures(
    schema_name: str,
    include_parameters: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListProceduresOutput | dict[str, Any]:
    """List stored procedures in a SAP HANA schema.

    Enumerates stored procedures with their names, types (SQLScript, R, L),
    read-only status, and parameter counts. Optionally includes parameter
    details (name, data type, direction IN/OUT/INOUT) for each procedure.

    Args:
        schema_name: Schema to list procedures from.
        include_parameters: Include parameter details for each procedure.
            Default: False

    Returns:
        Procedure information including names, types, parameter counts,
        and optionally parameter details.

    Example:
        list_procedures(schema_name="MY_SCHEMA")
        -> {"procedures": [...], "schema_name": "MY_SCHEMA", "count": 3}
    """
    logger.debug(
        "list_procedures called with schema_name=%s, include_parameters=%s",
        schema_name,
        include_parameters,
    )

    if ctx is None:
        logger.error("list_procedures: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="list_procedures",
        ).model_dump()

    app_ctx = ctx.request_context.lifespan_context
    service = HanaService(app_ctx.pool)

    try:
        result = await service.list_procedures(
            schema_name=schema_name,
            include_parameters=include_parameters,
        )
    except Exception as exc:
        logger.error("list_procedures failed: %s", exc)
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message=f"Failed to list procedures: {exc}",
            tool_name="list_procedures",
            input_received={
                "schema_name": schema_name,
                "include_parameters": include_parameters,
            },
        ).model_dump()

    if isinstance(result, ToolError):
        return result.model_dump()

    return result
