"""Layer 2: Relationship Discovery Tools.

These tools help LLMs discover foreign key relationships and join paths
between tables in SAP HANA databases.

Based on Spec Section 5.2, 9.2.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from mamba_mcp_hana.database.relationship_service import RelationshipService
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error
from mamba_mcp_hana.models.relationships import FindJoinPathOutput, ForeignKeysOutput
from mamba_mcp_hana.server import AppContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_foreign_keys(
    table_name: str,
    schema_name: str,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ForeignKeysOutput | dict[str, Any]:
    """Get foreign key relationships for a table.

    Returns both outgoing (this table references other tables) and incoming
    (other tables reference this table) foreign key relationships. Includes
    constraint names, source/target schemas, tables, columns, and delete rules.

    Note: SAP HANA row store tables do not support foreign key constraints.
    If the table uses row store, results may be empty.

    Args:
        table_name: Name of the table to inspect.
        schema_name: Schema containing the table.

    Returns:
        Outgoing and incoming foreign key details.

    Example:
        get_foreign_keys(table_name="ORDERS", schema_name="SALES")
    """
    if ctx is None:
        logger.error("get_foreign_keys: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="get_foreign_keys",
        ).model_dump()

    app_ctx = ctx.request_context.lifespan_context
    service = RelationshipService(app_ctx.pool)

    result = await service.get_foreign_keys(
        schema_name=schema_name,
        table_name=table_name,
    )

    if isinstance(result, ToolError):
        return result.model_dump()

    return result


@mcp.tool()
async def find_join_path(
    from_table: str,
    to_table: str,
    from_schema: str,
    to_schema: str | None = None,
    max_depth: int = 4,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> FindJoinPathOutput | dict[str, Any]:
    """Find join paths between two tables via foreign key relationships.

    Uses breadth-first search to discover paths through foreign key
    relationships. Returns all paths sorted by length (shortest first)
    with generated SQL JOIN examples for each path.

    If ``to_schema`` is not provided, it defaults to ``from_schema``
    (same-schema join).

    Note: SAP HANA row store tables do not support foreign key constraints,
    so join paths involving row store tables may not be found.

    Args:
        from_table: Starting table name.
        to_table: Target table name.
        from_schema: Schema of the starting table.
        to_schema: Schema of the target table (defaults to from_schema).
        max_depth: Maximum number of joins to traverse (1-6, default 4).

    Returns:
        Discovered join paths and SQL JOIN examples.

    Example:
        find_join_path(
            from_table="ORDER_ITEMS",
            to_table="CUSTOMERS",
            from_schema="SALES",
        )
    """
    if ctx is None:
        logger.error("find_join_path: No context available")
        return create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="No server context available",
            tool_name="find_join_path",
        ).model_dump()

    # Default to_schema to from_schema if not provided
    resolved_to_schema = to_schema if to_schema is not None else from_schema

    # Clamp max_depth to valid range (1-6)
    clamped_depth = max(1, min(6, max_depth))

    app_ctx = ctx.request_context.lifespan_context
    service = RelationshipService(app_ctx.pool)

    result = await service.find_join_path(
        from_schema=from_schema,
        from_table=from_table,
        to_schema=resolved_to_schema,
        to_table=to_table,
        max_depth=clamped_depth,
    )

    if isinstance(result, ToolError):
        return result.model_dump()

    return result
