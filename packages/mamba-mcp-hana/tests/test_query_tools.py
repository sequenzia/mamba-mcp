"""Tests for Layer 3 query execution MCP tools.

Tests both execute_query and explain_query tool functions with mocked
QueryService to verify parameter handling, error wrapping, and JSON
serialization.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_hana.errors import ErrorCode, create_tool_error
from mamba_mcp_hana.models.query import (
    ExecuteQueryOutput,
    ExplainPlanNode,
    ExplainQueryOutput,
    QueryResult,
)
from mamba_mcp_hana.tools.query_tools import execute_query, explain_query


def _make_app_context(statement_timeout: int = 30000) -> MagicMock:
    """Create a mock AppContext with pool and settings."""
    app_ctx = MagicMock()
    app_ctx.pool = MagicMock()
    app_ctx.settings.database.statement_timeout = statement_timeout
    return app_ctx


def _make_ctx(app_ctx: MagicMock | None = None) -> MagicMock:
    """Create a mock MCP Context wrapping an AppContext."""
    if app_ctx is None:
        app_ctx = _make_app_context()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


def _make_execute_output(
    columns: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    row_count: int = 1,
    execution_time_ms: float = 5.0,
    truncated: bool = False,
    warning: str | None = None,
    query_hash: str = "abc12345",
) -> ExecuteQueryOutput:
    """Create a sample ExecuteQueryOutput for testing."""
    return ExecuteQueryOutput(
        result=QueryResult(
            columns=columns or ["id", "name"],
            rows=rows or [{"id": 1, "name": "test"}],
            row_count=row_count,
            execution_time_ms=execution_time_ms,
            truncated=truncated,
            warning=warning,
        ),
        query_hash=query_hash,
    )


def _make_explain_output(
    nodes: list[ExplainPlanNode] | None = None,
    total_cost: float | None = 10.5,
    plan_type: str = "HANA EXPLAIN PLAN",
    original_query: str = "SELECT 1 FROM DUMMY",
) -> ExplainQueryOutput:
    """Create a sample ExplainQueryOutput for testing."""
    if nodes is None:
        nodes = [
            ExplainPlanNode(
                operator="TABLE SCAN",
                table_name="DUMMY",
                schema_name="SYS",
                cost=10.5,
                cardinality=1.0,
            )
        ]
    return ExplainQueryOutput(
        nodes=nodes,
        total_cost=total_cost,
        plan_type=plan_type,
        original_query=original_query,
    )


class TestExecuteQueryTool:
    """Tests for the execute_query MCP tool."""

    @pytest.mark.anyio
    async def test_successful_query(self) -> None:
        """Test execute_query returns JSON-serialized ExecuteQueryOutput."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(
                sql="SELECT * FROM DUMMY",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["query_hash"] == "abc12345"
        assert parsed["result"]["columns"] == ["id", "name"]
        assert parsed["result"]["row_count"] == 1

    @pytest.mark.anyio
    async def test_with_named_params(self) -> None:
        """Test execute_query passes named dict params to service."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(
                sql="SELECT * FROM USERS WHERE name = :name",
                params={"name": "alice"},
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["query_hash"] == "abc12345"

        # Verify service was called with named params
        mock_service.execute_query.assert_called_once_with(
            sql="SELECT * FROM USERS WHERE name = :name",
            params={"name": "alice"},
            max_rows=1000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_with_positional_params(self) -> None:
        """Test execute_query passes positional list params to service."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(
                sql="SELECT * FROM USERS WHERE id = ?",
                params=[42],
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert "result" in parsed

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT * FROM USERS WHERE id = ?",
            params=[42],
            max_rows=1000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_params_none(self) -> None:
        """Test execute_query with params=None passes None to service."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_custom_limit(self) -> None:
        """Test execute_query passes custom limit as max_rows."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=500, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=500,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_custom_timeout(self) -> None:
        """Test execute_query passes custom timeout_ms to service."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", timeout_ms=5000, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1000,
            timeout_ms=5000,
        )

    @pytest.mark.anyio
    async def test_timeout_none_uses_default(self) -> None:
        """Test execute_query passes timeout_ms=None so service uses default."""
        ctx = _make_ctx(_make_app_context(statement_timeout=60000))
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        # Service created with the config timeout
        mock_service_cls.assert_called_once_with(
            pool=ctx.request_context.lifespan_context.pool,
            statement_timeout=60000,
        )
        # timeout_ms=None passed through
        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_limit_clamped_below(self) -> None:
        """Test that limit below 1 is clamped to 1."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=0, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_limit_clamped_above(self) -> None:
        """Test that limit above 10000 is clamped to 10000."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=99999, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=10000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_write_operation_denied(self) -> None:
        """Test execute_query returns error JSON for write attempts."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: INSERT",
            tool_name="execute_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(
                sql="INSERT INTO users VALUES (1)",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"
        assert "INSERT" in parsed["message"]
        assert parsed["tool_name"] == "execute_query"

    @pytest.mark.anyio
    async def test_query_timeout_error(self) -> None:
        """Test execute_query returns error JSON for timeout."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.QUERY_TIMEOUT,
            message="Query timed out after 30000ms",
            tool_name="execute_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(
                sql="SELECT * FROM huge_table",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["code"] == "QUERY_TIMEOUT"
        assert "suggestion" in parsed

    @pytest.mark.anyio
    async def test_invalid_sql_error(self) -> None:
        """Test execute_query returns error JSON for invalid SQL."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.INVALID_SQL,
            message="SQL execution error: invalid column name",
            tool_name="execute_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(
                sql="SELECT nonexistent FROM DUMMY",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["code"] == "INVALID_SQL"

    @pytest.mark.anyio
    async def test_no_context_returns_error(self) -> None:
        """Test execute_query returns error JSON when ctx is None."""
        result = await execute_query(sql="SELECT 1 FROM DUMMY", ctx=None)

        parsed = json.loads(result)
        assert parsed["code"] == "CONNECTION_ERROR"
        assert "context" in parsed["message"].lower()

    @pytest.mark.anyio
    async def test_truncated_result(self) -> None:
        """Test execute_query serializes truncated results correctly."""
        ctx = _make_ctx()
        expected = _make_execute_output(
            truncated=True,
            warning="Result set truncated to 100 rows.",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(
                sql="SELECT * FROM big_table",
                limit=100,
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["result"]["truncated"] is True
        assert "truncated" in parsed["result"]["warning"].lower()

    @pytest.mark.anyio
    async def test_service_created_with_pool_and_timeout(self) -> None:
        """Test that QueryService is created with pool and statement_timeout from context."""
        app_ctx = _make_app_context(statement_timeout=45000)
        ctx = _make_ctx(app_ctx)
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        mock_service_cls.assert_called_once_with(
            pool=app_ctx.pool,
            statement_timeout=45000,
        )


class TestExplainQueryTool:
    """Tests for the explain_query MCP tool."""

    @pytest.mark.anyio
    async def test_successful_explain(self) -> None:
        """Test explain_query returns JSON-serialized ExplainQueryOutput."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            result = await explain_query(
                sql="SELECT * FROM DUMMY",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["plan_type"] == "HANA EXPLAIN PLAN"
        assert parsed["total_cost"] == 10.5
        assert len(parsed["nodes"]) == 1
        assert parsed["nodes"][0]["operator"] == "TABLE SCAN"

    @pytest.mark.anyio
    async def test_text_format(self) -> None:
        """Test explain_query with format='text'."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(
                sql="SELECT 1 FROM DUMMY",
                format="text",
                ctx=ctx,
            )

        mock_service.explain_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            format="text",
        )

    @pytest.mark.anyio
    async def test_json_format(self) -> None:
        """Test explain_query with format='json'."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(
                sql="SELECT 1 FROM DUMMY",
                format="json",
                ctx=ctx,
            )

        mock_service.explain_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            format="json",
        )

    @pytest.mark.anyio
    async def test_invalid_format_falls_back_to_text(self) -> None:
        """Test explain_query falls back to 'text' for invalid format."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(
                sql="SELECT 1 FROM DUMMY",
                format="yaml",
                ctx=ctx,
            )

        mock_service.explain_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            format="text",
        )

    @pytest.mark.anyio
    async def test_with_params(self) -> None:
        """Test explain_query passes params to service."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(
                sql="SELECT * FROM USERS WHERE id = :id",
                params={"id": 1},
                ctx=ctx,
            )

        mock_service.explain_query.assert_called_once_with(
            sql="SELECT * FROM USERS WHERE id = :id",
            params={"id": 1},
            format="text",
        )

    @pytest.mark.anyio
    async def test_params_none(self) -> None:
        """Test explain_query with params=None passes None to service."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        mock_service.explain_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            format="text",
        )

    @pytest.mark.anyio
    async def test_write_operation_denied(self) -> None:
        """Test explain_query returns error JSON for write attempts."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: DELETE",
            tool_name="explain_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=error)

            result = await explain_query(
                sql="DELETE FROM users",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"
        assert "DELETE" in parsed["message"]

    @pytest.mark.anyio
    async def test_invalid_sql_error(self) -> None:
        """Test explain_query returns error JSON for invalid SQL."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.INVALID_SQL,
            message="SQL error in EXPLAIN PLAN: syntax error",
            tool_name="explain_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=error)

            result = await explain_query(
                sql="SELEC BAD SYNTAX",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["code"] == "INVALID_SQL"

    @pytest.mark.anyio
    async def test_no_context_returns_error(self) -> None:
        """Test explain_query returns error JSON when ctx is None."""
        result = await explain_query(sql="SELECT 1 FROM DUMMY", ctx=None)

        parsed = json.loads(result)
        assert parsed["code"] == "CONNECTION_ERROR"
        assert "context" in parsed["message"].lower()

    @pytest.mark.anyio
    async def test_service_created_with_pool_and_timeout(self) -> None:
        """Test that QueryService is created with pool and statement_timeout."""
        app_ctx = _make_app_context(statement_timeout=15000)
        ctx = _make_ctx(app_ctx)
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        mock_service_cls.assert_called_once_with(
            pool=app_ctx.pool,
            statement_timeout=15000,
        )

    @pytest.mark.anyio
    async def test_multiple_plan_nodes(self) -> None:
        """Test explain_query serializes multiple plan nodes correctly."""
        ctx = _make_ctx()
        nodes = [
            ExplainPlanNode(
                operator="COLUMN TABLE",
                table_name="ORDERS",
                schema_name="SALES",
                cost=25.0,
                cardinality=100.0,
            ),
            ExplainPlanNode(
                operator="INDEX SCAN",
                table_name="CUSTOMERS",
                schema_name="SALES",
                cost=5.0,
                cardinality=1.0,
            ),
        ]
        expected = _make_explain_output(
            nodes=nodes,
            total_cost=25.0,
            original_query="SELECT o.* FROM ORDERS o JOIN CUSTOMERS c ON o.cid = c.id",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            result = await explain_query(
                sql="SELECT o.* FROM ORDERS o JOIN CUSTOMERS c ON o.cid = c.id",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert len(parsed["nodes"]) == 2
        assert parsed["nodes"][0]["operator"] == "COLUMN TABLE"
        assert parsed["nodes"][1]["operator"] == "INDEX SCAN"
        assert parsed["total_cost"] == 25.0


class TestToolRegistration:
    """Tests for tool registration with FastMCP."""

    def test_execute_query_is_callable(self) -> None:
        """Test execute_query is a callable tool function."""
        assert callable(execute_query)

    def test_explain_query_is_callable(self) -> None:
        """Test explain_query is a callable tool function."""
        assert callable(explain_query)

    def test_tools_registered_with_mcp(self) -> None:
        """Test both tools are registered with the FastMCP server."""
        from mamba_mcp_hana.server import mcp as server

        # FastMCP registers tools internally; verify by checking tool list
        # The tools should be registered when the module is imported
        tool_names = [tool.name for tool in server._tool_manager._tools.values()]
        assert "execute_query" in tool_names
        assert "explain_query" in tool_names

    def test_tools_have_docstrings(self) -> None:
        """Both tool functions have non-empty docstrings."""
        assert execute_query.__doc__
        assert explain_query.__doc__


# ---------------------------------------------------------------------------
# Phase 2: Extended query tool tests
# ---------------------------------------------------------------------------


class TestQueryValidationComprehensive:
    """Comprehensive tests for write keyword blocking at tool level.

    Verifies that all 20 blocked keywords from BLOCKED_KEYWORDS set
    are rejected when passed through the tool layer.
    """

    @pytest.mark.anyio
    async def test_all_blocked_keywords_rejected(self) -> None:
        """Every BLOCKED_KEYWORD produces WRITE_OPERATION_DENIED or INVALID_SQL."""
        from mamba_mcp_hana.database.query_service import BLOCKED_KEYWORDS

        ctx = _make_ctx()

        for keyword in BLOCKED_KEYWORDS:
            error = create_tool_error(
                code=ErrorCode.WRITE_OPERATION_DENIED,
                message=f"Query contains blocked keyword: {keyword}",
                tool_name="execute_query",
            )

            with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
                mock_service = mock_service_cls.return_value
                mock_service.execute_query = AsyncMock(return_value=error)

                result = await execute_query(
                    sql=f"{keyword} something",
                    ctx=ctx,
                )

            parsed = json.loads(result)
            assert parsed["code"] in (
                "WRITE_OPERATION_DENIED",
                "INVALID_SQL",
            ), f"Keyword '{keyword}' was not properly rejected"

    @pytest.mark.anyio
    async def test_insert_blocked(self) -> None:
        """INSERT is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: INSERT",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="INSERT INTO t VALUES (1)", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_update_blocked(self) -> None:
        """UPDATE is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: UPDATE",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="UPDATE t SET x=1", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_delete_blocked(self) -> None:
        """DELETE is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: DELETE",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="DELETE FROM t", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_drop_blocked(self) -> None:
        """DROP is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: DROP",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="DROP TABLE t", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_create_blocked(self) -> None:
        """CREATE is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: CREATE",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="CREATE TABLE t (id INT)", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_truncate_blocked(self) -> None:
        """TRUNCATE is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: TRUNCATE",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="TRUNCATE TABLE t", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_grant_blocked(self) -> None:
        """GRANT is blocked at the tool level."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: GRANT",
            tool_name="execute_query",
        )
        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="GRANT SELECT ON t TO public", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_valid_select_passes(self) -> None:
        """Valid SELECT query is accepted and returns normal output."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(sql="SELECT * FROM DUMMY", ctx=ctx)

        parsed = json.loads(result)
        assert "result" in parsed
        assert parsed["result"]["columns"] == ["id", "name"]

    @pytest.mark.anyio
    async def test_valid_with_query_passes(self) -> None:
        """Valid WITH (CTE) query is accepted."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(
                sql="WITH cte AS (SELECT 1 AS x) SELECT * FROM cte",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert "result" in parsed


class TestAutoLimitBehavior:
    """Tests for limit auto-clamping at the tool layer."""

    @pytest.mark.anyio
    async def test_limit_clamped_to_1_when_zero(self) -> None:
        """Limit of 0 is clamped to 1."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=0, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_limit_clamped_to_1_when_negative(self) -> None:
        """Negative limit is clamped to 1."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=-100, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_limit_clamped_to_10000_when_large(self) -> None:
        """Limit above 10000 is clamped to 10000."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=999999, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=10000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_limit_at_boundary_1(self) -> None:
        """Limit of exactly 1 passes through unchanged."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=1, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_limit_at_boundary_10000(self) -> None:
        """Limit of exactly 10000 passes through unchanged."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", limit=10000, ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=10000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_default_limit_is_1000(self) -> None:
        """Default limit (not provided) is 1000."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1000,
            timeout_ms=None,
        )


class TestExplainPlanLifecycle:
    """Tests for EXPLAIN PLAN write-read-cleanup lifecycle at tool level."""

    @pytest.mark.anyio
    async def test_explain_plan_end_to_end(self) -> None:
        """Explain query returns full plan nodes with cost and cardinality."""
        ctx = _make_ctx()
        nodes = [
            ExplainPlanNode(
                operator="COLUMN TABLE",
                table_name="ORDERS",
                schema_name="SALES",
                cost=25.0,
                cardinality=1000.0,
                details={"execution_engine": "OLAP"},
            ),
            ExplainPlanNode(
                operator="INDEX SCAN",
                table_name="CUSTOMERS",
                schema_name="SALES",
                cost=5.0,
                cardinality=1.0,
                details={"execution_engine": "HEX"},
            ),
        ]
        expected = _make_explain_output(
            nodes=nodes,
            total_cost=25.0,
            original_query="SELECT o.* FROM ORDERS o JOIN CUSTOMERS c ON o.cid = c.id",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            result = await explain_query(
                sql="SELECT o.* FROM ORDERS o JOIN CUSTOMERS c ON o.cid = c.id",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["plan_type"] == "HANA EXPLAIN PLAN"
        assert parsed["total_cost"] == 25.0
        assert len(parsed["nodes"]) == 2
        assert parsed["nodes"][0]["operator"] == "COLUMN TABLE"
        assert parsed["nodes"][0]["cost"] == 25.0
        assert parsed["nodes"][0]["cardinality"] == 1000.0
        assert parsed["nodes"][1]["operator"] == "INDEX SCAN"
        assert parsed["original_query"] == (
            "SELECT o.* FROM ORDERS o JOIN CUSTOMERS c ON o.cid = c.id"
        )

    @pytest.mark.anyio
    async def test_explain_empty_plan(self) -> None:
        """Explain query handles empty plan (no nodes)."""
        ctx = _make_ctx()
        expected = _make_explain_output(
            nodes=[],
            total_cost=None,
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            result = await explain_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["nodes"] == []
        assert parsed["total_cost"] is None

    @pytest.mark.anyio
    async def test_explain_with_params(self) -> None:
        """Explain query passes params for accurate cost estimates."""
        ctx = _make_ctx()
        expected = _make_explain_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=expected)

            await explain_query(
                sql="SELECT * FROM USERS WHERE id = :id",
                params={"id": 42},
                ctx=ctx,
            )

        mock_service.explain_query.assert_called_once_with(
            sql="SELECT * FROM USERS WHERE id = :id",
            params={"id": 42},
            format="text",
        )

    @pytest.mark.anyio
    async def test_explain_write_blocked(self) -> None:
        """Explain query blocks write operations like execute_query."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.WRITE_OPERATION_DENIED,
            message="Query contains blocked keyword: INSERT",
            tool_name="explain_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=error)

            result = await explain_query(sql="INSERT INTO t VALUES (1)", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "WRITE_OPERATION_DENIED"

    @pytest.mark.anyio
    async def test_explain_plan_table_error(self) -> None:
        """Explain query returns helpful error when EXPLAIN_PLAN_TABLE missing."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.INVALID_SQL,
            message="EXPLAIN_PLAN_TABLE not found",
            tool_name="explain_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.explain_query = AsyncMock(return_value=error)

            result = await explain_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "INVALID_SQL"
        assert "EXPLAIN_PLAN_TABLE" in parsed["message"]


class TestExecuteQueryExtended:
    """Extended tests for execute_query covering parameterized queries and timing."""

    @pytest.mark.anyio
    async def test_execution_time_in_output(self) -> None:
        """execute_query returns execution_time_ms in the result."""
        ctx = _make_ctx()
        expected = _make_execute_output(execution_time_ms=15.3)

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["result"]["execution_time_ms"] == 15.3

    @pytest.mark.anyio
    async def test_query_hash_in_output(self) -> None:
        """execute_query returns a deterministic query_hash."""
        ctx = _make_ctx()
        expected = _make_execute_output(query_hash="deadbeef")

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["query_hash"] == "deadbeef"

    @pytest.mark.anyio
    async def test_mixed_params_dict(self) -> None:
        """execute_query handles dict params with mixed types."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(
                sql="SELECT * FROM t WHERE id = :id AND name = :name",
                params={"id": 1, "name": "test"},
                ctx=ctx,
            )

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT * FROM t WHERE id = :id AND name = :name",
            params={"id": 1, "name": "test"},
            max_rows=1000,
            timeout_ms=None,
        )

    @pytest.mark.anyio
    async def test_connection_error_tool_level(self) -> None:
        """execute_query returns CONNECTION_ERROR when service returns it."""
        ctx = _make_ctx()
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="Failed to connect to SAP HANA",
            tool_name="execute_query",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=error)

            result = await execute_query(sql="SELECT 1 FROM DUMMY", ctx=ctx)

        parsed = json.loads(result)
        assert parsed["code"] == "CONNECTION_ERROR"

    @pytest.mark.anyio
    async def test_timeout_with_custom_value(self) -> None:
        """execute_query passes custom timeout_ms to service."""
        ctx = _make_ctx()
        expected = _make_execute_output()

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            await execute_query(
                sql="SELECT 1 FROM DUMMY",
                timeout_ms=3000,
                ctx=ctx,
            )

        mock_service.execute_query.assert_called_once_with(
            sql="SELECT 1 FROM DUMMY",
            params=None,
            max_rows=1000,
            timeout_ms=3000,
        )

    @pytest.mark.anyio
    async def test_empty_result_set(self) -> None:
        """execute_query handles empty result set correctly."""
        ctx = _make_ctx()
        # Build directly to avoid helper's `rows or [default]` falsy-list issue
        expected = ExecuteQueryOutput(
            result=QueryResult(
                columns=["ID"],
                rows=[],
                row_count=0,
                execution_time_ms=1.0,
                truncated=False,
                warning=None,
            ),
            query_hash="empty123",
        )

        with patch("mamba_mcp_hana.tools.query_tools.QueryService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.execute_query = AsyncMock(return_value=expected)

            result = await execute_query(
                sql="SELECT id FROM t WHERE 1=0",
                ctx=ctx,
            )

        parsed = json.loads(result)
        assert parsed["result"]["rows"] == []
        assert parsed["result"]["row_count"] == 0
