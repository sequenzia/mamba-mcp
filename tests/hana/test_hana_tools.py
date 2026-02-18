"""Tests for Layer 4 HANA-specific MCP tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_hana.database.connection import HanaConnectionPool
from mamba_mcp_hana.database.hana import (
    CALC_VIEW_PRIVILEGE_NOTE,
    COLUMN_STORE_IMPLICATIONS,
    ROW_STORE_IMPLICATIONS,
    HanaService,
)
from mamba_mcp_hana.errors import ErrorCode, ToolError, create_tool_error
from mamba_mcp_hana.models.hana import (
    CalcViewColumnInfo,
    CalcViewInfo,
    GetTableStoreTypeOutput,
    ListCalcViewsOutput,
    ListProceduresOutput,
    ProcedureInfo,
    ProcedureParameterInfo,
    StoreTypeInfo,
)
from mamba_mcp_hana.tools.hana_tools import (
    get_table_store_type,
    list_calculation_views,
    list_procedures,
)


def _make_mock_ctx() -> MagicMock:
    """Create a mock FastMCP context with pool accessible via lifespan_context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context.pool = MagicMock()
    return ctx


def _make_calc_views_output(
    views: list[CalcViewInfo] | None = None,
    schema_name: str = "MY_SCHEMA",
) -> ListCalcViewsOutput:
    """Build a ListCalcViewsOutput for testing."""
    v = views if views is not None else []
    return ListCalcViewsOutput(views=v, schema_name=schema_name, count=len(v))


def _make_store_type_output(
    table_name: str = "ORDERS",
    schema_name: str = "SALES",
    store_type: str = "COLUMN",
    is_column_table: bool = True,
    has_partitions: bool = False,
    partition_count: int = 0,
    is_compressed: bool = True,
    implications: str = "Column store: optimized for analytics.",
) -> GetTableStoreTypeOutput:
    """Build a GetTableStoreTypeOutput for testing."""
    info = StoreTypeInfo(
        table_name=table_name,
        schema_name=schema_name,
        store_type=store_type,
        is_column_table=is_column_table,
        has_partitions=has_partitions,
        partition_count=partition_count,
        is_compressed=is_compressed,
        implications=implications,
    )
    return GetTableStoreTypeOutput(store_info=info)


def _make_procedures_output(
    procedures: list[ProcedureInfo] | None = None,
    schema_name: str = "MY_SCHEMA",
) -> ListProceduresOutput:
    """Build a ListProceduresOutput for testing."""
    p = procedures if procedures is not None else []
    return ListProceduresOutput(procedures=p, schema_name=schema_name, count=len(p))


# ---------------------------------------------------------------------------
# list_calculation_views tests
# ---------------------------------------------------------------------------


class TestListCalculationViews:
    """Tests for list_calculation_views MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_views_with_metadata(self) -> None:
        """Tool returns ListCalcViewsOutput with calculation view details."""
        view = CalcViewInfo(
            name="CV_SALES_REPORT",
            schema_name="MY_SCHEMA",
            type="CALC",
            description="Sales report view",
            is_active=True,
            column_count=5,
        )
        output = _make_calc_views_output(views=[view])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            result = await list_calculation_views(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListCalcViewsOutput)
        assert result.schema_name == "MY_SCHEMA"
        assert result.count == 1
        assert result.views[0].name == "CV_SALES_REPORT"
        assert result.views[0].type == "CALC"
        assert result.views[0].is_active is True

    @pytest.mark.asyncio
    async def test_returns_views_with_columns(self) -> None:
        """Tool returns column metadata when include_columns is True."""
        col = CalcViewColumnInfo(
            name="AMOUNT",
            data_type="DECIMAL",
            description="Sale amount",
        )
        view = CalcViewInfo(
            name="CV_REPORT",
            schema_name="MY_SCHEMA",
            type="CALC",
            is_active=True,
            column_count=1,
            columns=[col],
        )
        output = _make_calc_views_output(views=[view])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            result = await list_calculation_views(
                schema_name="MY_SCHEMA",
                include_columns=True,
                ctx=ctx,
            )

        assert isinstance(result, ListCalcViewsOutput)
        assert len(result.views[0].columns) == 1
        assert result.views[0].columns[0].name == "AMOUNT"
        assert result.views[0].columns[0].data_type == "DECIMAL"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_views(self) -> None:
        """Tool returns empty views list for schema without calc views."""
        output = _make_calc_views_output(views=[])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            result = await list_calculation_views(
                schema_name="EMPTY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListCalcViewsOutput)
        assert result.views == []
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns error dict when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema 'BAD_SCHEMA' not found",
            tool_name="list_calculation_views",
            input_received={"schema_name": "BAD_SCHEMA"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=tool_error)

            result = await list_calculation_views(
                schema_name="BAD_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.SCHEMA_NOT_FOUND
        assert "not found" in result["message"]
        assert result["tool_name"] == "list_calculation_views"

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self) -> None:
        """Tool wraps unexpected exceptions in CONNECTION_ERROR."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(
                side_effect=RuntimeError("DB connection lost")
            )

            result = await list_calculation_views(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "DB connection lost" in result["message"]
        assert result["tool_name"] == "list_calculation_views"

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error dict when no context is provided."""
        result = await list_calculation_views(
            schema_name="MY_SCHEMA",
            ctx=None,
        )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in result["message"].lower()
        assert result["tool_name"] == "list_calculation_views"

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self) -> None:
        """Tool passes schema_name and include_columns to HanaService."""
        output = _make_calc_views_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            await list_calculation_views(
                schema_name="TEST_SCHEMA",
                include_columns=True,
                ctx=ctx,
            )

            mock_service.list_calculation_views.assert_awaited_once_with(
                schema_name="TEST_SCHEMA",
                include_columns=True,
            )

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates HanaService with pool from context."""
        output = _make_calc_views_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            await list_calculation_views(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_analytic_privilege_note_in_tool_docstring(self) -> None:
        """Tool docstring mentions analytic privilege requirement."""
        assert list_calculation_views.__doc__ is not None
        assert "analytic" in list_calculation_views.__doc__.lower()
        assert "privilege" in list_calculation_views.__doc__.lower()

    @pytest.mark.asyncio
    async def test_multiple_views_with_different_types(self) -> None:
        """Tool returns multiple views of different types (CALC, JOIN, OLAP)."""
        views = [
            CalcViewInfo(
                name="CV_CALC_VIEW",
                schema_name="MY_SCHEMA",
                type="CALC",
                is_active=True,
                column_count=3,
            ),
            CalcViewInfo(
                name="CV_JOIN_VIEW",
                schema_name="MY_SCHEMA",
                type="JOIN",
                is_active=True,
                column_count=5,
            ),
            CalcViewInfo(
                name="CV_OLAP_VIEW",
                schema_name="MY_SCHEMA",
                type="OLAP",
                is_active=False,
                column_count=8,
            ),
        ]
        output = _make_calc_views_output(views=views)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            result = await list_calculation_views(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 3
        types = [v.type for v in result.views]
        assert "CALC" in types
        assert "JOIN" in types
        assert "OLAP" in types
        # Verify inactive view is included
        olap_view = next(v for v in result.views if v.type == "OLAP")
        assert olap_view.is_active is False

    @pytest.mark.asyncio
    async def test_view_with_columns_excluded(self) -> None:
        """Tool returns empty columns when include_columns defaults to False."""
        view = CalcViewInfo(
            name="CV_REPORT",
            schema_name="MY_SCHEMA",
            type="CALC",
            is_active=True,
            column_count=10,
            columns=[],
        )
        output = _make_calc_views_output(views=[view])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            result = await list_calculation_views(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListCalcViewsOutput)
        assert result.views[0].columns == []
        assert result.views[0].column_count == 10

    @pytest.mark.asyncio
    async def test_default_include_columns_is_false(self) -> None:
        """Tool defaults include_columns to False when not specified."""
        output = _make_calc_views_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            await list_calculation_views(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_service.list_calculation_views.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                include_columns=False,
            )

    @pytest.mark.asyncio
    async def test_multiple_columns_metadata(self) -> None:
        """Tool returns multiple columns with full metadata for each view."""
        cols = [
            CalcViewColumnInfo(name="AMOUNT", data_type="DECIMAL", description="Total amount"),
            CalcViewColumnInfo(name="REGION", data_type="NVARCHAR", description=None),
            CalcViewColumnInfo(
                name="IS_ACTIVE",
                data_type="BOOLEAN",
                description="Active flag",
                is_key=True,
            ),
        ]
        view = CalcViewInfo(
            name="CV_DETAIL",
            schema_name="MY_SCHEMA",
            type="CALC",
            is_active=True,
            column_count=3,
            columns=cols,
        )
        output = _make_calc_views_output(views=[view])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_calculation_views = AsyncMock(return_value=output)

            result = await list_calculation_views(
                schema_name="MY_SCHEMA",
                include_columns=True,
                ctx=ctx,
            )

        assert isinstance(result, ListCalcViewsOutput)
        columns = result.views[0].columns
        assert len(columns) == 3
        assert columns[0].name == "AMOUNT"
        assert columns[0].data_type == "DECIMAL"
        assert columns[0].description == "Total amount"
        assert columns[1].description is None
        assert columns[2].is_key is True


# ---------------------------------------------------------------------------
# get_table_store_type tests
# ---------------------------------------------------------------------------


class TestGetTableStoreType:
    """Tests for get_table_store_type MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_column_store_info(self) -> None:
        """Tool returns GetTableStoreTypeOutput with column store type details."""
        output = _make_store_type_output(
            table_name="ORDERS",
            schema_name="SALES",
            store_type="COLUMN",
            is_column_table=True,
            is_compressed=True,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            result = await get_table_store_type(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        assert isinstance(result, GetTableStoreTypeOutput)
        assert result.store_info.table_name == "ORDERS"
        assert result.store_info.store_type == "COLUMN"
        assert result.store_info.is_column_table is True
        assert result.store_info.is_compressed is True

    @pytest.mark.asyncio
    async def test_returns_row_store_info(self) -> None:
        """Tool returns GetTableStoreTypeOutput with row store type details."""
        output = _make_store_type_output(
            table_name="SETTINGS",
            schema_name="ADMIN",
            store_type="ROW",
            is_column_table=False,
            is_compressed=False,
            implications="Row store: optimized for point lookups.",
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            result = await get_table_store_type(
                table_name="SETTINGS",
                schema_name="ADMIN",
                ctx=ctx,
            )

        assert isinstance(result, GetTableStoreTypeOutput)
        assert result.store_info.store_type == "ROW"
        assert result.store_info.is_column_table is False

    @pytest.mark.asyncio
    async def test_handles_table_not_found_error(self) -> None:
        """Tool returns error dict when table is not found."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'MISSING' not found in schema 'SALES'",
            tool_name="get_table_store_type",
            input_received={"schema_name": "SALES", "table_name": "MISSING"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=tool_error)

            result = await get_table_store_type(
                table_name="MISSING",
                schema_name="SALES",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_handles_view_parameter_error(self) -> None:
        """Tool returns PARAMETER_ERROR when target is a view."""
        tool_error = create_tool_error(
            code=ErrorCode.PARAMETER_ERROR,
            message="'MY_VIEW' is a view, not a table.",
            tool_name="get_table_store_type",
            input_received={"schema_name": "SALES", "table_name": "MY_VIEW"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=tool_error)

            result = await get_table_store_type(
                table_name="MY_VIEW",
                schema_name="SALES",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PARAMETER_ERROR
        assert "view" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self) -> None:
        """Tool wraps unexpected exceptions in CONNECTION_ERROR."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(
                side_effect=RuntimeError("Connection timeout")
            )

            result = await get_table_store_type(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "Connection timeout" in result["message"]
        assert result["tool_name"] == "get_table_store_type"

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error dict when no context is provided."""
        result = await get_table_store_type(
            table_name="ORDERS",
            schema_name="SALES",
            ctx=None,
        )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in result["message"].lower()
        assert result["tool_name"] == "get_table_store_type"

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self) -> None:
        """Tool passes table_name and schema_name to HanaService."""
        output = _make_store_type_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            await get_table_store_type(
                table_name="MY_TABLE",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_service.get_table_store_type.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                table_name="MY_TABLE",
            )

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates HanaService with pool from context."""
        output = _make_store_type_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            await get_table_store_type(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_returns_partition_info(self) -> None:
        """Tool returns partitioning information in store type output."""
        output = _make_store_type_output(
            has_partitions=True,
            partition_count=4,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            result = await get_table_store_type(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        assert isinstance(result, GetTableStoreTypeOutput)
        assert result.store_info.has_partitions is True
        assert result.store_info.partition_count == 4

    @pytest.mark.asyncio
    async def test_column_store_compression_metadata(self) -> None:
        """Tool returns compression status for column store tables."""
        output = _make_store_type_output(
            table_name="LARGE_TABLE",
            schema_name="ANALYTICS",
            store_type="COLUMN",
            is_column_table=True,
            is_compressed=True,
            has_partitions=True,
            partition_count=8,
            implications=COLUMN_STORE_IMPLICATIONS,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            result = await get_table_store_type(
                table_name="LARGE_TABLE",
                schema_name="ANALYTICS",
                ctx=ctx,
            )

        assert isinstance(result, GetTableStoreTypeOutput)
        info = result.store_info
        assert info.is_compressed is True
        assert info.store_type == "COLUMN"
        assert info.is_column_table is True
        assert info.has_partitions is True
        assert info.partition_count == 8
        assert "compressed" in info.implications.lower()
        assert "analytical" in info.implications.lower()

    @pytest.mark.asyncio
    async def test_row_store_no_compression(self) -> None:
        """Tool returns no compression for row store tables."""
        output = _make_store_type_output(
            table_name="CONFIG_TABLE",
            schema_name="ADMIN",
            store_type="ROW",
            is_column_table=False,
            is_compressed=False,
            has_partitions=False,
            partition_count=0,
            implications=ROW_STORE_IMPLICATIONS,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            result = await get_table_store_type(
                table_name="CONFIG_TABLE",
                schema_name="ADMIN",
                ctx=ctx,
            )

        assert isinstance(result, GetTableStoreTypeOutput)
        info = result.store_info
        assert info.is_compressed is False
        assert info.store_type == "ROW"
        assert info.is_column_table is False
        assert info.has_partitions is False
        assert info.partition_count == 0
        assert "point lookups" in info.implications.lower()

    @pytest.mark.asyncio
    async def test_column_store_without_partitions(self) -> None:
        """Tool returns column store table with no partitions."""
        output = _make_store_type_output(
            table_name="SMALL_TABLE",
            schema_name="MY_SCHEMA",
            store_type="COLUMN",
            is_column_table=True,
            is_compressed=False,
            has_partitions=False,
            partition_count=0,
            implications=COLUMN_STORE_IMPLICATIONS,
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=output)

            result = await get_table_store_type(
                table_name="SMALL_TABLE",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, GetTableStoreTypeOutput)
        info = result.store_info
        assert info.store_type == "COLUMN"
        assert info.has_partitions is False
        assert info.partition_count == 0

    @pytest.mark.asyncio
    async def test_store_type_tool_docstring_explains_implications(self) -> None:
        """Tool docstring explains column vs row store implications."""
        assert get_table_store_type.__doc__ is not None
        doc = get_table_store_type.__doc__.lower()
        assert "column store" in doc
        assert "row store" in doc
        assert "analytical" in doc
        assert "point lookups" in doc

    @pytest.mark.asyncio
    async def test_view_error_includes_suggestion(self) -> None:
        """Tool error for views includes describe_table suggestion."""
        tool_error = create_tool_error(
            code=ErrorCode.PARAMETER_ERROR,
            message="'MY_VIEW' is a view, not a table.",
            tool_name="get_table_store_type",
            input_received={"schema_name": "SALES", "table_name": "MY_VIEW"},
            suggestion="Use describe_table to get view details.",
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_table_store_type = AsyncMock(return_value=tool_error)

            result = await get_table_store_type(
                table_name="MY_VIEW",
                schema_name="SALES",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PARAMETER_ERROR
        assert result["suggestion"] is not None
        assert "describe_table" in result["suggestion"]


# ---------------------------------------------------------------------------
# list_procedures tests
# ---------------------------------------------------------------------------


class TestListProcedures:
    """Tests for list_procedures MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_procedures_with_metadata(self) -> None:
        """Tool returns ListProceduresOutput with procedure details."""
        proc = ProcedureInfo(
            name="CALCULATE_TOTALS",
            schema_name="MY_SCHEMA",
            type="SQLSCRIPT",
            parameter_count=2,
            is_read_only=True,
        )
        output = _make_procedures_output(procedures=[proc])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        assert result.schema_name == "MY_SCHEMA"
        assert result.count == 1
        assert result.procedures[0].name == "CALCULATE_TOTALS"
        assert result.procedures[0].type == "SQLSCRIPT"
        assert result.procedures[0].is_read_only is True

    @pytest.mark.asyncio
    async def test_returns_procedures_with_parameters(self) -> None:
        """Tool returns parameter details when include_parameters is True."""
        param = ProcedureParameterInfo(
            name="IV_AMOUNT",
            data_type="DECIMAL",
            direction="IN",
            position=1,
        )
        proc = ProcedureInfo(
            name="CALCULATE_TOTALS",
            schema_name="MY_SCHEMA",
            type="SQLSCRIPT",
            parameter_count=1,
            is_read_only=False,
            parameters=[param],
        )
        output = _make_procedures_output(procedures=[proc])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                include_parameters=True,
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        params = result.procedures[0].parameters
        assert len(params) == 1
        assert params[0].name == "IV_AMOUNT"
        assert params[0].direction == "IN"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_procedures(self) -> None:
        """Tool returns empty procedures list for schema without procs."""
        output = _make_procedures_output(procedures=[])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="EMPTY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        assert result.procedures == []
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns error dict when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema 'BAD_SCHEMA' not found",
            tool_name="list_procedures",
            input_received={"schema_name": "BAD_SCHEMA"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=tool_error)

            result = await list_procedures(
                schema_name="BAD_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.SCHEMA_NOT_FOUND
        assert "not found" in result["message"]
        assert result["tool_name"] == "list_procedures"

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self) -> None:
        """Tool wraps unexpected exceptions in CONNECTION_ERROR."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(side_effect=RuntimeError("Network failure"))

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "Network failure" in result["message"]
        assert result["tool_name"] == "list_procedures"

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error dict when no context is provided."""
        result = await list_procedures(
            schema_name="MY_SCHEMA",
            ctx=None,
        )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in result["message"].lower()
        assert result["tool_name"] == "list_procedures"

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self) -> None:
        """Tool passes schema_name and include_parameters to HanaService."""
        output = _make_procedures_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            await list_procedures(
                schema_name="TEST_SCHEMA",
                include_parameters=True,
                ctx=ctx,
            )

            mock_service.list_procedures.assert_awaited_once_with(
                schema_name="TEST_SCHEMA",
                include_parameters=True,
            )

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates HanaService with pool from context."""
        output = _make_procedures_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            await list_procedures(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_procedure_with_no_parameters(self) -> None:
        """Tool returns procedure with empty parameter list."""
        proc = ProcedureInfo(
            name="NO_PARAMS_PROC",
            schema_name="MY_SCHEMA",
            type="SQLSCRIPT",
            parameter_count=0,
            is_read_only=True,
            parameters=[],
        )
        output = _make_procedures_output(procedures=[proc])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                include_parameters=True,
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        assert result.procedures[0].parameter_count == 0
        assert result.procedures[0].parameters == []

    @pytest.mark.asyncio
    async def test_procedure_types_sqlscript_r_l(self) -> None:
        """Tool returns procedures of all three types: SQLScript, R, L."""
        procs = [
            ProcedureInfo(
                name="SQL_PROC",
                schema_name="MY_SCHEMA",
                type="SQLSCRIPT",
                parameter_count=1,
                is_read_only=True,
            ),
            ProcedureInfo(
                name="R_PROC",
                schema_name="MY_SCHEMA",
                type="R",
                parameter_count=2,
                is_read_only=False,
            ),
            ProcedureInfo(
                name="L_PROC",
                schema_name="MY_SCHEMA",
                type="L",
                parameter_count=0,
                is_read_only=True,
            ),
        ]
        output = _make_procedures_output(procedures=procs)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 3
        proc_types = {p.name: p.type for p in result.procedures}
        assert proc_types["SQL_PROC"] == "SQLSCRIPT"
        assert proc_types["R_PROC"] == "R"
        assert proc_types["L_PROC"] == "L"

    @pytest.mark.asyncio
    async def test_procedure_with_mixed_direction_parameters(self) -> None:
        """Tool returns procedure with IN, OUT, and INOUT parameters."""
        params = [
            ProcedureParameterInfo(
                name="P_INPUT",
                data_type="NVARCHAR",
                direction="IN",
                position=1,
            ),
            ProcedureParameterInfo(
                name="P_OUTPUT",
                data_type="INTEGER",
                direction="OUT",
                position=2,
            ),
            ProcedureParameterInfo(
                name="P_BOTH",
                data_type="DECIMAL",
                direction="INOUT",
                position=3,
            ),
        ]
        proc = ProcedureInfo(
            name="MIXED_PROC",
            schema_name="MY_SCHEMA",
            type="SQLSCRIPT",
            parameter_count=3,
            is_read_only=False,
            parameters=params,
        )
        output = _make_procedures_output(procedures=[proc])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                include_parameters=True,
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        proc_data = result.procedures[0]
        assert proc_data.parameter_count == 3
        directions = [p.direction for p in proc_data.parameters]
        assert "IN" in directions
        assert "OUT" in directions
        assert "INOUT" in directions

    @pytest.mark.asyncio
    async def test_default_include_parameters_is_false(self) -> None:
        """Tool defaults include_parameters to False when not specified."""
        output = _make_procedures_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            await list_procedures(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_service.list_procedures.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                include_parameters=False,
            )

    @pytest.mark.asyncio
    async def test_multiple_procedures_with_parameters(self) -> None:
        """Tool returns multiple procedures each with parameter details."""
        proc1_params = [
            ProcedureParameterInfo(
                name="P_SCHEMA",
                data_type="NVARCHAR",
                direction="IN",
                position=1,
            ),
        ]
        proc2_params = [
            ProcedureParameterInfo(
                name="P_X",
                data_type="INTEGER",
                direction="IN",
                position=1,
                default_value="0",
            ),
            ProcedureParameterInfo(
                name="P_RESULT",
                data_type="TABLE",
                direction="OUT",
                position=2,
            ),
        ]
        procs = [
            ProcedureInfo(
                name="PROC_A",
                schema_name="MY_SCHEMA",
                type="SQLSCRIPT",
                parameter_count=1,
                is_read_only=True,
                parameters=proc1_params,
            ),
            ProcedureInfo(
                name="PROC_B",
                schema_name="MY_SCHEMA",
                type="L",
                parameter_count=2,
                is_read_only=False,
                parameters=proc2_params,
            ),
        ]
        output = _make_procedures_output(procedures=procs)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                include_parameters=True,
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 2
        proc_map = {p.name: p for p in result.procedures}
        assert len(proc_map["PROC_A"].parameters) == 1
        assert len(proc_map["PROC_B"].parameters) == 2
        assert proc_map["PROC_B"].parameters[0].default_value == "0"
        assert proc_map["PROC_B"].parameters[1].direction == "OUT"

    @pytest.mark.asyncio
    async def test_procedure_read_only_status(self) -> None:
        """Tool correctly reports read_only status for procedures."""
        procs = [
            ProcedureInfo(
                name="READ_ONLY_PROC",
                schema_name="MY_SCHEMA",
                type="SQLSCRIPT",
                parameter_count=0,
                is_read_only=True,
            ),
            ProcedureInfo(
                name="WRITE_PROC",
                schema_name="MY_SCHEMA",
                type="SQLSCRIPT",
                parameter_count=1,
                is_read_only=False,
            ),
        ]
        output = _make_procedures_output(procedures=procs)

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_hana.tools.hana_tools.HanaService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.list_procedures = AsyncMock(return_value=output)

            result = await list_procedures(
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

        assert isinstance(result, ListProceduresOutput)
        proc_map = {p.name: p for p in result.procedures}
        assert proc_map["READ_ONLY_PROC"].is_read_only is True
        assert proc_map["WRITE_PROC"].is_read_only is False


# ---------------------------------------------------------------------------
# HanaService integration tests via mocked cursor (Phase 3 additions)
# ---------------------------------------------------------------------------


def _make_pool(pool_size: int = 3, pool_timeout: float = 1.0) -> HanaConnectionPool:
    """Create a HanaConnectionPool with test defaults."""
    return HanaConnectionPool(
        connection_params={"address": "localhost", "port": 30015},
        pool_size=pool_size,
        pool_timeout=pool_timeout,
    )


def _make_mock_connection() -> MagicMock:
    """Create a mock hdbcli connection with cursor support."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.description = None
    cursor.fetchall.return_value = []
    return conn


def _setup_cursor_responses(
    conn: MagicMock,
    responses: list[tuple[list[tuple[str, ...]] | None, list[tuple[Any, ...]]]],
) -> None:
    """Configure a mock connection's cursor for sequential responses.

    Each response is a tuple of (description, fetchall_result).
    """
    cursor = conn.cursor.return_value
    descriptions: list[Any] = []
    fetchall_results: list[Any] = []

    for desc, rows in responses:
        descriptions.append(desc)
        fetchall_results.append(rows)

    cursor.description = None
    _call_count = {"execute": 0}

    def execute_side_effect(*args: Any, **kwargs: Any) -> None:
        idx = _call_count["execute"]
        _call_count["execute"] = idx + 1
        if idx < len(descriptions):
            cursor.description = descriptions[idx]
        else:
            cursor.description = None

    cursor.execute = MagicMock(side_effect=execute_side_effect)
    cursor.fetchall = MagicMock(side_effect=fetchall_results)


class TestCalcViewsServiceIntegration:
    """Phase 3: HanaService calc view tests with mocked cursor data."""

    @pytest.mark.asyncio
    async def test_calc_views_with_all_types_and_columns(self) -> None:
        """Service returns views with full column metadata included."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Views: CALC and JOIN types
                (
                    None,
                    [
                        ("CV_SALES", "MY_SCHEMA", "CALC", "Sales view", "TRUE", 2),
                        ("CV_JOIN", "MY_SCHEMA", "JOIN", None, "TRUE", 1),
                    ],
                ),
                # Columns for CV_SALES
                (
                    None,
                    [
                        ("AMOUNT", "DECIMAL", "Total amount", "FALSE"),
                        ("REGION", "NVARCHAR", "Region name", "TRUE"),
                    ],
                ),
                # Columns for CV_JOIN
                (
                    None,
                    [
                        ("ID", "INTEGER", None, "FALSE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA", include_columns=True)

        assert not isinstance(result, ToolError)
        assert result.count == 2
        view_map = {v.name: v for v in result.views}
        assert len(view_map["CV_SALES"].columns) == 2
        assert view_map["CV_SALES"].columns[0].name == "AMOUNT"
        assert len(view_map["CV_JOIN"].columns) == 1

    @pytest.mark.asyncio
    async def test_calc_views_empty_schema_returns_zero_count(self) -> None:
        """Service returns count=0 and empty list for schema with no calc views."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("EMPTY_SCHEMA",)]),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("EMPTY_SCHEMA")

        assert not isinstance(result, ToolError)
        assert result.count == 0
        assert result.views == []
        assert result.schema_name == "EMPTY_SCHEMA"

    @pytest.mark.asyncio
    async def test_calc_view_privilege_note_constant_exists(self) -> None:
        """Verify analytic privilege note constant is defined in HanaService module."""
        assert CALC_VIEW_PRIVILEGE_NOTE is not None
        assert "analytic privileges" in CALC_VIEW_PRIVILEGE_NOTE.lower()
        assert "metadata visibility" in CALC_VIEW_PRIVILEGE_NOTE.lower()

    @pytest.mark.asyncio
    async def test_calc_views_inactive_view_detected(self) -> None:
        """Service correctly identifies inactive (invalid) calc views."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("CV_ACTIVE", "MY_SCHEMA", "CALC", None, "TRUE", 3),
                        ("CV_INACTIVE", "MY_SCHEMA", "CALC", None, "FALSE", 2),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA")

        assert not isinstance(result, ToolError)
        view_map = {v.name: v for v in result.views}
        assert view_map["CV_ACTIVE"].is_active is True
        assert view_map["CV_INACTIVE"].is_active is False


class TestStoreTypeServiceIntegration:
    """Phase 3: HanaService store type tests with mocked cursor data."""

    @pytest.mark.asyncio
    async def test_column_store_with_partitions_and_compression(self) -> None:
        """Service returns full column store details: partitions + compression."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Column store, partitioned, preload enabled
                (
                    None,
                    [
                        ("BIG_TABLE", "DW", "TRUE", "TRUE", "HASH 4", "TRUE"),
                    ],
                ),
                # Partition count
                (None, [(4,)]),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("DW", "BIG_TABLE")

        assert not isinstance(result, ToolError)
        info = result.store_info
        assert info.store_type == "COLUMN"
        assert info.is_column_table is True
        assert info.has_partitions is True
        assert info.partition_count == 4
        assert info.is_compressed is True
        assert info.implications == COLUMN_STORE_IMPLICATIONS

    @pytest.mark.asyncio
    async def test_row_store_detection(self) -> None:
        """Service correctly identifies row store tables."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),
                (
                    None,
                    [
                        ("SETTINGS", "ADMIN", "FALSE", "FALSE", None, "FALSE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("ADMIN", "SETTINGS")

        assert not isinstance(result, ToolError)
        info = result.store_info
        assert info.store_type == "ROW"
        assert info.is_column_table is False
        assert info.is_compressed is False
        assert info.has_partitions is False
        assert info.partition_count == 0
        assert info.implications == ROW_STORE_IMPLICATIONS

    @pytest.mark.asyncio
    async def test_view_passed_as_table_returns_parameter_error(self) -> None:
        """Service returns PARAMETER_ERROR when view is passed instead of table."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # It IS a view
                (None, [("REVENUE_VIEW",)]),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("SALES", "REVENUE_VIEW")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.PARAMETER_ERROR
        assert "view" in result.message.lower()
        assert result.suggestion is not None
        assert "describe_table" in result.suggestion

    @pytest.mark.asyncio
    async def test_table_not_found_returns_error_with_suggestions(self) -> None:
        """Service returns TABLE_NOT_FOUND with fuzzy name suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Table not found
                (None, []),
                # All objects for fuzzy matching
                (
                    None,
                    [
                        ("ORDERS",),
                        ("ORDERS_ARCHIVE",),
                        ("PRODUCTS",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("SALES", "ORDRS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        assert "ORDRS" in result.message
        assert result.context is not None
        assert "similar_tables" in result.context
        assert "ORDERS" in result.context["similar_tables"]


class TestProcedureServiceIntegration:
    """Phase 3: HanaService procedure tests with mocked cursor data."""

    @pytest.mark.asyncio
    async def test_procedures_all_types_sqlscript_r_l(self) -> None:
        """Service returns procedures of types SQLScript, R, and L."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("PROC_SQL", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 1),
                        ("PROC_R", "MY_SCHEMA", "R", "TRUE", 0),
                        ("PROC_L", "MY_SCHEMA", "L", "FALSE", 2),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA")

        assert not isinstance(result, ToolError)
        assert result.count == 3
        proc_map = {p.name: p for p in result.procedures}
        assert proc_map["PROC_SQL"].type == "SQLSCRIPT"
        assert proc_map["PROC_R"].type == "R"
        assert proc_map["PROC_L"].type == "L"
        assert proc_map["PROC_SQL"].is_read_only is True
        assert proc_map["PROC_L"].is_read_only is False

    @pytest.mark.asyncio
    async def test_procedures_empty_schema_returns_zero(self) -> None:
        """Service returns count=0 for schema with no procedures."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("EMPTY_SCHEMA",)]),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("EMPTY_SCHEMA")

        assert not isinstance(result, ToolError)
        assert result.count == 0
        assert result.procedures == []

    @pytest.mark.asyncio
    async def test_procedure_with_no_parameters_include_true(self) -> None:
        """Service returns empty parameters list when procedure has none."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("PROC_SIMPLE", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 0),
                    ],
                ),
                # No parameters
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert not isinstance(result, ToolError)
        proc = result.procedures[0]
        assert proc.parameter_count == 0
        assert proc.parameters == []

    @pytest.mark.asyncio
    async def test_procedure_mixed_direction_parameters(self) -> None:
        """Service returns IN, OUT, INOUT parameter directions correctly."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("PROC_MIX", "MY_SCHEMA", "SQLSCRIPT", "FALSE", 3),
                    ],
                ),
                # Parameters with all three directions
                (
                    None,
                    [
                        ("P_IN", "NVARCHAR", "IN", 1, None),
                        ("P_OUT", "INTEGER", "OUT", 2, None),
                        ("P_INOUT", "DECIMAL", "INOUT", 3, "'0.0'"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert not isinstance(result, ToolError)
        params = result.procedures[0].parameters
        assert len(params) == 3
        assert params[0].direction == "IN"
        assert params[0].name == "P_IN"
        assert params[1].direction == "OUT"
        assert params[1].name == "P_OUT"
        assert params[2].direction == "INOUT"
        assert params[2].default_value == "'0.0'"

    @pytest.mark.asyncio
    async def test_procedure_exclude_parameters(self) -> None:
        """Service returns empty parameters when include_parameters=False."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("PROC_WITH_PARAMS", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 5),
                    ],
                ),
                # No param query issued when include_parameters=False
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=False)

        assert not isinstance(result, ToolError)
        assert result.procedures[0].parameter_count == 5
        assert result.procedures[0].parameters == []


# ---------------------------------------------------------------------------
# Tool registration test
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests for HANA tool registration with FastMCP."""

    def test_hana_tools_are_registered_on_mcp(self) -> None:
        """All 3 HANA-specific tools are registered on the mcp server."""
        from mamba_mcp_hana.server import mcp as server

        tool_names = []
        for tool in server._tool_manager._tools.values():
            tool_names.append(tool.name)

        assert "list_calculation_views" in tool_names
        assert "get_table_store_type" in tool_names
        assert "list_procedures" in tool_names

    def test_total_tool_count_is_eleven(self) -> None:
        """Server has 11 total tools (8 core + 3 HANA)."""
        from mamba_mcp_hana.server import mcp as server

        tool_count = len(server._tool_manager._tools)
        assert tool_count == 11

    def test_hana_tools_have_docstrings(self) -> None:
        """Each HANA tool function has a non-empty docstring."""
        assert list_calculation_views.__doc__
        assert get_table_store_type.__doc__
        assert list_procedures.__doc__
