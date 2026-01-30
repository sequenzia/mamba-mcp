"""Query execution service with security validation.

This module provides secure query execution with strict validation
to ensure only read-only operations are allowed.
"""

import hashlib
import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Blocked keywords (PRD Section 8.1)
BLOCKED_KEYWORDS = {
    # Data Modification
    "INSERT",
    "UPDATE",
    "DELETE",
    "UPSERT",
    "MERGE",
    # Schema Modification
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "RENAME",
    # Permissions
    "GRANT",
    "REVOKE",
    # Session
    "SET",
    "RESET",
    "DISCARD",
    # Administrative
    "VACUUM",
    "ANALYZE",
    "CLUSTER",
    "REINDEX",
    "COPY",
    # Transaction
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
}

# Regex pattern for blocked keywords (case-insensitive, word boundaries)
BLOCKED_PATTERN = re.compile(r"\b(" + "|".join(BLOCKED_KEYWORDS) + r")\b", re.IGNORECASE)


class QueryValidationError(Exception):
    """Raised when query validation fails."""

    def __init__(self, code: str, message: str, suggestion: str | None = None) -> None:
        """Initialize validation error.

        Args:
            code: Machine-readable error code.
            message: Human-readable error message.
            suggestion: Actionable suggestion to resolve the error.
        """
        self.code = code
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)


class QueryService:
    """Service for query execution with security validation."""

    def __init__(self, conn: AsyncConnection, statement_timeout: int) -> None:
        """Initialize query service.

        Args:
            conn: Async database connection.
            statement_timeout: Statement timeout in milliseconds.
        """
        self.conn = conn
        self.statement_timeout = statement_timeout

    def validate_query(self, sql: str) -> None:
        """Validate that query is read-only (PRD Section 8.1).

        Args:
            sql: SQL query to validate.

        Raises:
            QueryValidationError: If query contains blocked keywords or
                doesn't start with SELECT/WITH.
        """
        # Check for blocked keywords
        match = BLOCKED_PATTERN.search(sql)
        if match:
            keyword = match.group(1).upper()
            raise QueryValidationError(
                code="WRITE_OPERATION_DENIED",
                message=f"Query contains blocked keyword: {keyword}",
                suggestion="This server only supports read operations (SELECT queries).",
            )

        # Normalize and check query starts with SELECT or WITH
        normalized = sql.strip().upper()
        if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
            raise QueryValidationError(
                code="INVALID_SQL",
                message="Query must start with SELECT or WITH",
                suggestion="Only SELECT and WITH...SELECT queries are allowed.",
            )

    def _hash_query(self, sql: str) -> str:
        """Generate short hash for query reference.

        Args:
            sql: SQL query to hash.

        Returns:
            8-character hash string.
        """
        return hashlib.sha256(sql.encode()).hexdigest()[:8]

    def _convert_params(self, sql: str, params: list[Any] | None) -> tuple[str, dict[str, Any]]:
        """Convert positional params ($1, $2) to named params (:param_1, :param_2).

        Args:
            sql: SQL query with $N placeholders.
            params: List of parameter values.

        Returns:
            Tuple of (converted SQL, parameter dictionary).
        """
        param_dict: dict[str, Any] = {}
        if params:
            for i, val in enumerate(params, 1):
                param_dict[f"param_{i}"] = val
            # Replace $N with :param_N (in reverse order to handle $10+ correctly)
            for i in range(len(params), 0, -1):
                sql = sql.replace(f"${i}", f":param_{i}")
        return sql, param_dict

    async def execute_query(
        self,
        sql: str,
        params: list[Any] | None = None,
        limit: int = 1000,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Execute read-only query with parameters.

        Args:
            sql: SQL SELECT query.
            params: Parameter values matching $1, $2, etc.
            limit: Maximum rows to return.
            timeout_ms: Query timeout in milliseconds.

        Returns:
            Dictionary with columns, rows, and metadata.

        Raises:
            QueryValidationError: If query validation fails.
        """
        # Validate query
        self.validate_query(sql)

        # Apply limit if not present
        upper_sql = sql.upper()
        if "LIMIT" not in upper_sql:
            sql = f"{sql} LIMIT {limit}"

        # Set timeout
        effective_timeout = timeout_ms or self.statement_timeout
        await self.conn.execute(text(f"SET LOCAL statement_timeout = {effective_timeout}"))

        # Convert parameters
        sql, param_dict = self._convert_params(sql, params)

        # Execute
        start_time = time.perf_counter()
        result = await self.conn.execute(text(sql), param_dict)
        execution_time = (time.perf_counter() - start_time) * 1000

        rows = [dict(row._mapping) for row in result.fetchall()]

        # Get column info
        columns: list[dict[str, str]] = []
        if rows:
            for key in rows[0]:
                columns.append({"name": str(key), "data_type": "unknown"})

        # Determine if results were truncated
        has_more = len(rows) == limit

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "has_more": has_more,
            "execution_time_ms": round(execution_time, 2),
            "query_hash": self._hash_query(sql),
        }

    async def explain_query(
        self,
        sql: str,
        params: list[Any] | None = None,
        analyze: bool = False,
        format: str = "text",
        verbose: bool = False,
        buffers: bool = False,
    ) -> dict[str, Any]:
        """Get query execution plan.

        Args:
            sql: SQL query to explain.
            params: Parameter values for accurate estimates.
            analyze: Actually execute query for real timings.
            format: Output format (text, json, yaml).
            verbose: Include additional detail.
            buffers: Include buffer statistics (requires analyze=True).

        Returns:
            Dictionary with plan and metadata.

        Raises:
            QueryValidationError: If query validation fails.
        """
        # Validate query
        self.validate_query(sql)

        # Build EXPLAIN options
        options = [f"FORMAT {format.upper()}"]
        if analyze:
            options.append("ANALYZE")
        if verbose:
            options.append("VERBOSE")
        if buffers and analyze:
            options.append("BUFFERS")

        explain_sql = f"EXPLAIN ({', '.join(options)}) {sql}"

        # Convert params
        explain_sql, param_dict = self._convert_params(explain_sql, params)

        # Set timeout
        await self.conn.execute(text(f"SET LOCAL statement_timeout = {self.statement_timeout}"))

        result = await self.conn.execute(text(explain_sql), param_dict)

        if format == "json":
            row = result.fetchone()
            plan = row[0] if row else None
        else:
            plan = "\n".join(row[0] for row in result.fetchall())

        return {
            "plan": plan,
            "format": format,
            "estimated_cost": None,  # Could parse from plan
            "estimated_rows": None,
            "actual_time_ms": None if not analyze else None,  # Could parse
            "warnings": None,
        }
