"""Query execution service with security validation for SAP HANA.

Provides secure read-only query execution with strict validation to ensure
only SELECT/WITH statements are allowed. Uses asyncio.to_thread for
non-blocking operation with hdbcli's synchronous cursor API.

Based on Spec Section 5.3 and Architecture Section 7.1.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from typing import Any

from mamba_mcp_hana.database.connection import HanaConnectionPool
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error
from mamba_mcp_hana.models.query import (
    ExecuteQueryOutput,
    ExplainPlanNode,
    ExplainQueryOutput,
    QueryResult,
)

logger = logging.getLogger(__name__)

# Maximum SQL query length (characters) - matches model constant
MAX_SQL_LENGTH = 100_000

# Blocked keywords for write operation detection
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
    # Administrative
    "CALL",
    "IMPORT",
    "EXPORT",
    "LOAD",
    "UNLOAD",
}

# Regex to strip SQL comments before keyword detection
_COMMENT_PATTERN = re.compile(
    r"--[^\n]*"  # Single-line comments
    r"|/\*.*?\*/",  # Block comments
    re.DOTALL,
)

# Regex to strip string literals before keyword detection
_STRING_PATTERN = re.compile(
    r"'(?:[^'\\]|\\.)*'"  # Single-quoted strings
)

# Regex pattern for blocked keywords (case-insensitive, word boundaries)
_BLOCKED_PATTERN = re.compile(
    r"\b(" + "|".join(BLOCKED_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _strip_comments_and_strings(sql: str) -> str:
    """Remove SQL comments and string literals for safe keyword detection.

    This prevents false positives from comments like '-- SELECT INSERT data'
    or strings like 'INSERT is a word' when scanning for blocked keywords.

    Args:
        sql: Raw SQL query string.

    Returns:
        SQL with comments and string literals replaced by spaces.
    """
    result = _COMMENT_PATTERN.sub(" ", sql)
    result = _STRING_PATTERN.sub(" ", result)
    return result


def _validate_sql_readonly(sql: str) -> ToolError | None:
    """Validate that SQL is a read-only SELECT/WITH statement.

    Strips comments and string literals before checking for blocked
    keywords to prevent bypass via SQL comments.

    Args:
        sql: SQL query to validate.

    Returns:
        ToolError if validation fails, None if valid.
    """
    # Check length
    if len(sql) > MAX_SQL_LENGTH:
        return create_tool_error(
            code=ErrorCode.INVALID_SQL,
            message=f"SQL query exceeds maximum length of {MAX_SQL_LENGTH} characters",
            tool_name="execute_query",
            context={"sql_length": len(sql), "max_length": MAX_SQL_LENGTH},
        )

    # Strip comments and string literals for safe keyword detection
    cleaned = _strip_comments_and_strings(sql)

    # Check for blocked keywords
    match = _BLOCKED_PATTERN.search(cleaned)
    if match:
        keyword = match.group(1).upper()
        return create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message=f"Query contains blocked keyword: {keyword}",
            tool_name="execute_query",
            context={"blocked_keyword": keyword},
        )

    # Validate query starts with SELECT or WITH
    normalized = cleaned.strip().upper()
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        return create_tool_error(
            code=ErrorCode.INVALID_SQL,
            message="Query must start with SELECT or WITH",
            tool_name="execute_query",
        )

    return None


def _generate_query_hash(sql: str, params: list[Any] | dict[str, Any] | None = None) -> str:
    """Generate a short hash for query identification and caching reference.

    Args:
        sql: SQL query string.
        params: Optional query parameters.

    Returns:
        8-character hex hash string.
    """
    content = sql
    if params is not None:
        content += str(params)
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def _execute_query_sync(
    conn: Any,
    sql: str,
    params: list[Any] | dict[str, Any] | None,
    max_rows: int,
    timeout_ms: int,
) -> tuple[list[str], list[dict[str, Any]], bool]:
    """Execute a query synchronously using hdbcli cursor.

    This function runs inside asyncio.to_thread to avoid blocking
    the event loop.

    Args:
        conn: hdbcli Connection object.
        sql: SQL query to execute.
        params: Bind parameters (list for positional, dict for named).
        max_rows: Maximum rows to fetch.
        timeout_ms: Statement timeout in milliseconds.

    Returns:
        Tuple of (column_names, rows_as_dicts, was_truncated).

    Raises:
        Exception: Propagated from hdbcli on query failure.
    """
    cursor = conn.cursor()
    try:
        # Set statement timeout via cursor property
        cursor.execute("SET TRANSACTION AUTOCOMMIT DDL OFF")
        # HANA statement timeout via connection property
        conn.setclientinfo("SESSIONVARIABLE:STATEMENT_TIMEOUT", str(timeout_ms))

        # Execute with parameters
        if params is None:
            cursor.execute(sql)
        elif isinstance(params, list):
            cursor.execute(sql, params)
        else:
            # Named parameters: hdbcli uses :name syntax natively
            cursor.execute(sql, params)

        # Fetch column names from cursor description
        columns: list[str] = []
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]

        # Fetch up to max_rows + 1 to detect truncation
        rows_raw = cursor.fetchmany(max_rows + 1)
        truncated = len(rows_raw) > max_rows
        if truncated:
            rows_raw = rows_raw[:max_rows]

        # Convert rows to dicts
        rows: list[dict[str, Any]] = []
        for row in rows_raw:
            rows.append(dict(zip(columns, row)))

        return columns, rows, truncated
    finally:
        cursor.close()


def _explain_query_sync(
    conn: Any,
    sql: str,
    statement_name: str,
) -> list[dict[str, Any]]:
    """Execute EXPLAIN PLAN synchronously and retrieve results.

    Uses HANA's EXPLAIN PLAN SET STATEMENT_NAME mechanism:
    1. Execute EXPLAIN PLAN SET STATEMENT_NAME = '{name}' FOR {sql}
    2. Read results from EXPLAIN_PLAN_TABLE
    3. Clean up the explain plan entry

    Args:
        conn: hdbcli Connection object.
        sql: SQL query to explain.
        statement_name: Unique statement name for the plan.

    Returns:
        List of plan node dictionaries from EXPLAIN_PLAN_TABLE.

    Raises:
        Exception: Propagated from hdbcli on failure.
    """
    cursor = conn.cursor()
    try:
        # Generate the explain plan
        explain_sql = f"EXPLAIN PLAN SET STATEMENT_NAME = '{statement_name}' FOR {sql}"
        cursor.execute(explain_sql)

        # Read plan results from EXPLAIN_PLAN_TABLE
        read_sql = (
            "SELECT OPERATOR_NAME, TABLE_NAME, SCHEMA_NAME, "
            "SUBTREE_COST, OUTPUT_SIZE, OPERATOR_DETAILS, "
            "EXECUTION_ENGINE, DATABASE_NAME, OPERATOR_ID, PARENT_OPERATOR_ID "
            "FROM EXPLAIN_PLAN_TABLE "
            "WHERE STATEMENT_NAME = ? "
            "ORDER BY OPERATOR_ID"
        )
        cursor.execute(read_sql, [statement_name])

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = []
        for row in cursor.fetchall():
            rows.append(dict(zip(columns, row)))

        return rows
    finally:
        # Always attempt cleanup
        try:
            cleanup_cursor = conn.cursor()
            cleanup_cursor.execute(
                "DELETE FROM EXPLAIN_PLAN_TABLE WHERE STATEMENT_NAME = ?",
                [statement_name],
            )
            cleanup_cursor.close()
        except Exception:
            logger.warning(
                "Failed to clean up EXPLAIN_PLAN_TABLE entry for statement: %s",
                statement_name,
            )
        cursor.close()


class QueryService:
    """Service for read-only query execution against SAP HANA.

    Validates all queries for read-only safety, executes via hdbcli
    with asyncio.to_thread for non-blocking operation, and returns
    structured Pydantic output models.

    Args:
        pool: HanaConnectionPool for acquiring database connections.
        statement_timeout: Default statement timeout in milliseconds.
    """

    def __init__(
        self,
        pool: HanaConnectionPool,
        statement_timeout: int = 30000,
    ) -> None:
        self._pool = pool
        self._statement_timeout = statement_timeout

    @property
    def statement_timeout(self) -> int:
        """Default statement timeout in milliseconds."""
        return self._statement_timeout

    async def execute_query(
        self,
        sql: str,
        params: list[Any] | dict[str, Any] | None = None,
        max_rows: int = 100,
        timeout_ms: int | None = None,
    ) -> ExecuteQueryOutput | ToolError:
        """Execute a read-only SQL query with parameters.

        Validates the query for read-only safety, executes it with optional
        parameters, and returns structured results with metadata.

        Args:
            sql: SQL SELECT/WITH query to execute.
            params: Bind parameters (list for positional ?, dict for named :param).
            max_rows: Maximum rows to return (excess triggers truncation warning).
            timeout_ms: Query timeout in milliseconds (uses default if not specified).

        Returns:
            ExecuteQueryOutput on success, or ToolError on failure.
        """
        # Validate read-only
        validation_error = _validate_sql_readonly(sql)
        if validation_error is not None:
            return validation_error

        # Generate query hash
        query_hash = _generate_query_hash(sql, params)

        # Determine effective timeout
        effective_timeout = timeout_ms or self._statement_timeout

        # Acquire connection and execute
        conn = None
        try:
            conn = await self._pool.acquire()

            start_time = time.perf_counter()
            try:
                columns, rows, truncated = await asyncio.wait_for(
                    asyncio.to_thread(
                        _execute_query_sync,
                        conn,
                        sql,
                        params,
                        max_rows,
                        effective_timeout,
                    ),
                    timeout=effective_timeout / 1000.0,
                )
            except TimeoutError:
                return create_tool_error(
                    code=ErrorCode.QUERY_TIMEOUT,
                    message=(f"Query timed out after {effective_timeout}ms"),
                    tool_name="execute_query",
                    context={"timeout_ms": effective_timeout, "query_hash": query_hash},
                )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Build warning message for truncation
            warning: str | None = None
            if truncated:
                warning = (
                    f"Result set truncated to {max_rows} rows. "
                    "Add a LIMIT clause or increase max_rows to see more."
                )

            result = QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=round(execution_time_ms, 2),
                truncated=truncated,
                warning=warning,
            )

            return ExecuteQueryOutput(
                result=result,
                query_hash=query_hash,
            )

        except ConnectionError as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Database connection error: {exc}",
                tool_name="execute_query",
                context={"query_hash": query_hash},
            )
        except Exception as exc:
            error_msg = str(exc)
            # Check if this is an hdbcli error that looks like invalid SQL
            if "invalid" in error_msg.lower() or "syntax" in error_msg.lower():
                return create_tool_error(
                    code=ErrorCode.INVALID_SQL,
                    message=f"SQL execution error: {error_msg}",
                    tool_name="execute_query",
                    context={"query_hash": query_hash},
                )
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Query execution failed: {error_msg}",
                tool_name="execute_query",
                context={"query_hash": query_hash},
            )
        finally:
            if conn is not None:
                await self._pool.release(conn)

    async def explain_query(
        self,
        sql: str,
        params: list[Any] | dict[str, Any] | None = None,
        format: str = "text",
    ) -> ExplainQueryOutput | ToolError:
        """Get the execution plan for a SQL query.

        Uses HANA's EXPLAIN PLAN SET STATEMENT_NAME mechanism to generate
        the plan, reads results from EXPLAIN_PLAN_TABLE, and cleans up.

        Args:
            sql: SQL query to explain.
            params: Bind parameters for accurate cost estimates.
            format: Output format ("text" or "json").

        Returns:
            ExplainQueryOutput on success, or ToolError on failure.
        """
        # Validate read-only
        validation_error = _validate_sql_readonly(sql)
        if validation_error is not None:
            return validation_error

        # Generate unique statement name to avoid conflicts
        statement_name = f"mamba_explain_{uuid.uuid4().hex[:12]}"

        conn = None
        try:
            conn = await self._pool.acquire()

            plan_rows = await asyncio.to_thread(
                _explain_query_sync,
                conn,
                sql,
                statement_name,
            )

            # Convert plan rows to ExplainPlanNode models
            nodes: list[ExplainPlanNode] = []
            total_cost: float | None = None

            for row in plan_rows:
                details: dict[str, Any] = {}
                if row.get("OPERATOR_DETAILS"):
                    details["operator_details"] = row["OPERATOR_DETAILS"]
                if row.get("EXECUTION_ENGINE"):
                    details["execution_engine"] = row["EXECUTION_ENGINE"]
                if row.get("DATABASE_NAME"):
                    details["database_name"] = row["DATABASE_NAME"]
                if row.get("OPERATOR_ID") is not None:
                    details["operator_id"] = row["OPERATOR_ID"]
                if row.get("PARENT_OPERATOR_ID") is not None:
                    details["parent_operator_id"] = row["PARENT_OPERATOR_ID"]

                cost = float(row["SUBTREE_COST"]) if row.get("SUBTREE_COST") is not None else None
                cardinality = (
                    float(row["OUTPUT_SIZE"]) if row.get("OUTPUT_SIZE") is not None else None
                )

                node = ExplainPlanNode(
                    operator=row.get("OPERATOR_NAME", "UNKNOWN"),
                    table_name=row.get("TABLE_NAME"),
                    schema_name=row.get("SCHEMA_NAME"),
                    cost=cost,
                    cardinality=cardinality,
                    details=details,
                )
                nodes.append(node)

                # Track maximum subtree cost as total cost
                if cost is not None:
                    if total_cost is None or cost > total_cost:
                        total_cost = cost

            return ExplainQueryOutput(
                nodes=nodes,
                total_cost=total_cost,
                plan_type="HANA EXPLAIN PLAN",
                original_query=sql,
            )

        except ConnectionError as exc:
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Database connection error: {exc}",
                tool_name="explain_query",
            )
        except Exception as exc:
            error_msg = str(exc)
            if "EXPLAIN_PLAN_TABLE" in error_msg:
                return create_tool_error(
                    code=ErrorCode.INVALID_SQL,
                    message=(
                        "EXPLAIN_PLAN_TABLE not accessible. "
                        "This table is auto-created in the user's schema."
                    ),
                    tool_name="explain_query",
                    suggestion=(
                        "Ensure the database user has access to EXPLAIN_PLAN_TABLE "
                        "in their default schema."
                    ),
                )
            if "invalid" in error_msg.lower() or "syntax" in error_msg.lower():
                return create_tool_error(
                    code=ErrorCode.INVALID_SQL,
                    message=f"SQL error in EXPLAIN PLAN: {error_msg}",
                    tool_name="explain_query",
                )
            return create_tool_error(
                code=ErrorCode.CONNECTION_ERROR,
                message=f"Explain plan failed: {error_msg}",
                tool_name="explain_query",
            )
        finally:
            if conn is not None:
                await self._pool.release(conn)
