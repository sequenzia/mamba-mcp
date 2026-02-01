"""Layer 1: Schema Discovery Tools.

These tools help LLMs discover and understand database schema structure.
"""

import logging
import time
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_pg.database.schema import SchemaService
from mamba_mcp_pg.errors import ErrorCode, create_tool_error
from mamba_mcp_pg.models.schema import (
    ColumnInfo,
    ConstraintInfo,
    DescribeTableOutput,
    GetSampleRowsOutput,
    IndexInfo,
    ListSchemasOutput,
    ListTablesOutput,
    SchemaInfo,
    TableInfo,
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
async def list_schemas(
    include_system: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListSchemasOutput | dict[str, Any]:
    """List all database schemas.

    Enumerate all non-system schemas in the database, returning their names,
    owners, descriptions, and table counts. Use this as the first step to
    explore an unknown database structure.

    Args:
        include_system: Include system schemas (pg_*, information_schema). Default: False

    Returns:
        List of schemas with metadata including table counts.

    Example:
        list_schemas() -> {"schemas": [{"name": "public", "table_count": 15}], "total_count": 1}
    """
    start_time = time.perf_counter()
    logger.debug("list_schemas called with include_system=%s", include_system)

    if ctx is None:
        logger.error("list_schemas: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "list_schemas",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = SchemaService(conn, app_ctx.settings.database.statement_timeout)
            schemas = await service.list_schemas(include_system=include_system)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_schemas completed in %.2fms, returned %d schemas",
            elapsed_ms,
            len(schemas),
        )
        return ListSchemasOutput(
            schemas=[SchemaInfo(**s) for s in schemas],
            total_count=len(schemas),
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_schemas failed after %.2fms: %s", elapsed_ms, str(e))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(e),
            "list_schemas",
            {"include_system": include_system},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_tables(
    schema_name: str = "public",
    include_views: bool = True,
    name_pattern: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListTablesOutput | dict[str, Any]:
    """List all tables in a schema.

    Returns tables and optionally views with metadata including row counts,
    sizes, and column counts. Use this to understand what data is available
    in a specific schema.

    Args:
        schema_name: Schema to list tables from. Default: "public"
        include_views: Include views in the listing. Default: True
        name_pattern: Optional LIKE pattern to filter table names (e.g., 'user%')

    Returns:
        List of tables with metadata.

    Example:
        list_tables(schema_name="public") -> {"tables": [...], "total_count": 15}
    """
    start_time = time.perf_counter()
    logger.debug(
        "list_tables called with schema_name=%s, include_views=%s, name_pattern=%s",
        schema_name,
        include_views,
        name_pattern,
    )

    if ctx is None:
        logger.error("list_tables: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "list_tables",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = SchemaService(conn, app_ctx.settings.database.statement_timeout)
            tables = await service.list_tables(
                schema_name=schema_name,
                include_views=include_views,
                name_pattern=name_pattern,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_tables completed in %.2fms, returned %d tables",
            elapsed_ms,
            len(tables),
        )
        return ListTablesOutput(
            tables=[TableInfo(**t) for t in tables],
            schema_name=schema_name,
            total_count=len(tables),
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_tables failed after %.2fms: %s", elapsed_ms, str(e))
        return create_tool_error(
            ErrorCode.SCHEMA_NOT_FOUND
            if "schema" in str(e).lower()
            else ErrorCode.CONNECTION_ERROR,
            str(e),
            "list_tables",
            {"schema_name": schema_name},
        )


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
    schema_name: str = "public",
    include_indexes: bool = True,
    include_constraints: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> DescribeTableOutput | dict[str, Any]:
    """Get detailed structure of a table.

    Returns comprehensive table information including all columns with their
    types, nullability, defaults, and foreign key references. Also includes
    indexes and constraints.

    Args:
        table_name: Name of the table to describe
        schema_name: Schema containing the table. Default: "public"
        include_indexes: Include index information. Default: True
        include_constraints: Include constraint information. Default: True

    Returns:
        Detailed table structure with columns, indexes, and constraints.

    Example:
        describe_table(table_name="users") -> {"columns": [...], "indexes": [...]}
    """
    start_time = time.perf_counter()
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
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "describe_table",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = SchemaService(conn, app_ctx.settings.database.statement_timeout)

            # Check if table exists
            exists = await service.table_exists(schema_name, table_name)
            if not exists:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    "describe_table: table %s.%s not found after %.2fms",
                    schema_name,
                    table_name,
                    elapsed_ms,
                )
                return create_tool_error(
                    ErrorCode.TABLE_NOT_FOUND,
                    f"Table '{table_name}' does not exist in schema '{schema_name}'",
                    "describe_table",
                    {"table_name": table_name, "schema_name": schema_name},
                )

            # Get table metadata
            metadata = await service.get_table_metadata(schema_name, table_name)

            # Get columns
            columns = await service.describe_columns(schema_name, table_name)

            # Get primary key columns
            pk_columns = await service.get_primary_key_columns(schema_name, table_name)

            # Get indexes
            indexes = None
            if include_indexes:
                indexes = await service.describe_indexes(schema_name, table_name)

            # Get constraints
            constraints = None
            if include_constraints:
                constraints = await service.describe_constraints(schema_name, table_name)

        # Transform columns to ColumnInfo with PK info
        column_infos = []
        for col in columns:
            column_infos.append(
                ColumnInfo(
                    name=col["name"],
                    data_type=col.get("udt_name") or col["data_type"],
                    is_nullable=col["is_nullable"],
                    default_value=col.get("default_value"),
                    description=col.get("description"),
                    is_primary_key=col["name"] in pk_columns,
                    is_unique=False,  # Would need to derive from constraints
                    foreign_key=None,  # Would need FK lookup
                    character_maximum_length=col.get("character_maximum_length"),
                    numeric_precision=col.get("numeric_precision"),
                    numeric_scale=col.get("numeric_scale"),
                )
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "describe_table completed in %.2fms, table=%s.%s, columns=%d",
            elapsed_ms,
            schema_name,
            table_name,
            len(column_infos),
        )
        return DescribeTableOutput(
            table_name=table_name,
            schema_name=schema_name,
            type=metadata.get("type", "table") if metadata else "table",
            description=metadata.get("description") if metadata else None,
            columns=column_infos,
            indexes=[IndexInfo(**i) for i in indexes] if indexes else None,
            constraints=[ConstraintInfo(**c) for c in constraints] if constraints else None,
            estimated_row_count=metadata.get("estimated_row_count", 0) if metadata else 0,
            size_pretty=metadata.get("size_pretty") if metadata else None,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("describe_table failed after %.2fms: %s", elapsed_ms, str(e))
        return create_tool_error(
            ErrorCode.TABLE_NOT_FOUND
            if "not exist" in str(e).lower()
            else ErrorCode.CONNECTION_ERROR,
            str(e),
            "describe_table",
            {"table_name": table_name, "schema_name": schema_name},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,  # False if randomize=true
        openWorldHint=False,
    )
)
async def get_sample_rows(
    table_name: str,
    schema_name: str = "public",
    limit: int = 5,
    columns: list[str] | None = None,
    where_clause: str | None = None,
    randomize: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> GetSampleRowsOutput | dict[str, Any]:
    """Get sample rows from a table.

    Retrieves example rows to understand actual data patterns, formats, and values.
    Useful for discovering enum-like values, date formats, and data distributions.

    Args:
        table_name: Name of the table to sample
        schema_name: Schema containing the table. Default: "public"
        limit: Number of sample rows (1-100). Default: 5
        columns: Specific columns to include (null for all)
        where_clause: Optional WHERE clause without 'WHERE' keyword
        randomize: Randomize row selection (slower on large tables). Default: False

    Returns:
        Sample rows with column names and values.

    Example:
        get_sample_rows(table_name="orders", limit=3) -> {"rows": [...]}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_sample_rows called with table_name=%s, schema_name=%s, "
        "limit=%d, columns_count=%d, has_where=%s, randomize=%s",
        table_name,
        schema_name,
        limit,
        len(columns) if columns else 0,
        where_clause is not None,
        randomize,
    )

    if ctx is None:
        logger.error("get_sample_rows: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_sample_rows",
        )

    # Clamp limit to valid range
    limit = max(1, min(100, limit))

    app_ctx = ctx.request_context.lifespan_context

    try:
        async with app_ctx.engine.connect() as conn:
            service = SchemaService(conn, app_ctx.settings.database.statement_timeout)

            # Check if table exists
            exists = await service.table_exists(schema_name, table_name)
            if not exists:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    "get_sample_rows: table %s.%s not found after %.2fms",
                    schema_name,
                    table_name,
                    elapsed_ms,
                )
                return create_tool_error(
                    ErrorCode.TABLE_NOT_FOUND,
                    f"Table '{table_name}' does not exist in schema '{schema_name}'",
                    "get_sample_rows",
                    {"table_name": table_name, "schema_name": schema_name},
                )

            # Get metadata for total rows
            metadata = await service.get_table_metadata(schema_name, table_name)
            total_rows = metadata.get("estimated_row_count", 0) if metadata else 0

            result = await service.get_sample_rows(
                schema_name=schema_name,
                table_name=table_name,
                limit=limit,
                columns=columns,
                where_clause=where_clause,
                randomize=randomize,
            )

        note = None
        if randomize:
            note = "Rows selected randomly"
        elif where_clause:
            note = f"Filtered by: {where_clause}"
        else:
            note = "Showing first rows ordered by primary key"

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_sample_rows completed in %.2fms, returned %d rows",
            elapsed_ms,
            result["row_count"],
        )
        return GetSampleRowsOutput(
            table_name=table_name,
            schema_name=schema_name,
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"],
            total_table_rows=max(0, total_rows),
            note=note,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_sample_rows failed after %.2fms: %s", elapsed_ms, str(e))
        return create_tool_error(
            ErrorCode.TABLE_NOT_FOUND
            if "not exist" in str(e).lower()
            else ErrorCode.CONNECTION_ERROR,
            str(e),
            "get_sample_rows",
            {"table_name": table_name, "schema_name": schema_name},
        )
