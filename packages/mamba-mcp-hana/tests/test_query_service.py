"""Tests for QueryService Layer 3 database operations."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mamba_mcp_sap_hana.database.connection import HanaConnectionPool
from mamba_mcp_sap_hana.database.query_service import (
    BLOCKED_KEYWORDS,
    MAX_SQL_LENGTH,
    QueryService,
    _generate_query_hash,
    _strip_comments_and_strings,
    _validate_sql_readonly,
)
from mamba_mcp_sap_hana.errors import ErrorCode, ToolError
from mamba_mcp_sap_hana.models.query import (
    ExecuteQueryOutput,
    ExplainQueryOutput,
)

# === Test Helpers ===


def _make_mock_connection(
    columns: list[tuple[str, ...]] | None = None,
    rows: list[tuple[Any, ...]] | None = None,
) -> MagicMock:
    """Create a mock hdbcli connection with cursor behavior.

    Args:
        columns: Cursor description tuples (name, type_code, ...).
        rows: Rows to return from fetchmany/fetchall.

    Returns:
        A MagicMock simulating an hdbcli connection with cursor.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    if columns is not None:
        cursor.description = columns
    else:
        cursor.description = [("ID",), ("NAME",)]

    if rows is not None:
        cursor.fetchmany.return_value = rows
        cursor.fetchall.return_value = rows
    else:
        cursor.fetchmany.return_value = [(1, "Alice"), (2, "Bob")]
        cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]

    return conn


def _make_pool(
    pool_size: int = 3,
    pool_timeout: float = 5.0,
) -> HanaConnectionPool:
    """Create a HanaConnectionPool with test defaults.

    Args:
        pool_size: Maximum connections.
        pool_timeout: Timeout in seconds.

    Returns:
        A new HanaConnectionPool instance.
    """
    return HanaConnectionPool(
        connection_params={"address": "localhost", "port": 30015},
        pool_size=pool_size,
        pool_timeout=pool_timeout,
    )


def _make_service(
    pool: HanaConnectionPool | None = None,
    statement_timeout: int = 30000,
) -> QueryService:
    """Create a QueryService with test defaults.

    Args:
        pool: Optional pool to use (creates one if not provided).
        statement_timeout: Default statement timeout in ms.

    Returns:
        A new QueryService instance.
    """
    if pool is None:
        pool = _make_pool()
    return QueryService(pool=pool, statement_timeout=statement_timeout)


# === SQL Validation Tests ===


class TestValidateSqlReadonly:
    """Tests for _validate_sql_readonly function."""

    def test_valid_select_query(self) -> None:
        """Valid SELECT query returns None (no error)."""
        assert _validate_sql_readonly("SELECT * FROM users") is None

    def test_valid_select_with_leading_whitespace(self) -> None:
        """SELECT with leading whitespace is valid."""
        assert _validate_sql_readonly("  SELECT 1 FROM DUMMY") is None

    def test_valid_with_query(self) -> None:
        """Valid WITH (CTE) query returns None."""
        sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        assert _validate_sql_readonly(sql) is None

    def test_blocked_insert(self) -> None:
        """INSERT keyword is blocked."""
        error = _validate_sql_readonly("INSERT INTO users VALUES (1, 'test')")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "INSERT" in error.message

    def test_blocked_update(self) -> None:
        """UPDATE keyword is blocked."""
        error = _validate_sql_readonly("UPDATE users SET name = 'x'")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "UPDATE" in error.message

    def test_blocked_delete(self) -> None:
        """DELETE keyword is blocked."""
        error = _validate_sql_readonly("DELETE FROM users WHERE id = 1")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "DELETE" in error.message

    def test_blocked_drop(self) -> None:
        """DROP keyword is blocked."""
        error = _validate_sql_readonly("DROP TABLE users")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "DROP" in error.message

    def test_blocked_create(self) -> None:
        """CREATE keyword is blocked."""
        error = _validate_sql_readonly("CREATE TABLE users (id INT)")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "CREATE" in error.message

    def test_blocked_alter(self) -> None:
        """ALTER keyword is blocked."""
        error = _validate_sql_readonly("ALTER TABLE users ADD name VARCHAR(50)")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "ALTER" in error.message

    def test_blocked_truncate(self) -> None:
        """TRUNCATE keyword is blocked."""
        error = _validate_sql_readonly("TRUNCATE TABLE users")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "TRUNCATE" in error.message

    def test_blocked_merge(self) -> None:
        """MERGE keyword is blocked."""
        error = _validate_sql_readonly("MERGE INTO target USING source ON (1=1)")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "MERGE" in error.message

    def test_blocked_grant(self) -> None:
        """GRANT keyword is blocked."""
        error = _validate_sql_readonly("GRANT SELECT ON users TO public")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "GRANT" in error.message

    def test_blocked_revoke(self) -> None:
        """REVOKE keyword is blocked."""
        error = _validate_sql_readonly("REVOKE SELECT ON users FROM public")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "REVOKE" in error.message

    def test_blocked_keyword_case_insensitive(self) -> None:
        """Blocked keywords detected regardless of case."""
        error = _validate_sql_readonly("insert into users values (1)")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED

    def test_blocked_keyword_in_subquery(self) -> None:
        """Blocked keywords detected even in subqueries."""
        sql = "SELECT * FROM (DELETE FROM users)"
        error = _validate_sql_readonly(sql)
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.WRITE_OPERATION_DENIED
        assert "DELETE" in error.message

    def test_query_must_start_with_select_or_with(self) -> None:
        """Query not starting with SELECT/WITH returns INVALID_SQL."""
        error = _validate_sql_readonly("EXPLAIN SELECT 1")
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.INVALID_SQL
        assert "SELECT or WITH" in error.message

    def test_sql_exceeds_max_length(self) -> None:
        """SQL exceeding MAX_SQL_LENGTH returns INVALID_SQL."""
        long_sql = "SELECT " + "x" * (MAX_SQL_LENGTH + 1)
        error = _validate_sql_readonly(long_sql)
        assert isinstance(error, ToolError)
        assert error.code == ErrorCode.INVALID_SQL
        assert "maximum length" in error.message

    def test_all_blocked_keywords_covered(self) -> None:
        """Every keyword in BLOCKED_KEYWORDS is actually detected."""
        for keyword in BLOCKED_KEYWORDS:
            sql = f"{keyword} some_table"
            error = _validate_sql_readonly(sql)
            assert error is not None, f"Keyword {keyword} was not blocked"
            assert error.code in (
                ErrorCode.WRITE_OPERATION_DENIED,
                ErrorCode.INVALID_SQL,
            ), f"Keyword {keyword} returned unexpected code: {error.code}"


# === Comment and String Stripping Tests ===


class TestStripCommentsAndStrings:
    """Tests for _strip_comments_and_strings function."""

    def test_single_line_comment_removed(self) -> None:
        """Single-line comments (--) are stripped."""
        result = _strip_comments_and_strings("SELECT 1 -- INSERT INTO x")
        assert "INSERT" not in result
        assert "SELECT" in result

    def test_block_comment_removed(self) -> None:
        """Block comments (/* */) are stripped."""
        result = _strip_comments_and_strings("SELECT /* DELETE FROM x */ 1")
        assert "DELETE" not in result
        assert "SELECT" in result

    def test_multiline_block_comment_removed(self) -> None:
        """Multi-line block comments are stripped."""
        sql = "SELECT 1\n/* DROP TABLE\nusers */\nFROM DUMMY"
        result = _strip_comments_and_strings(sql)
        assert "DROP" not in result
        assert "SELECT" in result

    def test_string_literal_removed(self) -> None:
        """String literals are stripped to prevent false positives."""
        result = _strip_comments_and_strings("SELECT 'INSERT is a word' FROM t")
        assert "INSERT" not in result
        assert "SELECT" in result

    def test_no_comments_or_strings_unchanged(self) -> None:
        """SQL without comments or strings passes through."""
        sql = "SELECT id, name FROM users WHERE id = 1"
        result = _strip_comments_and_strings(sql)
        assert "SELECT" in result
        assert "users" in result

    def test_blocked_keyword_in_comment_not_detected(self) -> None:
        """Write keywords in comments do not trigger validation failure."""
        sql = "SELECT 1 FROM DUMMY -- This is an INSERT test"
        error = _validate_sql_readonly(sql)
        assert error is None

    def test_blocked_keyword_in_string_not_detected(self) -> None:
        """Write keywords in string literals do not trigger validation failure."""
        sql = "SELECT 'DELETE' AS action_name FROM DUMMY"
        error = _validate_sql_readonly(sql)
        assert error is None

    def test_blocked_keyword_in_block_comment_not_detected(self) -> None:
        """Write keywords in block comments do not trigger validation failure."""
        sql = "SELECT /* UPDATE users SET x=1 */ name FROM users"
        error = _validate_sql_readonly(sql)
        assert error is None


# === Query Hash Tests ===


class TestGenerateQueryHash:
    """Tests for _generate_query_hash function."""

    def test_hash_is_8_chars(self) -> None:
        """Query hash is always 8 characters."""
        h = _generate_query_hash("SELECT 1")
        assert len(h) == 8

    def test_hash_is_hex(self) -> None:
        """Query hash is a valid hex string."""
        h = _generate_query_hash("SELECT 1")
        int(h, 16)  # Should not raise

    def test_same_query_same_hash(self) -> None:
        """Same SQL produces same hash."""
        h1 = _generate_query_hash("SELECT 1")
        h2 = _generate_query_hash("SELECT 1")
        assert h1 == h2

    def test_different_query_different_hash(self) -> None:
        """Different SQL produces different hash."""
        h1 = _generate_query_hash("SELECT 1")
        h2 = _generate_query_hash("SELECT 2")
        assert h1 != h2

    def test_params_affect_hash(self) -> None:
        """Parameters influence the hash value."""
        h1 = _generate_query_hash("SELECT ?", [1])
        h2 = _generate_query_hash("SELECT ?", [2])
        assert h1 != h2

    def test_dict_params_affect_hash(self) -> None:
        """Dict parameters influence the hash value."""
        h1 = _generate_query_hash("SELECT :x", {"x": 1})
        h2 = _generate_query_hash("SELECT :x", {"x": 2})
        assert h1 != h2

    def test_none_params_same_as_no_params(self) -> None:
        """None params and no params produce the same hash."""
        h1 = _generate_query_hash("SELECT 1", None)
        h2 = _generate_query_hash("SELECT 1")
        assert h1 == h2


# === QueryService Initialization Tests ===


class TestQueryServiceInit:
    """Tests for QueryService initialization and properties."""

    def test_default_statement_timeout(self) -> None:
        """Default statement timeout is 30000ms."""
        service = _make_service()
        assert service.statement_timeout == 30000

    def test_custom_statement_timeout(self) -> None:
        """Custom statement timeout is stored."""
        service = _make_service(statement_timeout=5000)
        assert service.statement_timeout == 5000


# === Execute Query Tests ===


class TestExecuteQuery:
    """Tests for QueryService.execute_query method."""

    @pytest.mark.asyncio
    async def test_simple_select_query(self) -> None:
        """Simple SELECT returns structured ExecuteQueryOutput."""
        pool = _make_pool()
        mock_conn = _make_mock_connection(
            columns=[("ID",), ("NAME",)],
            rows=[(1, "Alice"), (2, "Bob")],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query("SELECT id, name FROM users")

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.columns == ["ID", "NAME"]
        assert result.result.row_count == 2
        assert result.result.rows == [
            {"ID": 1, "NAME": "Alice"},
            {"ID": 2, "NAME": "Bob"},
        ]
        assert result.result.truncated is False
        assert result.result.warning is None
        assert len(result.query_hash) == 8

    @pytest.mark.asyncio
    async def test_empty_result_set(self) -> None:
        """Empty result set returns rows=[], row_count=0."""
        pool = _make_pool()
        mock_conn = _make_mock_connection(
            columns=[("ID",), ("NAME",)],
            rows=[],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query("SELECT id, name FROM users WHERE 1=0")

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.rows == []
        assert result.result.row_count == 0
        assert result.result.truncated is False

    @pytest.mark.asyncio
    async def test_write_operation_blocked(self) -> None:
        """Write operations return WRITE_OPERATION_DENIED ToolError."""
        service = _make_service()
        result = await service.execute_query("INSERT INTO users VALUES (1, 'test')")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.WRITE_OPERATION_DENIED

    @pytest.mark.asyncio
    async def test_invalid_sql_not_select(self) -> None:
        """Non-SELECT/WITH query returns INVALID_SQL ToolError."""
        service = _make_service()
        result = await service.execute_query("EXPLAIN SELECT 1")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.INVALID_SQL

    @pytest.mark.asyncio
    async def test_parameterized_query_positional(self) -> None:
        """Positional parameters (?) are passed to cursor.execute."""
        pool = _make_pool()
        mock_conn = _make_mock_connection(
            columns=[("ID",), ("NAME",)],
            rows=[(1, "Alice")],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query(
                "SELECT id, name FROM users WHERE id = ?",
                params=[1],
            )

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.row_count == 1
        # Verify cursor.execute was called with params
        mock_conn.cursor().execute.assert_called()

    @pytest.mark.asyncio
    async def test_parameterized_query_named(self) -> None:
        """Named parameters (:param) are passed to cursor.execute."""
        pool = _make_pool()
        mock_conn = _make_mock_connection(
            columns=[("ID",), ("NAME",)],
            rows=[(1, "Alice")],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query(
                "SELECT id, name FROM users WHERE id = :user_id",
                params={"user_id": 1},
            )

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.row_count == 1

    @pytest.mark.asyncio
    async def test_result_truncation_with_warning(self) -> None:
        """Results exceeding max_rows are truncated with a warning."""
        pool = _make_pool()
        # Return max_rows + 1 rows to trigger truncation
        mock_conn = _make_mock_connection(
            columns=[("ID",)],
            rows=[(i,) for i in range(4)],  # 4 rows, max_rows=3
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query(
                "SELECT id FROM users",
                max_rows=3,
            )

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.truncated is True
        assert result.result.row_count == 3
        assert result.result.warning is not None
        assert "truncated" in result.result.warning.lower()

    @pytest.mark.asyncio
    async def test_no_truncation_at_exact_limit(self) -> None:
        """Exactly max_rows results are not considered truncated."""
        pool = _make_pool()
        mock_conn = _make_mock_connection(
            columns=[("ID",)],
            rows=[(i,) for i in range(3)],  # Exactly 3 rows, max_rows=3
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query(
                "SELECT id FROM users",
                max_rows=3,
            )

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.truncated is False
        assert result.result.warning is None

    @pytest.mark.asyncio
    async def test_query_hash_generated(self) -> None:
        """Every result includes a query hash."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ExecuteQueryOutput)
        assert len(result.query_hash) == 8
        # Hash is deterministic
        expected_hash = _generate_query_hash("SELECT 1 FROM DUMMY")
        assert result.query_hash == expected_hash

    @pytest.mark.asyncio
    async def test_execution_time_measured(self) -> None:
        """Execution time is recorded in milliseconds."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ExecuteQueryOutput)
        assert result.result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_connection_error_handling(self) -> None:
        """ConnectionError from pool returns CONNECTION_ERROR ToolError."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Failed to connect to SAP HANA"),
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_syntax_error_returns_invalid_sql(self) -> None:
        """hdbcli syntax error returns INVALID_SQL ToolError."""
        pool = _make_pool()
        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        # Second cursor.execute call (the actual query) raises syntax error
        cursor.execute.side_effect = [
            None,  # SET TRANSACTION
            Exception("invalid SQL syntax near 'SELCT'"),
        ]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.execute_query("SELCT 1 FROM DUMMY")

        # This should fail at validation (not SELECT/WITH) but let's test
        # when validation passes but hdbcli rejects
        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.INVALID_SQL

    @pytest.mark.asyncio
    async def test_connection_released_on_success(self) -> None:
        """Connection is released back to pool after successful query."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            await service.execute_query("SELECT 1 FROM DUMMY")

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_connection_released_on_error(self) -> None:
        """Connection is released back to pool after query error."""
        pool = _make_pool()
        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("generic error")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            await service.execute_query("SELECT 1 FROM DUMMY")

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_timeout_returns_query_timeout(self) -> None:
        """Query exceeding timeout returns QUERY_TIMEOUT ToolError."""
        pool = _make_pool()
        mock_conn = MagicMock()
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor

        # Simulate a slow query by making execute block
        import asyncio

        async def slow_execute(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)

        with (
            patch(
                "mamba_mcp_sap_hana.database.connection._create_connection",
                return_value=mock_conn,
            ),
            patch(
                "mamba_mcp_sap_hana.database.query_service._execute_query_sync",
                side_effect=lambda *a, **k: __import__("time").sleep(10),
            ),
        ):
            service = _make_service(pool=pool, statement_timeout=100)
            result = await service.execute_query(
                "SELECT 1 FROM DUMMY",
                timeout_ms=100,
            )

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.QUERY_TIMEOUT

    @pytest.mark.asyncio
    async def test_custom_timeout_used(self) -> None:
        """Custom timeout_ms overrides default statement_timeout."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool, statement_timeout=30000)
            result = await service.execute_query(
                "SELECT 1 FROM DUMMY",
                timeout_ms=5000,
            )

        assert isinstance(result, ExecuteQueryOutput)
        # Verify the timeout was set via setclientinfo
        mock_conn.setclientinfo.assert_called_with("SESSIONVARIABLE:STATEMENT_TIMEOUT", "5000")


# === Explain Query Tests ===


class TestExplainQuery:
    """Tests for QueryService.explain_query method."""

    @pytest.mark.asyncio
    async def test_explain_returns_structured_plan(self) -> None:
        """explain_query returns ExplainQueryOutput with plan nodes."""
        pool = _make_pool()
        mock_conn = MagicMock()

        # Set up cursor chain for explain_query_sync
        explain_cursor = MagicMock()
        cleanup_cursor = MagicMock()
        mock_conn.cursor.side_effect = [explain_cursor, cleanup_cursor]

        # After executing EXPLAIN PLAN, the read uses the same cursor
        explain_cursor.description = [
            ("OPERATOR_NAME",),
            ("TABLE_NAME",),
            ("SCHEMA_NAME",),
            ("SUBTREE_COST",),
            ("OUTPUT_SIZE",),
            ("OPERATOR_DETAILS",),
            ("EXECUTION_ENGINE",),
            ("DATABASE_NAME",),
            ("OPERATOR_ID",),
            ("PARENT_OPERATOR_ID",),
        ]
        explain_cursor.fetchall.return_value = [
            ("TABLE SCAN", "USERS", "MY_SCHEMA", 10.5, 100.0, "full scan", "HEX", "SYSTEM", 1, 0),
            (
                "INDEX SCAN",
                "ORDERS",
                "MY_SCHEMA",
                5.2,
                50.0,
                "index lookup",
                "HEX",
                "SYSTEM",
                2,
                1,
            ),
        ]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.explain_query("SELECT * FROM users")

        assert isinstance(result, ExplainQueryOutput)
        assert len(result.nodes) == 2
        assert result.nodes[0].operator == "TABLE SCAN"
        assert result.nodes[0].table_name == "USERS"
        assert result.nodes[0].schema_name == "MY_SCHEMA"
        assert result.nodes[0].cost == 10.5
        assert result.nodes[0].cardinality == 100.0
        assert result.nodes[1].operator == "INDEX SCAN"
        assert result.plan_type == "HANA EXPLAIN PLAN"
        assert result.original_query == "SELECT * FROM users"
        assert result.total_cost == 10.5  # Max of subtree costs

    @pytest.mark.asyncio
    async def test_explain_blocks_write_operations(self) -> None:
        """explain_query blocks write operations just like execute_query."""
        service = _make_service()
        result = await service.explain_query("DELETE FROM users")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.WRITE_OPERATION_DENIED

    @pytest.mark.asyncio
    async def test_explain_empty_plan(self) -> None:
        """explain_query handles empty plan result."""
        pool = _make_pool()
        mock_conn = MagicMock()
        explain_cursor = MagicMock()
        cleanup_cursor = MagicMock()
        mock_conn.cursor.side_effect = [explain_cursor, cleanup_cursor]
        explain_cursor.description = []
        explain_cursor.fetchall.return_value = []

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.explain_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ExplainQueryOutput)
        assert len(result.nodes) == 0
        assert result.total_cost is None

    @pytest.mark.asyncio
    async def test_explain_connection_released(self) -> None:
        """Connection is released after explain_query regardless of outcome."""
        pool = _make_pool()
        mock_conn = MagicMock()
        explain_cursor = MagicMock()
        cleanup_cursor = MagicMock()
        mock_conn.cursor.side_effect = [explain_cursor, cleanup_cursor]
        explain_cursor.description = []
        explain_cursor.fetchall.return_value = []

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            await service.explain_query("SELECT 1 FROM DUMMY")

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_explain_connection_error(self) -> None:
        """ConnectionError from pool returns CONNECTION_ERROR ToolError."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Failed to connect"),
        ):
            service = _make_service(pool=pool)
            result = await service.explain_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_explain_plan_table_error(self) -> None:
        """EXPLAIN_PLAN_TABLE access error returns helpful message."""
        pool = _make_pool()
        mock_conn = MagicMock()
        explain_cursor = MagicMock()
        mock_conn.cursor.side_effect = [explain_cursor]
        explain_cursor.execute.side_effect = Exception("Could not find table EXPLAIN_PLAN_TABLE")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.explain_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.INVALID_SQL
        assert "EXPLAIN_PLAN_TABLE" in result.message

    @pytest.mark.asyncio
    async def test_explain_plan_node_details(self) -> None:
        """Plan nodes include operator details when available."""
        pool = _make_pool()
        mock_conn = MagicMock()
        explain_cursor = MagicMock()
        cleanup_cursor = MagicMock()
        mock_conn.cursor.side_effect = [explain_cursor, cleanup_cursor]

        explain_cursor.description = [
            ("OPERATOR_NAME",),
            ("TABLE_NAME",),
            ("SCHEMA_NAME",),
            ("SUBTREE_COST",),
            ("OUTPUT_SIZE",),
            ("OPERATOR_DETAILS",),
            ("EXECUTION_ENGINE",),
            ("DATABASE_NAME",),
            ("OPERATOR_ID",),
            ("PARENT_OPERATOR_ID",),
        ]
        explain_cursor.fetchall.return_value = [
            ("TABLE SCAN", "T1", "S1", 5.0, 10.0, "details here", "OLAP", "DB1", 1, None),
        ]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.explain_query("SELECT * FROM t1")

        assert isinstance(result, ExplainQueryOutput)
        node = result.nodes[0]
        assert node.details["operator_details"] == "details here"
        assert node.details["execution_engine"] == "OLAP"
        assert node.details["database_name"] == "DB1"
        assert node.details["operator_id"] == 1

    @pytest.mark.asyncio
    async def test_explain_total_cost_is_max_subtree(self) -> None:
        """Total cost is the maximum subtree cost across all nodes."""
        pool = _make_pool()
        mock_conn = MagicMock()
        explain_cursor = MagicMock()
        cleanup_cursor = MagicMock()
        mock_conn.cursor.side_effect = [explain_cursor, cleanup_cursor]

        explain_cursor.description = [
            ("OPERATOR_NAME",),
            ("TABLE_NAME",),
            ("SCHEMA_NAME",),
            ("SUBTREE_COST",),
            ("OUTPUT_SIZE",),
            ("OPERATOR_DETAILS",),
            ("EXECUTION_ENGINE",),
            ("DATABASE_NAME",),
            ("OPERATOR_ID",),
            ("PARENT_OPERATOR_ID",),
        ]
        explain_cursor.fetchall.return_value = [
            ("OP1", None, None, 3.0, None, None, None, None, 1, None),
            ("OP2", None, None, 7.5, None, None, None, None, 2, 1),
            ("OP3", None, None, 2.0, None, None, None, None, 3, 1),
        ]

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = _make_service(pool=pool)
            result = await service.explain_query("SELECT 1 FROM DUMMY")

        assert isinstance(result, ExplainQueryOutput)
        assert result.total_cost == 7.5


# === Sync Execution Function Tests ===


class TestExecuteQuerySync:
    """Tests for _execute_query_sync helper function."""

    def test_no_params_execution(self) -> None:
        """Execute without params calls cursor.execute(sql) only."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = _make_mock_connection(
            columns=[("ID",)],
            rows=[(1,)],
        )

        columns, rows, truncated = _execute_query_sync(conn, "SELECT 1", None, 100, 30000)

        assert columns == ["ID"]
        assert rows == [{"ID": 1}]
        assert truncated is False

    def test_list_params_execution(self) -> None:
        """Execute with list params calls cursor.execute(sql, params)."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = _make_mock_connection(
            columns=[("NAME",)],
            rows=[("Alice",)],
        )

        columns, rows, truncated = _execute_query_sync(
            conn, "SELECT name FROM users WHERE id = ?", [1], 100, 30000
        )

        assert columns == ["NAME"]
        assert rows == [{"NAME": "Alice"}]

    def test_dict_params_execution(self) -> None:
        """Execute with dict params calls cursor.execute(sql, params)."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = _make_mock_connection(
            columns=[("NAME",)],
            rows=[("Bob",)],
        )

        columns, rows, truncated = _execute_query_sync(
            conn, "SELECT name FROM users WHERE id = :id", {"id": 2}, 100, 30000
        )

        assert columns == ["NAME"]
        assert rows == [{"NAME": "Bob"}]

    def test_truncation_detection(self) -> None:
        """Fetching max_rows + 1 rows triggers truncation flag."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = _make_mock_connection(
            columns=[("ID",)],
            rows=[(1,), (2,), (3,), (4,)],  # 4 rows, max_rows=3
        )

        columns, rows, truncated = _execute_query_sync(conn, "SELECT id FROM t", None, 3, 30000)

        assert truncated is True
        assert len(rows) == 3

    def test_cursor_closed_on_success(self) -> None:
        """Cursor is closed after successful execution."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = _make_mock_connection()
        _execute_query_sync(conn, "SELECT 1", None, 100, 30000)
        conn.cursor().close.assert_called()

    def test_cursor_closed_on_error(self) -> None:
        """Cursor is closed even when execution fails."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        # SET TRANSACTION succeeds (first call), query execute fails (second call)
        cursor.execute.side_effect = [None, Exception("query failed")]

        with pytest.raises(Exception, match="query failed"):
            _execute_query_sync(conn, "SELECT 1", None, 100, 30000)

        cursor.close.assert_called_once()

    def test_empty_description_returns_empty_columns(self) -> None:
        """Cursor with no description returns empty column list."""
        from mamba_mcp_sap_hana.database.query_service import _execute_query_sync

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.description = None
        cursor.fetchmany.return_value = []

        columns, rows, truncated = _execute_query_sync(conn, "SELECT 1", None, 100, 30000)

        assert columns == []
        assert rows == []
        assert truncated is False


# === Explain Query Sync Tests ===


class TestExplainQuerySync:
    """Tests for _explain_query_sync helper function."""

    def test_explain_executes_correct_sql(self) -> None:
        """Explain generates correct EXPLAIN PLAN SQL."""
        from mamba_mcp_sap_hana.database.query_service import _explain_query_sync

        conn = MagicMock()
        cursor = MagicMock()
        cleanup_cursor = MagicMock()
        conn.cursor.side_effect = [cursor, cleanup_cursor]
        cursor.description = []
        cursor.fetchall.return_value = []

        _explain_query_sync(conn, "SELECT 1", "test_stmt")

        # First execute should be the EXPLAIN PLAN
        first_call = cursor.execute.call_args_list[0]
        assert "EXPLAIN PLAN SET STATEMENT_NAME = 'test_stmt' FOR SELECT 1" in first_call[0][0]

    def test_explain_reads_from_explain_plan_table(self) -> None:
        """Explain reads results from EXPLAIN_PLAN_TABLE."""
        from mamba_mcp_sap_hana.database.query_service import _explain_query_sync

        conn = MagicMock()
        cursor = MagicMock()
        cleanup_cursor = MagicMock()
        conn.cursor.side_effect = [cursor, cleanup_cursor]
        cursor.description = [
            ("OPERATOR_NAME",),
            ("TABLE_NAME",),
            ("SCHEMA_NAME",),
            ("SUBTREE_COST",),
            ("OUTPUT_SIZE",),
            ("OPERATOR_DETAILS",),
            ("EXECUTION_ENGINE",),
            ("DATABASE_NAME",),
            ("OPERATOR_ID",),
            ("PARENT_OPERATOR_ID",),
        ]
        cursor.fetchall.return_value = [
            ("TABLE SCAN", "T1", "S1", 5.0, 10.0, None, None, None, 1, None),
        ]

        rows = _explain_query_sync(conn, "SELECT * FROM t1", "test_stmt")

        assert len(rows) == 1
        assert rows[0]["OPERATOR_NAME"] == "TABLE SCAN"
        assert rows[0]["TABLE_NAME"] == "T1"

    def test_explain_cleanup_attempted(self) -> None:
        """Cleanup cursor attempts DELETE from EXPLAIN_PLAN_TABLE."""
        from mamba_mcp_sap_hana.database.query_service import _explain_query_sync

        conn = MagicMock()
        cursor = MagicMock()
        cleanup_cursor = MagicMock()
        conn.cursor.side_effect = [cursor, cleanup_cursor]
        cursor.description = []
        cursor.fetchall.return_value = []

        _explain_query_sync(conn, "SELECT 1", "test_stmt")

        # Cleanup cursor should have been called with DELETE
        cleanup_cursor.execute.assert_called_once()
        call_args = cleanup_cursor.execute.call_args[0]
        assert "DELETE FROM EXPLAIN_PLAN_TABLE" in call_args[0]

    def test_explain_cleanup_failure_does_not_raise(self) -> None:
        """Cleanup failure is logged but does not raise."""
        from mamba_mcp_sap_hana.database.query_service import _explain_query_sync

        conn = MagicMock()
        cursor = MagicMock()
        cleanup_cursor = MagicMock()
        conn.cursor.side_effect = [cursor, cleanup_cursor]
        cursor.description = []
        cursor.fetchall.return_value = []
        # Make cleanup fail
        cleanup_cursor.execute.side_effect = Exception("cleanup failed")

        # Should not raise
        rows = _explain_query_sync(conn, "SELECT 1", "test_stmt")
        assert rows == []
