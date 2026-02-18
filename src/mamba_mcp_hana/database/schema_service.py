"""Schema discovery service for SAP HANA (Layer 1).

Provides async methods querying HANA SYS.* system views for
schema discovery operations: list_schemas, list_tables,
describe_table, and get_sample_rows.

Based on Spec Section 5.1.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Any, Literal

from mamba_mcp_hana.database.connection import HanaConnectionPool
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error, suggest_similar
from mamba_mcp_hana.models.schema import (
    ColumnInfo,
    ConstraintInfo,
    DescribeTableOutput,
    IndexInfo,
    ListSchemasOutput,
    ListTablesOutput,
    SampleRowsOutput,
    SchemaInfo,
    TableInfo,
)

logger = logging.getLogger(__name__)

# HANA system schema prefixes/names to filter by default
SYSTEM_SCHEMA_PREFIXES = ("_SYS_",)
SYSTEM_SCHEMA_NAMES = frozenset({"SYS", "SYSTEM"})

# --- SQL Queries against SAP HANA SYS.* System Views ---

LIST_SCHEMAS_SQL = """
SELECT
    SCHEMA_NAME,
    SCHEMA_OWNER,
    (SELECT COUNT(*) FROM SYS.TABLES t WHERE t.SCHEMA_NAME = s.SCHEMA_NAME) AS TABLE_COUNT
FROM SYS.SCHEMAS s
ORDER BY SCHEMA_NAME
"""

LIST_TABLES_SQL = """
SELECT
    TABLE_NAME AS NAME,
    'TABLE' AS TYPE,
    RECORD_COUNT,
    (SELECT COUNT(*) FROM SYS.TABLE_COLUMNS c
     WHERE c.SCHEMA_NAME = t.SCHEMA_NAME AND c.TABLE_NAME = t.TABLE_NAME) AS COLUMN_COUNT,
    TABLE_TYPE,
    IS_COLUMN_TABLE
FROM SYS.TABLES t
WHERE SCHEMA_NAME = ?
ORDER BY TABLE_NAME
"""

LIST_VIEWS_SQL = """
SELECT
    VIEW_NAME AS NAME,
    'VIEW' AS TYPE,
    0 AS RECORD_COUNT,
    (SELECT COUNT(*) FROM SYS.VIEW_COLUMNS c
     WHERE c.SCHEMA_NAME = v.SCHEMA_NAME AND c.VIEW_NAME = v.VIEW_NAME) AS COLUMN_COUNT
FROM SYS.VIEWS v
WHERE SCHEMA_NAME = ?
ORDER BY VIEW_NAME
"""

DESCRIBE_TABLE_COLUMNS_SQL = """
SELECT
    COLUMN_NAME,
    DATA_TYPE_NAME,
    LENGTH,
    SCALE,
    IS_NULLABLE,
    DEFAULT_VALUE,
    POSITION,
    COMMENTS
FROM SYS.TABLE_COLUMNS
WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
ORDER BY POSITION
"""

DESCRIBE_VIEW_COLUMNS_SQL = """
SELECT
    COLUMN_NAME,
    DATA_TYPE_NAME,
    LENGTH,
    SCALE,
    IS_NULLABLE,
    DEFAULT_VALUE,
    POSITION,
    COMMENTS
FROM SYS.VIEW_COLUMNS
WHERE SCHEMA_NAME = ? AND VIEW_NAME = ?
ORDER BY POSITION
"""

DESCRIBE_INDEXES_SQL = """
SELECT
    i.INDEX_NAME,
    ic.COLUMN_NAME,
    i.CONSTRAINT AS IS_UNIQUE,
    i.INDEX_TYPE
FROM SYS.INDEXES i
JOIN SYS.INDEX_COLUMNS ic
    ON i.SCHEMA_NAME = ic.SCHEMA_NAME
    AND i.TABLE_NAME = ic.TABLE_NAME
    AND i.INDEX_NAME = ic.INDEX_NAME
WHERE i.SCHEMA_NAME = ? AND i.TABLE_NAME = ?
ORDER BY i.INDEX_NAME, ic.POSITION
"""

DESCRIBE_CONSTRAINTS_SQL = """
SELECT
    CONSTRAINT_NAME,
    COLUMN_NAME,
    IS_PRIMARY_KEY,
    IS_UNIQUE_KEY
FROM SYS.CONSTRAINTS
WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
ORDER BY CONSTRAINT_NAME, POSITION
"""

CHECK_SCHEMA_EXISTS_SQL = """
SELECT SCHEMA_NAME FROM SYS.SCHEMAS WHERE SCHEMA_NAME = ?
"""

CHECK_TABLE_EXISTS_SQL = """
SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
"""

CHECK_VIEW_EXISTS_SQL = """
SELECT VIEW_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ? AND VIEW_NAME = ?
"""

ALL_SCHEMA_NAMES_SQL = """
SELECT SCHEMA_NAME FROM SYS.SCHEMAS
"""

ALL_TABLE_NAMES_SQL = """
SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = ?
UNION
SELECT VIEW_NAME AS TABLE_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ?
"""

TABLE_ROW_COUNT_SQL = """
SELECT RECORD_COUNT FROM SYS.TABLES WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
"""


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


def _execute_query_with_description(
    conn: Any,
    sql: str,
    params: tuple[Any, ...] = (),
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Execute a query and return column names plus result rows.

    Args:
        conn: An hdbcli Connection object.
        sql: SQL query to execute.
        params: Query parameters.

    Returns:
        Tuple of (column_names, rows).
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return columns, rows
    finally:
        cursor.close()


def _is_system_schema(name: str) -> bool:
    """Check if a schema name is a HANA system schema.

    Args:
        name: Schema name to check.

    Returns:
        True if it is a system schema.
    """
    if name in SYSTEM_SCHEMA_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in SYSTEM_SCHEMA_PREFIXES)


class SchemaService:
    """Async service for Layer 1 schema discovery operations.

    Wraps synchronous hdbcli calls with asyncio.to_thread for
    non-blocking execution. Acquires connections from HanaConnectionPool
    and returns structured Pydantic output models.
    """

    def __init__(self, pool: HanaConnectionPool) -> None:
        """Initialize the schema service.

        Args:
            pool: Async connection pool for acquiring hdbcli connections.
        """
        self._pool = pool

    async def list_schemas(
        self,
        include_system: bool = False,
    ) -> ListSchemasOutput | ToolError:
        """List available database schemas.

        Queries SYS.SCHEMAS system view. Filters out system schemas
        (_SYS_*, SYS, SYSTEM) by default unless include_system is True.

        Args:
            include_system: Include system schemas in the listing.

        Returns:
            ListSchemasOutput with schema information, or ToolError on failure.
        """
        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="list_schemas",
                input_received={"include_system": include_system},
            )

        try:
            rows = await asyncio.to_thread(
                _execute_query,
                conn,
                LIST_SCHEMAS_SQL,
            )

            schemas: list[SchemaInfo] = []
            for row in rows:
                schema_name = row[0]
                is_system = _is_system_schema(schema_name)

                if not include_system and is_system:
                    continue

                schemas.append(
                    SchemaInfo(
                        name=schema_name,
                        owner=row[1],
                        table_count=row[2],
                        is_system=is_system,
                    )
                )

            return ListSchemasOutput(
                schemas=schemas,
                count=len(schemas),
            )
        except Exception as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to query schemas: {exc}",
                tool_name="list_schemas",
                input_received={"include_system": include_system},
            )
        finally:
            await self._pool.release(conn)

    async def list_tables(
        self,
        schema_name: str,
        name_pattern: str | None = None,
        include_views: bool = True,
    ) -> ListTablesOutput | ToolError:
        """List tables and optionally views in a schema.

        Queries SYS.TABLES and optionally SYS.VIEWS. Supports name
        pattern filtering using SQL LIKE or glob patterns.

        Args:
            schema_name: Schema to list tables from.
            name_pattern: Optional glob/LIKE pattern to filter table names.
            include_views: Include views in the listing.

        Returns:
            ListTablesOutput with table information, or ToolError on failure.
        """
        input_received = {
            "schema_name": schema_name,
            "name_pattern": name_pattern,
            "include_views": include_views,
        }

        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="list_tables",
                input_received=input_received,
            )

        try:
            # Check if schema exists
            schema_exists = await asyncio.to_thread(
                _execute_query, conn, CHECK_SCHEMA_EXISTS_SQL, (schema_name,)
            )
            if not schema_exists:
                all_schemas = await asyncio.to_thread(_execute_query, conn, ALL_SCHEMA_NAMES_SQL)
                all_names = [r[0] for r in all_schemas]
                suggestions = suggest_similar(schema_name, all_names)
                context: dict[str, Any] = {}
                if suggestions:
                    context["similar_schemas"] = suggestions

                return create_tool_error(
                    code=ErrorCode.SCHEMA_NOT_FOUND,
                    message=f"Schema '{schema_name}' not found",
                    tool_name="list_tables",
                    input_received=input_received,
                    context=context if context else None,
                    suggestion=(
                        f"Did you mean: {', '.join(suggestions)}?" if suggestions else None
                    ),
                )

            # Query tables
            table_rows = await asyncio.to_thread(
                _execute_query, conn, LIST_TABLES_SQL, (schema_name,)
            )

            tables: list[TableInfo] = []
            for row in table_rows:
                name = row[0]
                record_count = row[2]
                column_count = row[3]
                is_column = (row[5] == "TRUE") if isinstance(row[5], str) else bool(row[5])
                store_type: Literal["COLUMN", "ROW"] = "COLUMN" if is_column else "ROW"

                tables.append(
                    TableInfo(
                        name=name,
                        type="TABLE",
                        record_count=record_count,
                        column_count=column_count,
                        store_type=store_type,
                        is_column_table=is_column,
                    )
                )

            # Query views if requested
            if include_views:
                view_rows = await asyncio.to_thread(
                    _execute_query, conn, LIST_VIEWS_SQL, (schema_name,)
                )
                for row in view_rows:
                    tables.append(
                        TableInfo(
                            name=row[0],
                            type="VIEW",
                            record_count=0,
                            column_count=row[3],
                            store_type=None,
                            is_column_table=False,
                        )
                    )

            # Apply name pattern filtering
            if name_pattern is not None:
                # Support both SQL LIKE patterns and glob patterns
                # Convert SQL LIKE to glob: % -> *, _ -> ?
                glob_pattern = name_pattern.replace("%", "*").replace("_", "?")
                tables = [t for t in tables if fnmatch.fnmatchcase(t.name, glob_pattern)]

            # Sort by name
            tables.sort(key=lambda t: t.name)

            return ListTablesOutput(
                tables=tables,
                schema_name=schema_name,
                count=len(tables),
            )
        except Exception as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to query tables: {exc}",
                tool_name="list_tables",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)

    async def describe_table(
        self,
        schema_name: str,
        table_name: str,
        include_indexes: bool = True,
        include_constraints: bool = True,
    ) -> DescribeTableOutput | ToolError:
        """Describe a table's structure including columns, indexes, and constraints.

        Queries SYS.TABLE_COLUMNS (or SYS.VIEW_COLUMNS for views),
        SYS.INDEXES + SYS.INDEX_COLUMNS, and SYS.CONSTRAINTS.
        For views, indexes and constraints are skipped.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table or view to describe.
            include_indexes: Include index information (skipped for views).
            include_constraints: Include constraint information (skipped for views).

        Returns:
            DescribeTableOutput with structure details, or ToolError on failure.
        """
        input_received = {
            "schema_name": schema_name,
            "table_name": table_name,
            "include_indexes": include_indexes,
            "include_constraints": include_constraints,
        }

        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="describe_table",
                input_received=input_received,
            )

        try:
            # Check if it's a table
            table_exists = await asyncio.to_thread(
                _execute_query,
                conn,
                CHECK_TABLE_EXISTS_SQL,
                (schema_name, table_name),
            )
            is_view = False

            if not table_exists:
                # Check if it's a view
                view_exists = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    CHECK_VIEW_EXISTS_SQL,
                    (schema_name, table_name),
                )
                if view_exists:
                    is_view = True
                else:
                    # Not found -- suggest similar names
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
                        message=(
                            f"Table or view '{table_name}' not found in schema '{schema_name}'"
                        ),
                        tool_name="describe_table",
                        input_received=input_received,
                        context=context if context else None,
                        suggestion=(
                            f"Did you mean: {', '.join(suggestions)}?" if suggestions else None
                        ),
                    )

            # Query columns
            if is_view:
                column_rows = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    DESCRIBE_VIEW_COLUMNS_SQL,
                    (schema_name, table_name),
                )
            else:
                column_rows = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    DESCRIBE_TABLE_COLUMNS_SQL,
                    (schema_name, table_name),
                )

            columns = [
                ColumnInfo(
                    name=row[0],
                    data_type=row[1],
                    length=row[2],
                    scale=row[3],
                    nullable=(row[4] == "TRUE") if isinstance(row[4], str) else bool(row[4]),
                    default_value=row[5],
                    position=row[6],
                    comment=row[7],
                )
                for row in column_rows
            ]

            # Query indexes (skip for views)
            indexes: list[IndexInfo] = []
            if include_indexes and not is_view:
                index_rows = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    DESCRIBE_INDEXES_SQL,
                    (schema_name, table_name),
                )
                # Group by index name
                index_map: dict[str, dict[str, Any]] = {}
                for row in index_rows:
                    idx_name = row[0]
                    col_name = row[1]
                    is_unique_raw = row[2]
                    idx_type = row[3]

                    if idx_name not in index_map:
                        if isinstance(is_unique_raw, str):
                            is_unique = is_unique_raw in ("UNIQUE", "PRIMARY KEY")
                        else:
                            is_unique = bool(is_unique_raw)
                        index_map[idx_name] = {
                            "name": idx_name,
                            "columns": [],
                            "is_unique": is_unique,
                            "index_type": idx_type or "BTREE",
                        }
                    index_map[idx_name]["columns"].append(col_name)

                indexes = [IndexInfo(**data) for data in index_map.values()]

            # Query constraints (skip for views)
            constraints: list[ConstraintInfo] = []
            if include_constraints and not is_view:
                constraint_rows = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    DESCRIBE_CONSTRAINTS_SQL,
                    (schema_name, table_name),
                )
                # Group by constraint name
                constraint_map: dict[str, dict[str, Any]] = {}
                for row in constraint_rows:
                    c_name = row[0]
                    col_name = row[1]
                    is_pk = row[2]
                    is_unique = row[3]

                    if c_name not in constraint_map:
                        pk_flag = (is_pk == "TRUE") if isinstance(is_pk, str) else bool(is_pk)
                        uq_flag = (
                            (is_unique == "TRUE") if isinstance(is_unique, str) else bool(is_unique)
                        )

                        if pk_flag:
                            c_type = "PRIMARY KEY"
                        elif uq_flag:
                            c_type = "UNIQUE"
                        else:
                            c_type = "CHECK"

                        constraint_map[c_name] = {
                            "name": c_name,
                            "constraint_type": c_type,
                            "columns": [],
                        }
                    constraint_map[c_name]["columns"].append(col_name)

                constraints = [ConstraintInfo(**data) for data in constraint_map.values()]

            return DescribeTableOutput(
                table_name=table_name,
                schema_name=schema_name,
                columns=columns,
                indexes=indexes,
                constraints=constraints,
                is_view=is_view,
            )
        except Exception as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to describe table: {exc}",
                tool_name="describe_table",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)

    async def get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
        limit: int = 10,
        columns: list[str] | None = None,
        where_clause: str | None = None,
        randomize: bool = False,
    ) -> SampleRowsOutput | ToolError:
        """Get sample rows from a table.

        Executes a SELECT with LIMIT against the specified table.
        Supports column selection, WHERE clause filtering, and
        random row selection.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table to sample.
            limit: Maximum number of rows to return.
            columns: Specific columns to include (None for all).
            where_clause: Optional WHERE clause (without 'WHERE' keyword).
            randomize: Randomize row selection.

        Returns:
            SampleRowsOutput with sample data, or ToolError on failure.
        """
        input_received: dict[str, Any] = {
            "schema_name": schema_name,
            "table_name": table_name,
            "limit": limit,
        }
        if columns is not None:
            input_received["columns"] = columns
        if where_clause is not None:
            input_received["where_clause"] = where_clause
        if randomize:
            input_received["randomize"] = randomize

        try:
            conn = await self._pool.acquire()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to acquire database connection: {exc}",
                tool_name="get_sample_rows",
                input_received=input_received,
            )

        try:
            # Check table/view exists
            table_exists = await asyncio.to_thread(
                _execute_query,
                conn,
                CHECK_TABLE_EXISTS_SQL,
                (schema_name, table_name),
            )
            is_view = False
            if not table_exists:
                view_exists = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    CHECK_VIEW_EXISTS_SQL,
                    (schema_name, table_name),
                )
                if view_exists:
                    is_view = True
                else:
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
                        message=(
                            f"Table or view '{table_name}' not found in schema '{schema_name}'"
                        ),
                        tool_name="get_sample_rows",
                        input_received=input_received,
                        context=context if context else None,
                        suggestion=(
                            f"Did you mean: {', '.join(suggestions)}?" if suggestions else None
                        ),
                    )

            # Build column list
            col_list = ", ".join(f'"{col}"' for col in columns) if columns else "*"

            # Build query
            sql = f'SELECT {col_list} FROM "{schema_name}"."{table_name}"'

            if where_clause:
                sql += f" WHERE {where_clause}"

            if randomize:
                sql += " ORDER BY RAND()"

            sql += f" LIMIT {limit}"

            # Execute with column names
            col_names, rows = await asyncio.to_thread(_execute_query_with_description, conn, sql)

            # Convert rows to list of dicts
            row_dicts = [dict(zip(col_names, row)) for row in rows]

            # Get total row count
            total_count = 0
            if not is_view:
                count_rows = await asyncio.to_thread(
                    _execute_query,
                    conn,
                    TABLE_ROW_COUNT_SQL,
                    (schema_name, table_name),
                )
                if count_rows:
                    total_count = count_rows[0][0]
            else:
                # For views, use a count query
                count_sql = f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
                count_rows = await asyncio.to_thread(_execute_query, conn, count_sql)
                if count_rows:
                    total_count = count_rows[0][0]

            return SampleRowsOutput(
                table_name=table_name,
                schema_name=schema_name,
                columns=col_names,
                rows=row_dicts,
                row_count=len(row_dicts),
                total_count=total_count,
            )
        except Exception as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to get sample rows: {exc}",
                tool_name="get_sample_rows",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)
