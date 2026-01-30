"""Foreign key and relationship discovery for PostgreSQL.

This module contains SQL queries and service classes for discovering
database relationships including foreign keys and join paths.
"""

from collections import deque
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Foreign keys query - outgoing (PRD Appendix 14.1)
OUTGOING_FK_SQL = """
SELECT
    tc.constraint_name,
    tc.table_schema AS from_schema,
    tc.table_name AS from_table,
    array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS from_columns,
    ccu.table_schema AS to_schema,
    ccu.table_name AS to_table,
    array_agg(ccu.column_name ORDER BY kcu.ordinal_position) AS to_columns,
    rc.update_rule AS on_update,
    rc.delete_rule AS on_delete
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = :schema_name
  AND tc.table_name = :table_name
GROUP BY tc.constraint_name, tc.table_schema, tc.table_name,
         ccu.table_schema, ccu.table_name, rc.update_rule, rc.delete_rule;
"""

# Foreign keys query - incoming (tables that reference this table)
INCOMING_FK_SQL = """
SELECT
    tc.constraint_name,
    tc.table_schema AS from_schema,
    tc.table_name AS from_table,
    array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS from_columns,
    ccu.table_schema AS to_schema,
    ccu.table_name AS to_table,
    array_agg(ccu.column_name ORDER BY kcu.ordinal_position) AS to_columns,
    rc.update_rule AS on_update,
    rc.delete_rule AS on_delete
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND ccu.table_schema = :schema_name
  AND ccu.table_name = :table_name
GROUP BY tc.constraint_name, tc.table_schema, tc.table_name,
         ccu.table_schema, ccu.table_name, rc.update_rule, rc.delete_rule;
"""

# All foreign keys in schema(s) for join path finding
ALL_FK_SQL = """
SELECT
    tc.constraint_name,
    tc.table_schema AS from_schema,
    tc.table_name AS from_table,
    kcu.column_name AS from_column,
    ccu.table_schema AS to_schema,
    ccu.table_name AS to_table,
    ccu.column_name AS to_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND (tc.table_schema = :from_schema OR ccu.table_schema = :from_schema
       OR tc.table_schema = :to_schema OR ccu.table_schema = :to_schema);
"""


class RelationshipService:
    """Service for relationship discovery operations."""

    def __init__(self, conn: AsyncConnection, statement_timeout: int) -> None:
        """Initialize relationship service.

        Args:
            conn: Async database connection.
            statement_timeout: Statement timeout in milliseconds.
        """
        self.conn = conn
        self.statement_timeout = statement_timeout

    async def _execute_with_timeout(self, sql: str, params: dict[str, Any]) -> Any:
        """Execute query with statement timeout.

        Args:
            sql: SQL query string.
            params: Query parameters.

        Returns:
            Query result.
        """
        await self.conn.execute(text(f"SET LOCAL statement_timeout = {self.statement_timeout}"))
        result = await self.conn.execute(text(sql), params)
        return result

    async def get_outgoing_fks(self, schema_name: str, table_name: str) -> list[dict[str, Any]]:
        """Get foreign keys from this table to other tables.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            List of outgoing foreign key relationships.
        """
        params = {"schema_name": schema_name, "table_name": table_name}
        result = await self._execute_with_timeout(OUTGOING_FK_SQL, params)
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_incoming_fks(self, schema_name: str, table_name: str) -> list[dict[str, Any]]:
        """Get foreign keys from other tables to this table.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            List of incoming foreign key relationships.
        """
        params = {"schema_name": schema_name, "table_name": table_name}
        result = await self._execute_with_timeout(INCOMING_FK_SQL, params)
        return [dict(row._mapping) for row in result.fetchall()]

    async def find_join_path(
        self,
        from_schema: str,
        from_table: str,
        to_schema: str,
        to_table: str,
        max_depth: int = 4,
    ) -> list[list[dict[str, Any]]]:
        """Find join paths between two tables using BFS.

        Args:
            from_schema: Schema of the starting table.
            from_table: Name of the starting table.
            to_schema: Schema of the target table.
            to_table: Name of the target table.
            max_depth: Maximum number of joins to traverse.

        Returns:
            List of paths, where each path is a list of edge dictionaries.
        """
        # Build graph of all FK relationships
        params = {"from_schema": from_schema, "to_schema": to_schema}
        result = await self._execute_with_timeout(ALL_FK_SQL, params)

        # Build edge list
        edges: list[dict[str, Any]] = []
        for row in result.fetchall():
            r = dict(row._mapping)
            edges.append(
                {
                    "from": f"{r['from_schema']}.{r['from_table']}",
                    "to": f"{r['to_schema']}.{r['to_table']}",
                    "from_col": r["from_column"],
                    "to_col": r["to_column"],
                    "constraint": r["constraint_name"],
                }
            )

        # BFS to find paths
        start = f"{from_schema}.{from_table}"
        end = f"{to_schema}.{to_table}"

        if start == end:
            return []

        return self._bfs_paths(edges, start, end, max_depth)

    def _bfs_paths(
        self,
        edges: list[dict[str, Any]],
        start: str,
        end: str,
        max_depth: int,
    ) -> list[list[dict[str, Any]]]:
        """BFS to find all paths up to max_depth.

        Args:
            edges: List of edge dictionaries.
            start: Starting node (schema.table).
            end: Target node (schema.table).
            max_depth: Maximum path length.

        Returns:
            List of paths found.
        """
        # Build adjacency (bidirectional for FK traversal)
        adj: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            if e["from"] not in adj:
                adj[e["from"]] = []
            if e["to"] not in adj:
                adj[e["to"]] = []
            adj[e["from"]].append(e)
            # Reverse edge for traversal in opposite direction
            adj[e["to"]].append(
                {
                    "from": e["to"],
                    "to": e["from"],
                    "from_col": e["to_col"],
                    "to_col": e["from_col"],
                    "constraint": e["constraint"],
                    "reversed": True,
                }
            )

        queue: deque[tuple[str, list[dict[str, Any]], set[str]]] = deque()
        queue.append((start, [], {start}))
        found_paths: list[list[dict[str, Any]]] = []

        while queue:
            current, path, visited = queue.popleft()

            if len(path) > max_depth:
                continue

            if current == end and path:
                found_paths.append(path)
                continue

            for edge in adj.get(current, []):
                next_node = edge["to"]
                if next_node not in visited:
                    new_path = path + [edge]
                    new_visited = visited | {next_node}
                    if next_node == end:
                        found_paths.append(new_path)
                    elif len(new_path) < max_depth:
                        queue.append((next_node, new_path, new_visited))

        # Sort by path length (shortest first)
        found_paths.sort(key=len)
        return found_paths
