"""Tests for Layer 1 schema discovery MCP tools."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_sap_hana.errors import ErrorCode, create_tool_error
from mamba_mcp_sap_hana.models.schema import (
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
from mamba_mcp_sap_hana.tools.schema_tools import (
    describe_table,
    get_sample_rows,
    list_schemas,
    list_tables,
)


def _make_mock_ctx() -> MagicMock:
    """Create a mock FastMCP context with pool accessible via lifespan_context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context.pool = MagicMock()
    return ctx


def _make_list_schemas_output(
    schemas: list[SchemaInfo] | None = None,
) -> ListSchemasOutput:
    """Build a ListSchemasOutput for testing."""
    s = schemas or []
    return ListSchemasOutput(schemas=s, count=len(s))


def _make_list_tables_output(
    tables: list[TableInfo] | None = None,
    schema_name: str = "MY_SCHEMA",
) -> ListTablesOutput:
    """Build a ListTablesOutput for testing."""
    t = tables or []
    return ListTablesOutput(tables=t, schema_name=schema_name, count=len(t))


def _make_describe_table_output(
    table_name: str = "USERS",
    schema_name: str = "MY_SCHEMA",
    columns: list[ColumnInfo] | None = None,
    indexes: list[IndexInfo] | None = None,
    constraints: list[ConstraintInfo] | None = None,
    is_view: bool = False,
) -> DescribeTableOutput:
    """Build a DescribeTableOutput for testing."""
    cols = columns or [
        ColumnInfo(
            name="ID",
            data_type="INTEGER",
            nullable=False,
            position=1,
        )
    ]
    return DescribeTableOutput(
        table_name=table_name,
        schema_name=schema_name,
        columns=cols,
        indexes=indexes or [],
        constraints=constraints or [],
        is_view=is_view,
    )


def _make_sample_rows_output(
    table_name: str = "USERS",
    schema_name: str = "MY_SCHEMA",
    columns: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    total_count: int = 100,
) -> SampleRowsOutput:
    """Build a SampleRowsOutput for testing."""
    c = columns if columns is not None else ["ID", "NAME"]
    r = rows if rows is not None else [{"ID": 1, "NAME": "Alice"}, {"ID": 2, "NAME": "Bob"}]
    return SampleRowsOutput(
        table_name=table_name,
        schema_name=schema_name,
        columns=c,
        rows=r,
        row_count=len(r),
        total_count=total_count,
    )


# ---------------------------------------------------------------------------
# list_schemas tests
# ---------------------------------------------------------------------------


class TestListSchemas:
    """Tests for list_schemas MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_schemas_json(self) -> None:
        """Tool returns JSON with schema information."""
        output = _make_list_schemas_output(
            schemas=[
                SchemaInfo(name="MY_SCHEMA", owner="ADMIN", table_count=10, is_system=False),
                SchemaInfo(name="SALES", owner="ADMIN", table_count=5, is_system=False),
            ]
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            result_json = await list_schemas(include_system=False, ctx=ctx)

        data = json.loads(result_json)
        assert data["count"] == 2
        assert len(data["schemas"]) == 2
        assert data["schemas"][0]["name"] == "MY_SCHEMA"
        assert data["schemas"][1]["name"] == "SALES"

    @pytest.mark.asyncio
    async def test_include_system_passed_to_service(self) -> None:
        """Tool passes include_system parameter to SchemaService."""
        output = _make_list_schemas_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            await list_schemas(include_system=True, ctx=ctx)

            mock_service.list_schemas.assert_awaited_once_with(include_system=True)

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns JSON error when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="Failed to query schemas",
            tool_name="list_schemas",
            input_received={"include_system": False},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=tool_error)

            result_json = await list_schemas(include_system=False, ctx=ctx)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert data["tool_name"] == "list_schemas"

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error JSON when no context is provided."""
        result_json = await list_schemas(ctx=None)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in data["message"].lower()
        assert data["tool_name"] == "list_schemas"

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates SchemaService with pool from context."""
        output = _make_list_schemas_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            await list_schemas(ctx=ctx)

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_service_exception_wrapped_in_error(self) -> None:
        """Tool catches unexpected exceptions and returns error JSON."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(side_effect=RuntimeError("Unexpected failure"))

            result_json = await list_schemas(ctx=ctx)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "Unexpected failure" in data["message"]
        assert data["tool_name"] == "list_schemas"

    @pytest.mark.asyncio
    async def test_returns_empty_schemas_list(self) -> None:
        """Tool returns valid JSON for empty schema list."""
        output = _make_list_schemas_output(schemas=[])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            result_json = await list_schemas(ctx=ctx)

        data = json.loads(result_json)
        assert data["count"] == 0
        assert data["schemas"] == []


# ---------------------------------------------------------------------------
# list_tables tests
# ---------------------------------------------------------------------------


class TestListTables:
    """Tests for list_tables MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_tables_json(self) -> None:
        """Tool returns JSON with table information."""
        output = _make_list_tables_output(
            tables=[
                TableInfo(
                    name="ORDERS",
                    type="TABLE",
                    record_count=1000,
                    column_count=8,
                    store_type="COLUMN",
                    is_column_table=True,
                ),
                TableInfo(
                    name="USERS_VIEW",
                    type="VIEW",
                    record_count=0,
                    column_count=5,
                    store_type=None,
                    is_column_table=False,
                ),
            ],
            schema_name="SALES",
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=output)

            result_json = await list_tables(schema_name="SALES", ctx=ctx)

        data = json.loads(result_json)
        assert data["count"] == 2
        assert data["schema_name"] == "SALES"
        assert data["tables"][0]["name"] == "ORDERS"
        assert data["tables"][0]["type"] == "TABLE"
        assert data["tables"][1]["type"] == "VIEW"

    @pytest.mark.asyncio
    async def test_passes_all_params_to_service(self) -> None:
        """Tool passes schema_name, include_views, and name_pattern to service."""
        output = _make_list_tables_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=output)

            await list_tables(
                schema_name="MY_SCHEMA",
                include_views=False,
                name_pattern="ORDER%",
                ctx=ctx,
            )

            mock_service.list_tables.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                include_views=False,
                name_pattern="ORDER%",
            )

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns JSON error when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema 'BAD_SCHEMA' not found",
            tool_name="list_tables",
            input_received={"schema_name": "BAD_SCHEMA"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=tool_error)

            result_json = await list_tables(schema_name="BAD_SCHEMA", ctx=ctx)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.SCHEMA_NOT_FOUND
        assert "not found" in data["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error JSON when no context is provided."""
        result_json = await list_tables(schema_name="SALES", ctx=None)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in data["message"].lower()
        assert data["tool_name"] == "list_tables"

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates SchemaService with pool from context."""
        output = _make_list_tables_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=output)

            await list_tables(schema_name="MY_SCHEMA", ctx=ctx)

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_service_exception_wrapped_in_error(self) -> None:
        """Tool catches unexpected exceptions and returns error JSON."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(side_effect=RuntimeError("Connection reset"))

            result_json = await list_tables(schema_name="SALES", ctx=ctx)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "Connection reset" in data["message"]


# ---------------------------------------------------------------------------
# describe_table tests
# ---------------------------------------------------------------------------


class TestDescribeTable:
    """Tests for describe_table MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_table_structure_json(self) -> None:
        """Tool returns JSON with columns, indexes, and constraints."""
        output = _make_describe_table_output(
            columns=[
                ColumnInfo(
                    name="ID",
                    data_type="INTEGER",
                    nullable=False,
                    position=1,
                ),
                ColumnInfo(
                    name="NAME",
                    data_type="NVARCHAR",
                    length=100,
                    nullable=True,
                    position=2,
                ),
            ],
            indexes=[
                IndexInfo(
                    name="PK_USERS",
                    columns=["ID"],
                    is_unique=True,
                    index_type="BTREE",
                ),
            ],
            constraints=[
                ConstraintInfo(
                    name="PK_USERS",
                    constraint_type="PRIMARY KEY",
                    columns=["ID"],
                ),
            ],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            result_json = await describe_table(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["table_name"] == "USERS"
        assert data["schema_name"] == "MY_SCHEMA"
        assert len(data["columns"]) == 2
        assert data["columns"][0]["name"] == "ID"
        assert len(data["indexes"]) == 1
        assert len(data["constraints"]) == 1
        assert data["is_view"] is False

    @pytest.mark.asyncio
    async def test_passes_all_params_to_service(self) -> None:
        """Tool passes all parameters to SchemaService.describe_table."""
        output = _make_describe_table_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            await describe_table(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                include_indexes=False,
                include_constraints=False,
                ctx=ctx,
            )

            mock_service.describe_table.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                table_name="USERS",
                include_indexes=False,
                include_constraints=False,
            )

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns JSON error when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'MISSING' not found in schema 'MY_SCHEMA'",
            tool_name="describe_table",
            input_received={"table_name": "MISSING", "schema_name": "MY_SCHEMA"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=tool_error)

            result_json = await describe_table(
                table_name="MISSING",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "not found" in data["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error JSON when no context is provided."""
        result_json = await describe_table(
            table_name="USERS",
            schema_name="MY_SCHEMA",
            ctx=None,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in data["message"].lower()
        assert data["tool_name"] == "describe_table"

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates SchemaService with pool from context."""
        output = _make_describe_table_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            await describe_table(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_service_exception_wrapped_in_error(self) -> None:
        """Tool catches unexpected exceptions and returns error JSON."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(side_effect=RuntimeError("Database error"))

            result_json = await describe_table(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "Database error" in data["message"]

    @pytest.mark.asyncio
    async def test_view_returns_is_view_true(self) -> None:
        """Tool returns is_view=True for views."""
        output = _make_describe_table_output(
            table_name="USERS_VIEW",
            is_view=True,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            result_json = await describe_table(
                table_name="USERS_VIEW",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["is_view"] is True


# ---------------------------------------------------------------------------
# get_sample_rows tests
# ---------------------------------------------------------------------------


class TestGetSampleRows:
    """Tests for get_sample_rows MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_sample_rows_json(self) -> None:
        """Tool returns JSON with sample rows and metadata."""
        output = _make_sample_rows_output(
            columns=["ID", "NAME", "EMAIL"],
            rows=[
                {"ID": 1, "NAME": "Alice", "EMAIL": "alice@example.com"},
                {"ID": 2, "NAME": "Bob", "EMAIL": "bob@example.com"},
            ],
            total_count=500,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            result_json = await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                limit=10,
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["table_name"] == "USERS"
        assert data["schema_name"] == "MY_SCHEMA"
        assert data["row_count"] == 2
        assert data["total_count"] == 500
        assert len(data["columns"]) == 3
        assert len(data["rows"]) == 2

    @pytest.mark.asyncio
    async def test_passes_all_params_to_service(self) -> None:
        """Tool passes all parameters to SchemaService.get_sample_rows."""
        output = _make_sample_rows_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                limit=20,
                columns=["ID", "NAME"],
                where_clause="ID > 10",
                randomize=True,
                ctx=ctx,
            )

            mock_service.get_sample_rows.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                table_name="USERS",
                limit=20,
                columns=["ID", "NAME"],
                where_clause="ID > 10",
                randomize=True,
            )

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns JSON error when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'MISSING' not found in schema 'MY_SCHEMA'",
            tool_name="get_sample_rows",
            input_received={"table_name": "MISSING", "schema_name": "MY_SCHEMA"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=tool_error)

            result_json = await get_sample_rows(
                table_name="MISSING",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "not found" in data["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error JSON when no context is provided."""
        result_json = await get_sample_rows(
            table_name="USERS",
            schema_name="MY_SCHEMA",
            ctx=None,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in data["message"].lower()
        assert data["tool_name"] == "get_sample_rows"

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates SchemaService with pool from context."""
        output = _make_sample_rows_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_service_exception_wrapped_in_error(self) -> None:
        """Tool catches unexpected exceptions and returns error JSON."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(side_effect=RuntimeError("Timeout"))

            result_json = await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "Timeout" in data["message"]

    @pytest.mark.asyncio
    async def test_limit_below_range_returns_error(self) -> None:
        """Tool returns PARAMETER_ERROR when limit < 1."""
        ctx = _make_mock_ctx()
        result_json = await get_sample_rows(
            table_name="USERS",
            schema_name="MY_SCHEMA",
            limit=0,
            ctx=ctx,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.PARAMETER_ERROR
        assert "limit" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_limit_above_range_returns_error(self) -> None:
        """Tool returns PARAMETER_ERROR when limit > 100."""
        ctx = _make_mock_ctx()
        result_json = await get_sample_rows(
            table_name="USERS",
            schema_name="MY_SCHEMA",
            limit=101,
            ctx=ctx,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.PARAMETER_ERROR
        assert "limit" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_limit_at_boundaries_accepted(self) -> None:
        """Tool accepts limit=1 and limit=100 as valid values."""
        output = _make_sample_rows_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            # Test limit=1
            result_json = await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                limit=1,
                ctx=ctx,
            )
            data = json.loads(result_json)
            assert "code" not in data  # Not an error

            # Test limit=100
            result_json = await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                limit=100,
                ctx=ctx,
            )
            data = json.loads(result_json)
            assert "code" not in data  # Not an error

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_rows(self) -> None:
        """Tool returns empty rows for an empty table."""
        output = _make_sample_rows_output(
            columns=["ID", "NAME"],
            rows=[],
            total_count=0,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            result_json = await get_sample_rows(
                table_name="EMPTY_TABLE",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["row_count"] == 0
        assert data["rows"] == []
        assert data["total_count"] == 0


# ---------------------------------------------------------------------------
# Tool registration test
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests for tool registration with FastMCP."""

    def test_schema_tools_are_registered_on_mcp(self) -> None:
        """All 4 schema tools are registered on the mcp server instance."""
        from mamba_mcp_sap_hana.server import mcp as server

        tool_names = []
        for tool in server._tool_manager._tools.values():
            tool_names.append(tool.name)

        assert "list_schemas" in tool_names
        assert "list_tables" in tool_names
        assert "describe_table" in tool_names
        assert "get_sample_rows" in tool_names

    def test_tools_have_docstrings(self) -> None:
        """Each tool function has a non-empty docstring."""
        assert list_schemas.__doc__
        assert list_tables.__doc__
        assert describe_table.__doc__
        assert get_sample_rows.__doc__


# ---------------------------------------------------------------------------
# Phase 2: Additional schema tool scenarios
# ---------------------------------------------------------------------------


class TestListSchemasExtended:
    """Extended tests for list_schemas including system schema handling."""

    @pytest.mark.asyncio
    async def test_system_schemas_included_when_requested(self) -> None:
        """Tool passes include_system=True and returns system schemas."""
        system_schemas = [
            SchemaInfo(name="SYS", owner="SYS", table_count=200, is_system=True),
            SchemaInfo(name="_SYS_BIC", owner="SYS", table_count=50, is_system=True),
            SchemaInfo(name="MY_SCHEMA", owner="ADMIN", table_count=10, is_system=False),
        ]
        output = _make_list_schemas_output(schemas=system_schemas)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            result_json = await list_schemas(include_system=True, ctx=ctx)

        data = json.loads(result_json)
        assert data["count"] == 3
        names = [s["name"] for s in data["schemas"]]
        assert "SYS" in names
        assert "_SYS_BIC" in names
        assert "MY_SCHEMA" in names

    @pytest.mark.asyncio
    async def test_system_schemas_excluded_by_default(self) -> None:
        """Tool defaults to include_system=False, filtering system schemas."""
        user_schemas = [
            SchemaInfo(name="MY_SCHEMA", owner="ADMIN", table_count=10, is_system=False),
        ]
        output = _make_list_schemas_output(schemas=user_schemas)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            result_json = await list_schemas(ctx=ctx)

        mock_service.list_schemas.assert_awaited_once_with(include_system=False)
        data = json.loads(result_json)
        assert data["count"] == 1
        assert data["schemas"][0]["name"] == "MY_SCHEMA"

    @pytest.mark.asyncio
    async def test_is_system_flag_in_output(self) -> None:
        """Tool returns is_system flag for each schema."""
        schemas = [
            SchemaInfo(name="SYS", owner="SYS", table_count=200, is_system=True),
            SchemaInfo(name="APP", owner="ADMIN", table_count=5, is_system=False),
        ]
        output = _make_list_schemas_output(schemas=schemas)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_schemas = AsyncMock(return_value=output)

            result_json = await list_schemas(include_system=True, ctx=ctx)

        data = json.loads(result_json)
        schema_map = {s["name"]: s for s in data["schemas"]}
        assert schema_map["SYS"]["is_system"] is True
        assert schema_map["APP"]["is_system"] is False


class TestListTablesExtended:
    """Extended tests for list_tables with view inclusion and name patterns."""

    @pytest.mark.asyncio
    async def test_include_views_false_passed(self) -> None:
        """Tool passes include_views=False to filter out views."""
        tables_only = [
            TableInfo(
                name="ORDERS",
                type="TABLE",
                record_count=100,
                column_count=5,
                store_type="COLUMN",
                is_column_table=True,
            ),
        ]
        output = _make_list_tables_output(tables=tables_only)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=output)

            result_json = await list_tables(
                schema_name="SALES",
                include_views=False,
                ctx=ctx,
            )

        mock_service.list_tables.assert_awaited_once_with(
            schema_name="SALES",
            include_views=False,
            name_pattern=None,
        )
        data = json.loads(result_json)
        assert data["count"] == 1
        assert all(t["type"] == "TABLE" for t in data["tables"])

    @pytest.mark.asyncio
    async def test_name_pattern_filter_passed(self) -> None:
        """Tool passes name_pattern SQL LIKE filter to service."""
        filtered = [
            TableInfo(
                name="USER_ROLES",
                type="TABLE",
                record_count=50,
                column_count=3,
                store_type="COLUMN",
                is_column_table=True,
            ),
        ]
        output = _make_list_tables_output(tables=filtered)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=output)

            result_json = await list_tables(
                schema_name="MY_SCHEMA",
                name_pattern="USER%",
                ctx=ctx,
            )

        mock_service.list_tables.assert_awaited_once_with(
            schema_name="MY_SCHEMA",
            include_views=True,
            name_pattern="USER%",
        )
        data = json.loads(result_json)
        assert data["count"] == 1
        assert data["tables"][0]["name"] == "USER_ROLES"

    @pytest.mark.asyncio
    async def test_schema_not_found_fuzzy_suggestion(self) -> None:
        """Tool returns error with fuzzy suggestion for mistyped schema."""
        tool_error = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema 'PRODCTN' not found",
            suggestion="Did you mean: PRODUCTION, PRODUCTION_DEV?",
            tool_name="list_tables",
            input_received={"schema_name": "PRODCTN"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=tool_error)

            result_json = await list_tables(schema_name="PRODCTN", ctx=ctx)

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.SCHEMA_NOT_FOUND
        assert "PRODUCTION" in data["suggestion"]

    @pytest.mark.asyncio
    async def test_store_type_in_output(self) -> None:
        """Tool returns store_type and is_column_table for each table."""
        tables = [
            TableInfo(
                name="COL_TABLE",
                type="TABLE",
                record_count=100,
                column_count=5,
                store_type="COLUMN",
                is_column_table=True,
            ),
            TableInfo(
                name="ROW_TABLE",
                type="TABLE",
                record_count=50,
                column_count=3,
                store_type="ROW",
                is_column_table=False,
            ),
            TableInfo(
                name="MY_VIEW",
                type="VIEW",
                record_count=0,
                column_count=4,
                store_type=None,
                is_column_table=False,
            ),
        ]
        output = _make_list_tables_output(tables=tables)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_tables = AsyncMock(return_value=output)

            result_json = await list_tables(schema_name="MY_SCHEMA", ctx=ctx)

        data = json.loads(result_json)
        tbl_map = {t["name"]: t for t in data["tables"]}
        assert tbl_map["COL_TABLE"]["store_type"] == "COLUMN"
        assert tbl_map["COL_TABLE"]["is_column_table"] is True
        assert tbl_map["ROW_TABLE"]["store_type"] == "ROW"
        assert tbl_map["ROW_TABLE"]["is_column_table"] is False
        assert tbl_map["MY_VIEW"]["store_type"] is None


class TestDescribeTableExtended:
    """Extended tests for describe_table covering views and multi-column objects."""

    @pytest.mark.asyncio
    async def test_describe_view_empty_indexes_constraints(self) -> None:
        """View description has is_view=True, empty indexes and constraints."""
        output = _make_describe_table_output(
            table_name="ACTIVE_USERS",
            is_view=True,
            indexes=[],
            constraints=[],
            columns=[
                ColumnInfo(name="ID", data_type="INTEGER", nullable=False, position=1),
                ColumnInfo(name="STATUS", data_type="NVARCHAR", nullable=True, position=2),
            ],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            result_json = await describe_table(
                table_name="ACTIVE_USERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["is_view"] is True
        assert data["indexes"] == []
        assert data["constraints"] == []
        assert len(data["columns"]) == 2

    @pytest.mark.asyncio
    async def test_multi_column_index_in_output(self) -> None:
        """Describe returns multi-column composite index correctly."""
        output = _make_describe_table_output(
            table_name="ORDERS",
            indexes=[
                IndexInfo(
                    name="IDX_USER_STATUS",
                    columns=["USER_ID", "STATUS"],
                    is_unique=False,
                    index_type="CPBTREE",
                ),
            ],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            result_json = await describe_table(
                table_name="ORDERS",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert len(data["indexes"]) == 1
        idx = data["indexes"][0]
        assert idx["name"] == "IDX_USER_STATUS"
        assert idx["columns"] == ["USER_ID", "STATUS"]
        assert idx["is_unique"] is False

    @pytest.mark.asyncio
    async def test_table_not_found_fuzzy_suggestion(self) -> None:
        """describe_table returns fuzzy suggestions for mistyped table."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'CUSTMERS' not found in schema 'SALES'",
            suggestion="Did you mean: CUSTOMERS, CUSTOMER_ORDERS?",
            tool_name="describe_table",
            input_received={"table_name": "CUSTMERS", "schema_name": "SALES"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=tool_error)

            result_json = await describe_table(
                table_name="CUSTMERS",
                schema_name="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "CUSTOMERS" in data["suggestion"]

    @pytest.mark.asyncio
    async def test_include_indexes_false_skips_indexes(self) -> None:
        """describe_table passes include_indexes=False to skip indexes."""
        output = _make_describe_table_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.describe_table = AsyncMock(return_value=output)

            await describe_table(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                include_indexes=False,
                include_constraints=True,
                ctx=ctx,
            )

        mock_service.describe_table.assert_awaited_once_with(
            schema_name="MY_SCHEMA",
            table_name="USERS",
            include_indexes=False,
            include_constraints=True,
        )


class TestGetSampleRowsExtended:
    """Extended tests for get_sample_rows with column selection, WHERE, randomize."""

    @pytest.mark.asyncio
    async def test_column_selection_passed_to_service(self) -> None:
        """Tool passes specific columns to service for column selection."""
        output = _make_sample_rows_output(
            columns=["ID", "EMAIL"],
            rows=[{"ID": 1, "EMAIL": "alice@x.com"}],
            total_count=500,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            result_json = await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                columns=["ID", "EMAIL"],
                ctx=ctx,
            )

        mock_service.get_sample_rows.assert_awaited_once_with(
            schema_name="MY_SCHEMA",
            table_name="USERS",
            limit=10,
            columns=["ID", "EMAIL"],
            where_clause=None,
            randomize=False,
        )
        data = json.loads(result_json)
        assert data["columns"] == ["ID", "EMAIL"]

    @pytest.mark.asyncio
    async def test_where_clause_passed_to_service(self) -> None:
        """Tool passes WHERE clause to service for filtered sampling."""
        output = _make_sample_rows_output(
            rows=[{"ID": 5, "NAME": "Charlie"}],
            total_count=100,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            result_json = await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                where_clause="STATUS = 'ACTIVE'",
                ctx=ctx,
            )

        call_kwargs = mock_service.get_sample_rows.call_args.kwargs
        assert call_kwargs["where_clause"] == "STATUS = 'ACTIVE'"
        data = json.loads(result_json)
        assert data["row_count"] == 1

    @pytest.mark.asyncio
    async def test_randomize_passed_to_service(self) -> None:
        """Tool passes randomize=True to service for random sampling."""
        output = _make_sample_rows_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                randomize=True,
                ctx=ctx,
            )

        call_kwargs = mock_service.get_sample_rows.call_args.kwargs
        assert call_kwargs["randomize"] is True

    @pytest.mark.asyncio
    async def test_table_not_found_fuzzy_suggestion(self) -> None:
        """get_sample_rows returns fuzzy suggestions for mistyped table."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'USRES' not found in schema 'MY_SCHEMA'",
            suggestion="Did you mean: USERS, USER_ROLES?",
            tool_name="get_sample_rows",
            input_received={"table_name": "USRES", "schema_name": "MY_SCHEMA"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=tool_error)

            result_json = await get_sample_rows(
                table_name="USRES",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "USERS" in data["suggestion"]

    @pytest.mark.asyncio
    async def test_negative_limit_returns_error(self) -> None:
        """Tool returns PARAMETER_ERROR when limit is negative."""
        ctx = _make_mock_ctx()
        result_json = await get_sample_rows(
            table_name="USERS",
            schema_name="MY_SCHEMA",
            limit=-5,
            ctx=ctx,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.PARAMETER_ERROR
        assert "limit" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_combined_options(self) -> None:
        """Tool correctly passes all options simultaneously."""
        output = _make_sample_rows_output(
            columns=["ID"],
            rows=[{"ID": 42}],
            total_count=10,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.schema_tools.SchemaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_sample_rows = AsyncMock(return_value=output)

            await get_sample_rows(
                table_name="USERS",
                schema_name="MY_SCHEMA",
                limit=5,
                columns=["ID"],
                where_clause="ID > 10",
                randomize=True,
                ctx=ctx,
            )

        mock_service.get_sample_rows.assert_awaited_once_with(
            schema_name="MY_SCHEMA",
            table_name="USERS",
            limit=5,
            columns=["ID"],
            where_clause="ID > 10",
            randomize=True,
        )
