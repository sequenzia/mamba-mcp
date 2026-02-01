"""Relationship discovery service for SAP HANA (Layer 2).

Provides foreign key discovery and BFS-based join path finding
using SYS.REFERENTIAL_CONSTRAINTS system view.

Based on Spec Section 5.2.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from mamba_mcp_sap_hana.database.connection import HanaConnectionPool
from mamba_mcp_sap_hana.errors import (
    ErrorCode,
    ToolError,
    create_tool_error,
    suggest_similar,
)
from mamba_mcp_sap_hana.models.relationships import (
    FindJoinPathOutput,
    ForeignKeyInfo,
    ForeignKeysOutput,
    JoinPath,
    JoinStep,
)

logger = logging.getLogger(__name__)


# --- SQL Queries for SYS.REFERENTIAL_CONSTRAINTS ---

# Outgoing FKs: this table references other tables
OUTGOING_FK_SQL = """
SELECT
    CONSTRAINT_NAME,
    SCHEMA_NAME AS SOURCE_SCHEMA,
    TABLE_NAME AS SOURCE_TABLE,
    COLUMN_NAME AS SOURCE_COLUMN,
    REFERENCED_SCHEMA_NAME AS TARGET_SCHEMA,
    REFERENCED_TABLE_NAME AS TARGET_TABLE,
    REFERENCED_COLUMN_NAME AS TARGET_COLUMN,
    DELETE_RULE
FROM SYS.REFERENTIAL_CONSTRAINTS
WHERE SCHEMA_NAME = ?
  AND TABLE_NAME = ?
ORDER BY CONSTRAINT_NAME, POSITION
"""

# Incoming FKs: other tables reference this table
INCOMING_FK_SQL = """
SELECT
    CONSTRAINT_NAME,
    SCHEMA_NAME AS SOURCE_SCHEMA,
    TABLE_NAME AS SOURCE_TABLE,
    COLUMN_NAME AS SOURCE_COLUMN,
    REFERENCED_SCHEMA_NAME AS TARGET_SCHEMA,
    REFERENCED_TABLE_NAME AS TARGET_TABLE,
    REFERENCED_COLUMN_NAME AS TARGET_COLUMN,
    DELETE_RULE
FROM SYS.REFERENTIAL_CONSTRAINTS
WHERE REFERENCED_SCHEMA_NAME = ?
  AND REFERENCED_TABLE_NAME = ?
ORDER BY CONSTRAINT_NAME, POSITION
"""

# All FKs in relevant schemas for BFS graph building
ALL_FK_SQL = """
SELECT
    CONSTRAINT_NAME,
    SCHEMA_NAME AS SOURCE_SCHEMA,
    TABLE_NAME AS SOURCE_TABLE,
    COLUMN_NAME AS SOURCE_COLUMN,
    REFERENCED_SCHEMA_NAME AS TARGET_SCHEMA,
    REFERENCED_TABLE_NAME AS TARGET_TABLE,
    REFERENCED_COLUMN_NAME AS TARGET_COLUMN
FROM SYS.REFERENTIAL_CONSTRAINTS
WHERE SCHEMA_NAME = ?
   OR REFERENCED_SCHEMA_NAME = ?
   OR SCHEMA_NAME = ?
   OR REFERENCED_SCHEMA_NAME = ?
ORDER BY CONSTRAINT_NAME, POSITION
"""

# Verify a table exists in SYS.TABLES or SYS.VIEWS
TABLE_EXISTS_SQL = """
SELECT TABLE_NAME FROM SYS.TABLES
WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
UNION ALL
SELECT VIEW_NAME AS TABLE_NAME FROM SYS.VIEWS
WHERE SCHEMA_NAME = ? AND VIEW_NAME = ?
"""

# List all tables in a schema for fuzzy matching
TABLES_IN_SCHEMA_SQL = """
SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = ?
UNION ALL
SELECT VIEW_NAME AS TABLE_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ?
"""


def _execute_query(
    conn: Any,
    sql: str,
    params: tuple[Any, ...],
) -> list[tuple[Any, ...]]:
    """Execute a SQL query synchronously using hdbcli cursor.

    Args:
        conn: An hdbcli Connection object.
        sql: SQL query string with ? placeholders.
        params: Positional parameters for the query.

    Returns:
        List of result tuples.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()


def _group_fk_rows(
    rows: list[tuple[Any, ...]],
) -> list[ForeignKeyInfo]:
    """Group FK rows by constraint name into ForeignKeyInfo models.

    SYS.REFERENTIAL_CONSTRAINTS returns one row per column in a composite FK.
    This groups them into a single ForeignKeyInfo per constraint.

    Row format: (constraint_name, source_schema, source_table, source_column,
                  target_schema, target_table, target_column, delete_rule)

    Args:
        rows: Raw query result rows.

    Returns:
        List of ForeignKeyInfo models with columns aggregated.
    """
    constraints: dict[str, dict[str, Any]] = {}

    for row in rows:
        (
            constraint_name,
            source_schema,
            source_table,
            source_column,
            target_schema,
            target_table,
            target_column,
            delete_rule,
        ) = row

        if constraint_name not in constraints:
            constraints[constraint_name] = {
                "constraint_name": constraint_name,
                "source_schema": source_schema,
                "source_table": source_table,
                "source_columns": [],
                "target_schema": target_schema,
                "target_table": target_table,
                "target_columns": [],
                "delete_rule": delete_rule or "RESTRICT",
            }

        constraints[constraint_name]["source_columns"].append(source_column)
        constraints[constraint_name]["target_columns"].append(target_column)

    return [ForeignKeyInfo(**data) for data in constraints.values()]


def _build_fk_graph(
    rows: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    """Build edge list from FK rows for BFS traversal.

    Row format: (constraint_name, source_schema, source_table, source_column,
                  target_schema, target_table, target_column)

    Groups composite FKs by constraint name, producing one edge per constraint.

    Args:
        rows: Raw query result rows from ALL_FK_SQL.

    Returns:
        List of edge dictionaries with source/target info.
    """
    constraints: dict[str, dict[str, Any]] = {}

    for row in rows:
        (
            constraint_name,
            source_schema,
            source_table,
            source_column,
            target_schema,
            target_table,
            target_column,
        ) = row

        if constraint_name not in constraints:
            constraints[constraint_name] = {
                "constraint": constraint_name,
                "source": f"{source_schema}.{source_table}",
                "target": f"{target_schema}.{target_table}",
                "source_schema": source_schema,
                "source_table": source_table,
                "source_columns": [],
                "target_schema": target_schema,
                "target_table": target_table,
                "target_columns": [],
            }

        constraints[constraint_name]["source_columns"].append(source_column)
        constraints[constraint_name]["target_columns"].append(target_column)

    return list(constraints.values())


def _bfs_find_paths(
    edges: list[dict[str, Any]],
    start: str,
    end: str,
    max_depth: int,
) -> list[list[dict[str, Any]]]:
    """BFS to find all paths between start and end nodes up to max_depth.

    Builds a bidirectional adjacency list from FK edges and searches for
    all shortest paths. Both outgoing (following FK) and incoming (reverse FK)
    directions are traversed.

    Args:
        edges: List of FK edge dictionaries from _build_fk_graph.
        start: Starting node as "schema.table".
        end: Target node as "schema.table".
        max_depth: Maximum number of joins to traverse.

    Returns:
        List of paths, sorted by length (shortest first).
    """
    if start == end:
        return []

    # Build bidirectional adjacency list
    adj: dict[str, list[dict[str, Any]]] = {}

    for edge in edges:
        source = edge["source"]
        target = edge["target"]

        # Ensure both nodes exist in adjacency
        if source not in adj:
            adj[source] = []
        if target not in adj:
            adj[target] = []

        # Forward edge (outgoing direction)
        adj[source].append(
            {
                "from_schema": edge["source_schema"],
                "from_table": edge["source_table"],
                "from_columns": edge["source_columns"],
                "to_schema": edge["target_schema"],
                "to_table": edge["target_table"],
                "to_columns": edge["target_columns"],
                "constraint": edge["constraint"],
                "direction": "outgoing",
                "next_node": target,
            }
        )

        # Reverse edge (incoming direction)
        adj[target].append(
            {
                "from_schema": edge["target_schema"],
                "from_table": edge["target_table"],
                "from_columns": edge["target_columns"],
                "to_schema": edge["source_schema"],
                "to_table": edge["source_table"],
                "to_columns": edge["source_columns"],
                "constraint": edge["constraint"],
                "direction": "incoming",
                "next_node": source,
            }
        )

    # BFS: queue entries are (current_node, path_so_far, visited_set)
    queue: deque[tuple[str, list[dict[str, Any]], set[str]]] = deque()
    queue.append((start, [], {start}))
    found_paths: list[list[dict[str, Any]]] = []

    while queue:
        current, path, visited = queue.popleft()

        if len(path) > max_depth:
            continue

        for neighbor in adj.get(current, []):
            next_node = neighbor["next_node"]
            if next_node in visited:
                continue

            new_path = path + [neighbor]
            new_visited = visited | {next_node}

            if next_node == end:
                found_paths.append(new_path)
            elif len(new_path) < max_depth:
                queue.append((next_node, new_path, new_visited))

    # Sort by path length (shortest first)
    found_paths.sort(key=len)
    return found_paths


def _generate_sql_join(
    path: list[dict[str, Any]],
    from_schema: str,
    from_table: str,
) -> str:
    """Generate a SQL JOIN example for a given path.

    Produces a SELECT statement with JOIN clauses following the path steps.
    For composite FKs, multiple ON conditions are joined with AND.

    Args:
        path: List of edge dictionaries representing the join path.
        from_schema: Schema of the starting table.
        from_table: Name of the starting table.

    Returns:
        SQL JOIN clause string.
    """
    parts = [f'SELECT *\nFROM "{from_schema}"."{from_table}"']

    for step in path:
        join_type = "JOIN"
        to_ref = f'"{step["to_schema"]}"."{step["to_table"]}"'

        # Build ON conditions for all column pairs
        on_conditions = []
        for from_col, to_col in zip(step["from_columns"], step["to_columns"], strict=True):
            from_ref = f'"{step["from_schema"]}"."{step["from_table"]}"."{from_col}"'
            to_col_ref = f'"{step["to_schema"]}"."{step["to_table"]}"."{to_col}"'
            on_conditions.append(f"{from_ref} = {to_col_ref}")

        on_clause = " AND ".join(on_conditions)
        parts.append(f"  {join_type} {to_ref}\n    ON {on_clause}")

    return "\n".join(parts)


def _path_to_join_steps(path: list[dict[str, Any]]) -> list[JoinStep]:
    """Convert raw path edges to JoinStep models.

    For composite FKs, uses the first column pair. The full column
    mapping is captured in the SQL example.

    Args:
        path: List of edge dictionaries from BFS.

    Returns:
        List of JoinStep Pydantic models.
    """
    steps = []
    for edge in path:
        steps.append(
            JoinStep(
                from_schema=edge["from_schema"],
                from_table=edge["from_table"],
                from_column=edge["from_columns"][0],
                to_schema=edge["to_schema"],
                to_table=edge["to_table"],
                to_column=edge["to_columns"][0],
                constraint_name=edge["constraint"],
                direction=edge["direction"],
            )
        )
    return steps


class RelationshipService:
    """Service for Layer 2 relationship discovery operations.

    Provides foreign key discovery and BFS-based join path finding
    using SAP HANA's SYS.REFERENTIAL_CONSTRAINTS system view.

    All database operations are run via asyncio.to_thread to avoid
    blocking the event loop with hdbcli's synchronous calls.
    """

    def __init__(self, pool: HanaConnectionPool) -> None:
        """Initialize relationship service.

        Args:
            pool: Async connection pool for database access.
        """
        self._pool = pool

    async def _verify_table_exists(
        self,
        schema_name: str,
        table_name: str,
        tool_name: str,
        input_received: dict[str, Any],
    ) -> ToolError | None:
        """Verify a table exists, returning a ToolError if not found.

        Uses fuzzy matching to suggest similar table names when the
        requested table is not found.

        Args:
            schema_name: Schema to check.
            table_name: Table to verify.
            tool_name: Name of the calling tool (for error context).
            input_received: Original input parameters (for error context).

        Returns:
            ToolError if table not found, None if table exists.
        """
        conn = await self._pool.acquire()
        try:
            # Check if table exists
            rows = await asyncio.to_thread(
                _execute_query,
                conn,
                TABLE_EXISTS_SQL,
                (schema_name, table_name, schema_name, table_name),
            )
            if rows:
                return None

            # Table not found -- get candidates for fuzzy matching
            candidates_rows = await asyncio.to_thread(
                _execute_query,
                conn,
                TABLES_IN_SCHEMA_SQL,
                (schema_name, schema_name),
            )
            candidates = [row[0] for row in candidates_rows]
            similar = suggest_similar(table_name, candidates)

            context: dict[str, Any] = {
                "schema_name": schema_name,
                "table_name": table_name,
            }
            if similar:
                context["similar_tables"] = similar

            suggestion = f"Did you mean: {', '.join(similar)}?" if similar else None

            return create_tool_error(
                code=ErrorCode.TABLE_NOT_FOUND,
                message=f"Table '{table_name}' not found in schema '{schema_name}'",
                tool_name=tool_name,
                input_received=input_received,
                context=context,
                suggestion=suggestion,
            )
        finally:
            await self._pool.release(conn)

    async def get_foreign_keys(
        self,
        schema_name: str,
        table_name: str,
    ) -> ForeignKeysOutput | ToolError:
        """Get foreign key relationships for a table.

        Returns both outgoing (this table references others) and incoming
        (other tables reference this table) foreign keys.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            ForeignKeysOutput with outgoing and incoming FKs,
            or ToolError if the table is not found or a connection error occurs.
        """
        input_received = {"schema_name": schema_name, "table_name": table_name}

        # Verify table exists
        error = await self._verify_table_exists(
            schema_name, table_name, "get_foreign_keys", input_received
        )
        if error is not None:
            return error

        conn = await self._pool.acquire()
        try:
            # Query outgoing FKs
            outgoing_rows = await asyncio.to_thread(
                _execute_query,
                conn,
                OUTGOING_FK_SQL,
                (schema_name, table_name),
            )
            outgoing = _group_fk_rows(outgoing_rows)

            # Query incoming FKs
            incoming_rows = await asyncio.to_thread(
                _execute_query,
                conn,
                INCOMING_FK_SQL,
                (schema_name, table_name),
            )
            incoming = _group_fk_rows(incoming_rows)

            return ForeignKeysOutput(
                table_name=table_name,
                schema_name=schema_name,
                outgoing=outgoing,
                incoming=incoming,
                outgoing_count=len(outgoing),
                incoming_count=len(incoming),
            )
        except Exception as exc:
            logger.exception("Error retrieving foreign keys for %s.%s", schema_name, table_name)
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to retrieve foreign keys: {exc}",
                tool_name="get_foreign_keys",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)

    async def find_join_path(
        self,
        from_schema: str,
        from_table: str,
        to_schema: str,
        to_table: str,
        max_depth: int = 4,
    ) -> FindJoinPathOutput | ToolError:
        """Find join paths between two tables using BFS.

        Builds a foreign key graph from SYS.REFERENTIAL_CONSTRAINTS and
        uses breadth-first search to find the shortest paths between the
        specified tables. Supports cross-schema joins.

        Args:
            from_schema: Schema of the starting table.
            from_table: Name of the starting table.
            to_schema: Schema of the target table.
            to_table: Name of the target table.
            max_depth: Maximum number of joins to traverse (1-6).

        Returns:
            FindJoinPathOutput with discovered paths and SQL examples,
            or ToolError if tables are not found or a connection error occurs.
        """
        input_received = {
            "from_schema": from_schema,
            "from_table": from_table,
            "to_schema": to_schema,
            "to_table": to_table,
            "max_depth": max_depth,
        }

        # Verify both tables exist
        from_error = await self._verify_table_exists(
            from_schema, from_table, "find_join_path", input_received
        )
        if from_error is not None:
            return from_error

        to_error = await self._verify_table_exists(
            to_schema, to_table, "find_join_path", input_received
        )
        if to_error is not None:
            return to_error

        conn = await self._pool.acquire()
        try:
            # Build FK graph from all relevant schemas
            all_fk_rows = await asyncio.to_thread(
                _execute_query,
                conn,
                ALL_FK_SQL,
                (from_schema, from_schema, to_schema, to_schema),
            )

            edges = _build_fk_graph(all_fk_rows)

            start = f"{from_schema}.{from_table}"
            end = f"{to_schema}.{to_table}"

            raw_paths = _bfs_find_paths(edges, start, end, max_depth)

            # Convert raw paths to Pydantic models with SQL examples
            paths: list[JoinPath] = []
            for raw_path in raw_paths:
                steps = _path_to_join_steps(raw_path)
                sql_example = _generate_sql_join(raw_path, from_schema, from_table)
                paths.append(
                    JoinPath(
                        steps=steps,
                        length=len(steps),
                        sql_example=sql_example,
                    )
                )

            return FindJoinPathOutput(
                from_table=from_table,
                to_table=to_table,
                paths=paths,
                path_count=len(paths),
            )
        except Exception as exc:
            logger.exception(
                "Error finding join path from %s.%s to %s.%s",
                from_schema,
                from_table,
                to_schema,
                to_table,
            )
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Failed to find join path: {exc}",
                tool_name="find_join_path",
                input_received=input_received,
            )
        finally:
            await self._pool.release(conn)
