"""Layer 2: Relationship Discovery Tools.

These tools help LLMs discover foreign key relationships and join paths
between tables.
"""

import logging
import time
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_pg.database.relationships import RelationshipService
from mamba_mcp_pg.errors import ErrorCode, create_tool_error
from mamba_mcp_pg.models.relationships import (
    FindJoinPathOutput,
    ForeignKeyRelation,
    GetForeignKeysOutput,
    JoinPath,
    JoinStep,
)
from mamba_mcp_pg.server import AppContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_foreign_keys(
    table_name: str,
    schema_name: str = "public",
    ctx: Context[ServerSession, AppContext] | None = None,
) -> GetForeignKeysOutput | dict[str, Any]:
    """Get foreign key relationships for a table.

    Returns both outgoing (this table references other tables) and incoming
    (other tables reference this table) foreign key relationships.

    Args:
        table_name: Name of the table
        schema_name: Schema containing the table. Default: "public"

    Returns:
        Outgoing and incoming foreign key relationships.

    Example:
        get_foreign_keys(table_name="orders") -> {"outgoing": [...], "incoming": [...]}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_foreign_keys called with table_name=%s, schema_name=%s",
        table_name,
        schema_name,
    )

    if ctx is None:
        logger.error("get_foreign_keys: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_foreign_keys",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = RelationshipService(conn, app_ctx.settings.database.statement_timeout)
            outgoing = await service.get_outgoing_fks(schema_name, table_name)
            incoming = await service.get_incoming_fks(schema_name, table_name)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_foreign_keys completed in %.2fms, outgoing=%d, incoming=%d",
            elapsed_ms,
            len(outgoing),
            len(incoming),
        )
        return GetForeignKeysOutput(
            table_name=table_name,
            schema_name=schema_name,
            outgoing=[ForeignKeyRelation(**fk) for fk in outgoing],
            incoming=[ForeignKeyRelation(**fk) for fk in incoming],
            outgoing_count=len(outgoing),
            incoming_count=len(incoming),
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_foreign_keys failed after %.2fms: %s", elapsed_ms, str(e))
        return create_tool_error(
            ErrorCode.TABLE_NOT_FOUND
            if "not exist" in str(e).lower()
            else ErrorCode.CONNECTION_ERROR,
            str(e),
            "get_foreign_keys",
            {"table_name": table_name, "schema_name": schema_name},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def find_join_path(
    from_table: str,
    to_table: str,
    from_schema: str = "public",
    to_schema: str = "public",
    max_depth: int = 4,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> FindJoinPathOutput | dict[str, Any]:
    """Find join paths between two tables.

    Discovers possible paths to join two tables via foreign key relationships.
    Returns SQL examples for each path found.

    Args:
        from_table: Starting table name
        to_table: Target table name
        from_schema: Schema of starting table. Default: "public"
        to_schema: Schema of target table. Default: "public"
        max_depth: Maximum joins to traverse (1-6). Default: 4

    Returns:
        List of possible join paths with SQL examples.

    Example:
        find_join_path(from_table="order_items", to_table="users") -> {"paths": [...]}
    """
    start_time = time.perf_counter()
    logger.debug(
        "find_join_path called with from_table=%s, to_table=%s, "
        "from_schema=%s, to_schema=%s, max_depth=%d",
        from_table,
        to_table,
        from_schema,
        to_schema,
        max_depth,
    )

    if ctx is None:
        logger.error("find_join_path: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "find_join_path",
        )

    # Clamp max_depth to valid range
    max_depth = max(1, min(6, max_depth))

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = RelationshipService(conn, app_ctx.settings.database.statement_timeout)
            paths = await service.find_join_path(
                from_schema, from_table, to_schema, to_table, max_depth
            )

        # Convert paths to JoinPath objects
        join_paths = []
        for path in paths:
            steps = []
            for edge in path:
                from_parts = edge["from"].split(".")
                to_parts = edge["to"].split(".")

                # Determine join type based on FK direction
                is_reversed = edge.get("reversed", False)
                join_type = "LEFT JOIN" if is_reversed else "INNER JOIN"

                steps.append(
                    JoinStep(
                        from_schema=from_parts[0],
                        from_table=from_parts[1],
                        from_column=edge["from_col"],
                        to_schema=to_parts[0],
                        to_table=to_parts[1],
                        to_column=edge["to_col"],
                        join_type=join_type,
                        constraint_name=edge["constraint"],
                    )
                )

            # Generate SQL example
            sql_parts = [f"FROM {from_schema}.{from_table}"]
            prev_table = from_table
            for step in steps:
                sql_parts.append(
                    f"{step.join_type} {step.to_schema}.{step.to_table} "
                    f"ON {prev_table}.{step.from_column} = {step.to_table}.{step.to_column}"
                )
                prev_table = step.to_table

            join_paths.append(
                JoinPath(
                    steps=steps,
                    depth=len(steps),
                    sql_example=" ".join(sql_parts),
                )
            )

        note = None
        if len(join_paths) > 1:
            note = f"Multiple paths found ({len(join_paths)}), showing all"
        elif len(join_paths) == 0:
            note = "No path found between tables via foreign keys"

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "find_join_path completed in %.2fms, paths_found=%d",
            elapsed_ms,
            len(join_paths),
        )
        return FindJoinPathOutput(
            from_table=from_table,
            to_table=to_table,
            paths=join_paths,
            paths_found=len(join_paths),
            note=note,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("find_join_path failed after %.2fms: %s", elapsed_ms, str(e))
        return create_tool_error(
            ErrorCode.PATH_NOT_FOUND if "path" in str(e).lower() else ErrorCode.CONNECTION_ERROR,
            str(e),
            "find_join_path",
            {
                "from_table": from_table,
                "to_table": to_table,
                "from_schema": from_schema,
                "to_schema": to_schema,
            },
        )
