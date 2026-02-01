"""HANA-specific database service (Layer 4).

Provides async methods for HANA-specific features: calculation views,
table store type queries, and stored procedure listing.

Based on Spec Section 5.4 and 9.3.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Any

from mamba_mcp_sap_hana.database.connection import HanaConnectionPool
from mamba_mcp_sap_hana.errors import (
    ErrorCode,
    ToolError,
    create_tool_error,
    suggest_similar,
)
from mamba_mcp_sap_hana.models.hana import (
    CalcViewColumnInfo,
    CalcViewInfo,
    GetTableStoreTypeOutput,
    ListCalcViewsOutput,
    ListProceduresOutput,
    ProcedureInfo,
    ProcedureParameterInfo,
    StoreTypeInfo,
)

logger = logging.getLogger(__name__)

# --- SQL Queries for HANA-Specific Features ---

# Calculation views: query SYS.VIEWS filtering for calc view types
LIST_CALC_VIEWS_SQL = """
SELECT
    VIEW_NAME,
    SCHEMA_NAME,
    VIEW_TYPE,
    COMMENTS,
    IS_VALID,
    (SELECT COUNT(*) FROM SYS.VIEW_COLUMNS vc
     WHERE vc.SCHEMA_NAME = v.SCHEMA_NAME AND vc.VIEW_NAME = v.VIEW_NAME) AS COLUMN_COUNT
FROM SYS.VIEWS v
WHERE SCHEMA_NAME = ?
  AND VIEW_TYPE IN ('CALC', 'JOIN', 'OLAP')
ORDER BY VIEW_NAME
"""

# Calc view column metadata
CALC_VIEW_COLUMNS_SQL = """
SELECT
    COLUMN_NAME,
    DATA_TYPE_NAME,
    COMMENTS,
    IS_NULLABLE
FROM SYS.VIEW_COLUMNS
WHERE SCHEMA_NAME = ? AND VIEW_NAME = ?
ORDER BY POSITION
"""

# Store type query: table metadata from SYS.TABLES
TABLE_STORE_TYPE_SQL = """
SELECT
    TABLE_NAME,
    SCHEMA_NAME,
    IS_COLUMN_TABLE,
    HAS_PARTITIONS,
    PARTITION_SPEC,
    IS_PRELOAD
FROM SYS.TABLES
WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
"""

# Check if schema exists
CHECK_SCHEMA_EXISTS_SQL = """
SELECT SCHEMA_NAME FROM SYS.SCHEMAS WHERE SCHEMA_NAME = ?
"""

# All schema names for fuzzy matching
ALL_SCHEMA_NAMES_SQL = """
SELECT SCHEMA_NAME FROM SYS.SCHEMAS
"""

# Check if table exists
CHECK_TABLE_EXISTS_SQL = """
SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
"""

# Check if view exists
CHECK_VIEW_EXISTS_SQL = """
SELECT VIEW_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ? AND VIEW_NAME = ?
"""

# All table names in schema for fuzzy matching
ALL_TABLE_NAMES_SQL = """
SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = ?
UNION
SELECT VIEW_NAME AS TABLE_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ?
"""

# Procedure listing
LIST_PROCEDURES_SQL = """
SELECT
    PROCEDURE_NAME,
    SCHEMA_NAME,
    PROCEDURE_TYPE,
    IS_READ_ONLY,
    (SELECT COUNT(*) FROM SYS.PROCEDURE_PARAMETERS pp
     WHERE pp.SCHEMA_NAME = p.SCHEMA_NAME
       AND pp.PROCEDURE_NAME = p.PROCEDURE_NAME) AS PARAMETER_COUNT
FROM SYS.PROCEDURES p
WHERE SCHEMA_NAME = ?
ORDER BY PROCEDURE_NAME
"""

# Procedure parameters
PROCEDURE_PARAMETERS_SQL = """
SELECT
    PARAMETER_NAME,
    DATA_TYPE_NAME,
    PARAMETER_TYPE,
    POSITION,
    DEFAULT_VALUE
FROM SYS.PROCEDURE_PARAMETERS
WHERE SCHEMA_NAME = ? AND PROCEDURE_NAME = ?
ORDER BY POSITION
"""

# Partition count for a table
TABLE_PARTITION_COUNT_SQL = """
SELECT COUNT(*) FROM SYS.TABLE_PARTITIONS
WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
"""

# Implications text for store types
COLUMN_STORE_IMPLICATIONS = (
    "Column store: Optimized for analytical queries, aggregations, and large scans. "
    "Supports foreign key constraints. Data is compressed by default, reducing memory "
    "footprint. Best for read-heavy analytical workloads and large datasets."
)

ROW_STORE_IMPLICATIONS = (
    "Row store: Optimized for point lookups, single-row operations, and transactional "
    "workloads. Uses traditional row-based storage without columnar compression. "
    "Best for OLTP patterns with frequent single-record access."
)

# Analytic privilege note for calc views
CALC_VIEW_PRIVILEGE_NOTE = (
    "Note: Accessing data through calculation views may require analytic privileges. "
    "The views are listed based on metadata visibility, but data queries against "
    "these views may fail if the required analytic privileges are not granted."
)


def _execute_query(
    conn: Any,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[tuple[Any, ...]]:
    """Execute a SQL query on an hdbcli connection and return all rows.

    Args:
        conn: An hdbcli Connection object.
        sql: SQL query to execute.
        params: Query parameters.

    Returns:
        List of result tuples.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()


class HanaService:
    """Async service for HANA-specific operations (Layer 4).

    Provides methods for querying HANA-specific database objects:
    calculation views, table store types, and stored procedures.

    All database operations are run via asyncio.to_thread to avoid
    blocking the event loop with hdbcli's synchronous calls.
    """

    def __init__(self, pool: HanaConnectionPool) -> None:
        """Initialize the HANA service.

        Args:
            pool: Async connection pool for acquiring hdbcli connections.
        """
        self._pool = pool

    async def _verify_schema_exists(
        self,
        schema_name: str,
        tool_name: str,
        input_received: dict[str, Any],
        conn: Any,
    ) -> ToolError | None:
        """Verify a schema exists, returning a ToolError if not found.

        Args:
            schema_name: Schema to check.
            tool_name: Name of the calling tool (for error context).
            input_received: Original input parameters (for error context).
            conn: An active hdbcli connection.

        Returns:
            ToolError if schema not found, None if schema exists.
        """
        rows = await asyncio.to_thread(
            _execute_query, conn, CHECK_SCHEMA_EXISTS_SQL, (schema_name,)
        )
        if rows:
            return None

        # Schema not found -- get candidates for fuzzy matching
        all_schemas = await asyncio.to_thread(_execute_query, conn, ALL_SCHEMA_NAMES_SQL)
        all_names = [r[0] for r in all_schemas]
        suggestions = suggest_similar(schema_name, all_names)

        context: dict[str, Any] = {}
        if suggestions:
            context["similar_schemas"] = suggestions

        return create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message=f"Schema '{schema_name}' not found",
            tool_name=tool_name,
            input_received=input_received,
            context=context if context else None,
            suggestion=(f"Did you mean: {', '.join(suggestions)}?" if suggestions else None),
        )

    async def list_calculation_views(
        self,
        schema_name: str,
        include_columns: bool = False,
        name_pattern: str | None = None,
    ) -> ListCalcViewsOutput | ToolError:
        """List calculation views in a schema.

        Queries SYS.VIEWS for views with VIEW_TYPE indicating calculation
        views (CALC, JOIN, OLAP). Optionally includes column metadata
        from SYS.VIEW_COLUMNS for each view.

        Args:
            schema_name: Schema to list calculation views from.
            include_columns: Include column metadata for each view.
            name_pattern: Optional SQL LIKE/glob pattern to filter view names.

        Returns:
            ListCalcViewsOutput with view information, or ToolError on failure.
        """
        input_received = {
            "schema_name": schema_name,
            "include_columns": include_columns,
            "name_pattern": name_pattern,
        }

        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="list_calculation_views",
                input_received=input_received,
            )

        try:
            # Verify schema exists
            schema_error = await self._verify_schema_exists(
                schema_name, "list_calculation_views", input_received, conn
            )
            if schema_error is not None:
                return schema_error

            # Query calculation views
            rows = await asyncio.to_thread(
                _execute_query, conn, LIST_CALC_VIEWS_SQL, (schema_name,)
            )

            views: list[CalcViewInfo] = []
            for row in rows:
                view_name = row[0]
                view_schema = row[1]
                view_type = row[2] or "CALC"
                description = row[3]
                is_valid_raw = row[4]
                column_count = row[5]

                is_active = (
                    (is_valid_raw == "TRUE")
                    if isinstance(is_valid_raw, str)
                    else bool(is_valid_raw)
                )

                # Optionally fetch column metadata
                columns: list[CalcViewColumnInfo] = []
                if include_columns:
                    col_rows = await asyncio.to_thread(
                        _execute_query,
                        conn,
                        CALC_VIEW_COLUMNS_SQL,
                        (schema_name, view_name),
                    )
                    for col_row in col_rows:
                        columns.append(
                            CalcViewColumnInfo(
                                name=col_row[0],
                                data_type=col_row[1],
                                description=col_row[2],
                            )
                        )

                views.append(
                    CalcViewInfo(
                        name=view_name,
                        schema_name=view_schema,
                        type=view_type,
                        description=description,
                        is_active=is_active,
                        column_count=column_count,
                        columns=columns,
                    )
                )

            # Apply name pattern filtering
            if name_pattern is not None:
                glob_pattern = name_pattern.replace("%", "*").replace("_", "?")
                views = [v for v in views if fnmatch.fnmatchcase(v.name, glob_pattern)]

            return ListCalcViewsOutput(
                views=views,
                schema_name=schema_name,
                count=len(views),
            )
        except Exception as exc:
            logger.exception("Error listing calculation views in schema %s", schema_name)
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to list calculation views: {exc}",
                tool_name="list_calculation_views",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)

    async def get_table_store_type(
        self,
        schema_name: str,
        table_name: str,
    ) -> GetTableStoreTypeOutput | ToolError:
        """Get the store type (COLUMN or ROW) for a table.

        Queries SYS.TABLES for IS_COLUMN_TABLE and related metadata.
        Returns store type with partitioning info, compression status,
        and implications text about the store type.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            GetTableStoreTypeOutput with store type info, or ToolError on failure.
        """
        input_received = {
            "schema_name": schema_name,
            "table_name": table_name,
        }

        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="get_table_store_type",
                input_received=input_received,
            )

        try:
            # Check if it's a view first (views don't have store type)
            view_rows = await asyncio.to_thread(
                _execute_query,
                conn,
                CHECK_VIEW_EXISTS_SQL,
                (schema_name, table_name),
            )
            if view_rows:
                return create_tool_error(
                    code=ErrorCode.PARAMETER_ERROR,
                    message=(
                        f"'{table_name}' is a view, not a table. Views do not have a store type."
                    ),
                    tool_name="get_table_store_type",
                    input_received=input_received,
                    suggestion=(
                        "Use describe_table to get view details, or specify a "
                        "table name to check its store type."
                    ),
                )

            # Query table store type
            rows = await asyncio.to_thread(
                _execute_query,
                conn,
                TABLE_STORE_TYPE_SQL,
                (schema_name, table_name),
            )

            if not rows:
                # Table not found -- suggest similar names
                all_objects = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    ALL_TABLE_NAMES_SQL,
                    (schema_name, schema_name),
                )
                all_names = [r[0] for r in all_objects]
                suggestions = suggest_similar(table_name, all_names)

                context: dict[str, Any] = {}
                if suggestions:
                    context["similar_tables"] = suggestions

                return create_tool_error(
                    code=ErrorCode.TABLE_NOT_FOUND,
                    message=(f"Table '{table_name}' not found in schema '{schema_name}'"),
                    tool_name="get_table_store_type",
                    input_received=input_received,
                    context=context if context else None,
                    suggestion=(
                        f"Did you mean: {', '.join(suggestions)}?" if suggestions else None
                    ),
                )

            row = rows[0]
            is_column_raw = row[2]
            has_partitions_raw = row[3]
            is_preload_raw = row[5]

            is_column = (
                (is_column_raw == "TRUE") if isinstance(is_column_raw, str) else bool(is_column_raw)
            )
            has_partitions = (
                (has_partitions_raw == "TRUE")
                if isinstance(has_partitions_raw, str)
                else bool(has_partitions_raw)
            )
            is_compressed = (
                (is_preload_raw == "TRUE")
                if isinstance(is_preload_raw, str)
                else bool(is_preload_raw)
            )

            store_type = "COLUMN" if is_column else "ROW"
            implications = COLUMN_STORE_IMPLICATIONS if is_column else ROW_STORE_IMPLICATIONS

            # Get partition count if partitioned
            partition_count = 0
            if has_partitions:
                part_rows = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    TABLE_PARTITION_COUNT_SQL,
                    (schema_name, table_name),
                )
                if part_rows:
                    partition_count = part_rows[0][0]

            store_info = StoreTypeInfo(
                table_name=table_name,
                schema_name=schema_name,
                store_type=store_type,
                is_column_table=is_column,
                has_partitions=has_partitions,
                partition_count=partition_count,
                is_compressed=is_compressed,
                implications=implications,
            )

            return GetTableStoreTypeOutput(store_info=store_info)
        except Exception as exc:
            logger.exception("Error getting store type for %s.%s", schema_name, table_name)
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to get table store type: {exc}",
                tool_name="get_table_store_type",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)

    async def list_procedures(
        self,
        schema_name: str,
        include_parameters: bool = False,
        name_pattern: str | None = None,
    ) -> ListProceduresOutput | ToolError:
        """List stored procedures in a schema.

        Queries SYS.PROCEDURES for procedure listing with name, type
        (SQLScript/R/L), and parameter count. Optionally includes
        parameter details from SYS.PROCEDURE_PARAMETERS.

        Args:
            schema_name: Schema to list procedures from.
            include_parameters: Include parameter details for each procedure.
            name_pattern: Optional SQL LIKE/glob pattern to filter procedure names.

        Returns:
            ListProceduresOutput with procedure information, or ToolError on failure.
        """
        input_received = {
            "schema_name": schema_name,
            "include_parameters": include_parameters,
            "name_pattern": name_pattern,
        }

        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="list_procedures",
                input_received=input_received,
            )

        try:
            # Verify schema exists
            schema_error = await self._verify_schema_exists(
                schema_name, "list_procedures", input_received, conn
            )
            if schema_error is not None:
                return schema_error

            # Query procedures
            rows = await asyncio.to_thread(
                _execute_query, conn, LIST_PROCEDURES_SQL, (schema_name,)
            )

            procedures: list[ProcedureInfo] = []
            for row in rows:
                proc_name = row[0]
                proc_schema = row[1]
                proc_type = row[2] or "SQLSCRIPT"
                is_read_only_raw = row[3]
                param_count = row[4]

                is_read_only = (
                    (is_read_only_raw == "TRUE")
                    if isinstance(is_read_only_raw, str)
                    else bool(is_read_only_raw)
                )

                # Optionally fetch parameter details
                parameters: list[ProcedureParameterInfo] = []
                if include_parameters:
                    param_rows = await asyncio.to_thread(
                        _execute_query,
                        conn,
                        PROCEDURE_PARAMETERS_SQL,
                        (schema_name, proc_name),
                    )
                    for param_row in param_rows:
                        param_direction = param_row[2] or "IN"
                        parameters.append(
                            ProcedureParameterInfo(
                                name=param_row[0],
                                data_type=param_row[1],
                                direction=param_direction,
                                position=param_row[3],
                                default_value=param_row[4],
                            )
                        )

                procedures.append(
                    ProcedureInfo(
                        name=proc_name,
                        schema_name=proc_schema,
                        type=proc_type,
                        parameter_count=param_count,
                        is_read_only=is_read_only,
                        parameters=parameters,
                    )
                )

            # Apply name pattern filtering
            if name_pattern is not None:
                glob_pattern = name_pattern.replace("%", "*").replace("_", "?")
                procedures = [p for p in procedures if fnmatch.fnmatchcase(p.name, glob_pattern)]

            return ListProceduresOutput(
                procedures=procedures,
                schema_name=schema_name,
                count=len(procedures),
            )
        except Exception as exc:
            logger.exception("Error listing procedures in schema %s", schema_name)
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to list procedures: {exc}",
                tool_name="list_procedures",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)
