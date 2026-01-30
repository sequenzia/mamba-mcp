"""Schema discovery queries for PostgreSQL.

This module contains SQL queries and service classes for discovering
database schema information including schemas, tables, columns, indexes,
and constraints.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Query: List all schemas (PRD Appendix 14.1)
LIST_SCHEMAS_SQL = """
SELECT
    n.nspname AS name,
    pg_catalog.pg_get_userbyid(n.nspowner) AS owner,
    pg_catalog.obj_description(n.oid, 'pg_namespace') AS description,
    (SELECT count(*) FROM pg_tables WHERE schemaname = n.nspname) AS table_count
FROM pg_catalog.pg_namespace n
WHERE
    CASE WHEN :include_system THEN TRUE
    ELSE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
    END
ORDER BY n.nspname;
"""

# Query: List tables in schema (PRD Appendix 14.1)
LIST_TABLES_SQL = """
SELECT
    t.tablename AS name,
    t.schemaname AS schema_name,
    'table' AS type,
    pg_catalog.obj_description(c.oid, 'pg_class') AS description,
    GREATEST(c.reltuples::bigint, 0) AS estimated_row_count,
    pg_total_relation_size(c.oid) AS size_bytes,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS size_pretty,
    EXISTS(SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary) AS has_primary_key,
    (SELECT count(*) FROM information_schema.columns col
     WHERE col.table_schema = t.schemaname AND col.table_name = t.tablename) AS column_count
FROM pg_tables t
JOIN pg_class c ON c.relname = t.tablename
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname
WHERE t.schemaname = :schema_name
  AND (:name_pattern IS NULL OR t.tablename LIKE :name_pattern)
ORDER BY t.tablename;
"""

# Query: List views in schema
LIST_VIEWS_SQL = """
SELECT
    v.viewname AS name,
    v.schemaname AS schema_name,
    'view' AS type,
    pg_catalog.obj_description(c.oid, 'pg_class') AS description,
    0::bigint AS estimated_row_count,
    NULL::bigint AS size_bytes,
    NULL AS size_pretty,
    FALSE AS has_primary_key,
    (SELECT count(*) FROM information_schema.columns col
     WHERE col.table_schema = v.schemaname AND col.table_name = v.viewname) AS column_count
FROM pg_views v
JOIN pg_class c ON c.relname = v.viewname
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = v.schemaname
WHERE v.schemaname = :schema_name
  AND (:name_pattern IS NULL OR v.viewname LIKE :name_pattern)
ORDER BY v.viewname;
"""

# Query: List tables in schema (without name pattern filter)
# Used when name_pattern is None to avoid asyncpg AmbiguousParameterError
LIST_TABLES_SQL_NO_FILTER = """
SELECT
    t.tablename AS name,
    t.schemaname AS schema_name,
    'table' AS type,
    pg_catalog.obj_description(c.oid, 'pg_class') AS description,
    GREATEST(c.reltuples::bigint, 0) AS estimated_row_count,
    pg_total_relation_size(c.oid) AS size_bytes,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS size_pretty,
    EXISTS(SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary) AS has_primary_key,
    (SELECT count(*) FROM information_schema.columns col
     WHERE col.table_schema = t.schemaname AND col.table_name = t.tablename) AS column_count
FROM pg_tables t
JOIN pg_class c ON c.relname = t.tablename
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname
WHERE t.schemaname = :schema_name
ORDER BY t.tablename;
"""

# Query: List views in schema (without name pattern filter)
# Used when name_pattern is None to avoid asyncpg AmbiguousParameterError
LIST_VIEWS_SQL_NO_FILTER = """
SELECT
    v.viewname AS name,
    v.schemaname AS schema_name,
    'view' AS type,
    pg_catalog.obj_description(c.oid, 'pg_class') AS description,
    0::bigint AS estimated_row_count,
    NULL::bigint AS size_bytes,
    NULL AS size_pretty,
    FALSE AS has_primary_key,
    (SELECT count(*) FROM information_schema.columns col
     WHERE col.table_schema = v.schemaname AND col.table_name = v.viewname) AS column_count
FROM pg_views v
JOIN pg_class c ON c.relname = v.viewname
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = v.schemaname
WHERE v.schemaname = :schema_name
ORDER BY v.viewname;
"""

# Query: Describe table columns
DESCRIBE_COLUMNS_SQL = """
SELECT
    c.column_name AS name,
    c.data_type,
    c.udt_name,
    c.is_nullable = 'YES' AS is_nullable,
    c.column_default AS default_value,
    pgd.description,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale
FROM information_schema.columns c
LEFT JOIN pg_catalog.pg_statio_all_tables st
    ON c.table_schema = st.schemaname AND c.table_name = st.relname
LEFT JOIN pg_catalog.pg_description pgd
    ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
WHERE c.table_schema = :schema_name AND c.table_name = :table_name
ORDER BY c.ordinal_position;
"""

# Query: Describe table indexes
DESCRIBE_INDEXES_SQL = """
SELECT
    i.relname AS name,
    array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS columns,
    ix.indisunique AS is_unique,
    ix.indisprimary AS is_primary,
    am.amname AS index_type,
    pg_catalog.obj_description(i.oid, 'pg_class') AS description
FROM pg_class t
JOIN pg_index ix ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_am am ON i.relam = am.oid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE n.nspname = :schema_name AND t.relname = :table_name
GROUP BY i.relname, ix.indisunique, ix.indisprimary, am.amname, i.oid
ORDER BY ix.indisprimary DESC, i.relname;
"""

# Query: Describe table constraints
DESCRIBE_CONSTRAINTS_SQL = """
SELECT
    tc.constraint_name AS name,
    tc.constraint_type AS type,
    array_agg(DISTINCT kcu.column_name ORDER BY kcu.column_name) AS columns,
    cc.check_clause AS definition,
    ccu.table_name AS referenced_table
FROM information_schema.table_constraints tc
LEFT JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
LEFT JOIN information_schema.check_constraints cc
    ON tc.constraint_name = cc.constraint_name AND tc.table_schema = cc.constraint_schema
LEFT JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name AND tc.constraint_type = 'FOREIGN KEY'
WHERE tc.table_schema = :schema_name AND tc.table_name = :table_name
GROUP BY tc.constraint_name, tc.constraint_type, cc.check_clause, ccu.table_name
ORDER BY tc.constraint_type, tc.constraint_name;
"""

# Query: Get table metadata (row count, size)
TABLE_METADATA_SQL = """
SELECT
    c.reltuples::bigint AS estimated_row_count,
    pg_total_relation_size(c.oid) AS size_bytes,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS size_pretty,
    pg_catalog.obj_description(c.oid, 'pg_class') AS description,
    CASE c.relkind
        WHEN 'r' THEN 'table'
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized view'
        ELSE 'other'
    END AS type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema_name AND c.relname = :table_name;
"""

# Query: Check if table exists
TABLE_EXISTS_SQL = """
SELECT EXISTS(
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = :schema_name AND table_name = :table_name
) AS exists;
"""

# Query: Get primary key columns
PRIMARY_KEY_COLUMNS_SQL = """
SELECT a.attname AS column_name
FROM pg_index i
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
JOIN pg_class c ON c.oid = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE i.indisprimary AND n.nspname = :schema_name AND c.relname = :table_name
ORDER BY array_position(i.indkey, a.attnum);
"""


class SchemaService:
    """Service for schema discovery operations."""

    def __init__(self, conn: AsyncConnection, statement_timeout: int) -> None:
        """Initialize schema service.

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

    async def list_schemas(self, include_system: bool = False) -> list[dict[str, Any]]:
        """List all database schemas.

        Args:
            include_system: Include system schemas (pg_*, information_schema).

        Returns:
            List of schema information dictionaries.
        """
        result = await self._execute_with_timeout(
            LIST_SCHEMAS_SQL, {"include_system": include_system}
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def list_tables(
        self,
        schema_name: str,
        include_views: bool = True,
        name_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all tables in a schema.

        Args:
            schema_name: Schema to list tables from.
            include_views: Include views in the listing.
            name_pattern: Optional LIKE pattern to filter table names.

        Returns:
            List of table information dictionaries.
        """
        # Use different queries based on whether name_pattern is provided
        # to avoid asyncpg AmbiguousParameterError when name_pattern is None
        if name_pattern is not None:
            params = {"schema_name": schema_name, "name_pattern": name_pattern}
            tables_sql = LIST_TABLES_SQL
            views_sql = LIST_VIEWS_SQL
        else:
            params = {"schema_name": schema_name}
            tables_sql = LIST_TABLES_SQL_NO_FILTER
            views_sql = LIST_VIEWS_SQL_NO_FILTER

        result = await self._execute_with_timeout(tables_sql, params)
        tables = [dict(row._mapping) for row in result.fetchall()]

        if include_views:
            result = await self._execute_with_timeout(views_sql, params)
            tables.extend([dict(row._mapping) for row in result.fetchall()])

        return sorted(tables, key=lambda x: x["name"])

    async def table_exists(self, schema_name: str, table_name: str) -> bool:
        """Check if a table exists.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            True if table exists, False otherwise.
        """
        result = await self._execute_with_timeout(
            TABLE_EXISTS_SQL, {"schema_name": schema_name, "table_name": table_name}
        )
        row = result.fetchone()
        return bool(row and row._mapping["exists"])

    async def get_table_metadata(self, schema_name: str, table_name: str) -> dict[str, Any] | None:
        """Get table metadata (row count, size, description).

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            Table metadata dictionary or None if not found.
        """
        result = await self._execute_with_timeout(
            TABLE_METADATA_SQL, {"schema_name": schema_name, "table_name": table_name}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def describe_columns(self, schema_name: str, table_name: str) -> list[dict[str, Any]]:
        """Get column information for a table.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            List of column information dictionaries.
        """
        params = {"schema_name": schema_name, "table_name": table_name}
        result = await self._execute_with_timeout(DESCRIBE_COLUMNS_SQL, params)
        return [dict(row._mapping) for row in result.fetchall()]

    async def describe_indexes(self, schema_name: str, table_name: str) -> list[dict[str, Any]]:
        """Get index information for a table.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            List of index information dictionaries.
        """
        params = {"schema_name": schema_name, "table_name": table_name}
        result = await self._execute_with_timeout(DESCRIBE_INDEXES_SQL, params)
        return [dict(row._mapping) for row in result.fetchall()]

    async def describe_constraints(self, schema_name: str, table_name: str) -> list[dict[str, Any]]:
        """Get constraint information for a table.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            List of constraint information dictionaries.
        """
        params = {"schema_name": schema_name, "table_name": table_name}
        result = await self._execute_with_timeout(DESCRIBE_CONSTRAINTS_SQL, params)
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_primary_key_columns(self, schema_name: str, table_name: str) -> list[str]:
        """Get primary key column names for a table.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.

        Returns:
            List of primary key column names.
        """
        params = {"schema_name": schema_name, "table_name": table_name}
        result = await self._execute_with_timeout(PRIMARY_KEY_COLUMNS_SQL, params)
        return [row._mapping["column_name"] for row in result.fetchall()]

    async def get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
        limit: int = 5,
        columns: list[str] | None = None,
        where_clause: str | None = None,
        randomize: bool = False,
    ) -> dict[str, Any]:
        """Get sample rows from a table.

        Args:
            schema_name: Schema containing the table.
            table_name: Name of the table.
            limit: Number of rows to retrieve.
            columns: Specific columns to include (None for all).
            where_clause: Optional WHERE clause (without 'WHERE' keyword).
            randomize: Whether to randomize row selection.

        Returns:
            Dictionary with columns, rows, and metadata.
        """
        # Build column list - quote column names to handle reserved words
        col_list = ", ".join(f'"{col}"' for col in columns) if columns else "*"

        # Build query with proper quoting
        sql = f'SELECT {col_list} FROM "{schema_name}"."{table_name}"'

        if where_clause:
            sql += f" WHERE {where_clause}"

        if randomize:
            sql += " ORDER BY RANDOM()"
        else:
            # Try to order by primary key for consistent results
            pk_cols = await self.get_primary_key_columns(schema_name, table_name)
            if pk_cols:
                pk_order = ", ".join(f'"{col}"' for col in pk_cols)
                sql += f" ORDER BY {pk_order}"

        sql += f" LIMIT {limit}"

        result = await self._execute_with_timeout(sql, {})
        rows = [dict(row._mapping) for row in result.fetchall()]

        # Get column names from result
        result_columns = list(rows[0].keys()) if rows else []

        return {
            "columns": result_columns,
            "rows": rows,
            "row_count": len(rows),
        }
