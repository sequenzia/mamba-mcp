"""Tests for HanaService Layer 4 HANA-specific database operations."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mamba_mcp_sap_hana.database.connection import HanaConnectionPool
from mamba_mcp_sap_hana.database.hana import HanaService
from mamba_mcp_sap_hana.errors import ErrorCode, ToolError
from mamba_mcp_sap_hana.models.hana import (
    GetTableStoreTypeOutput,
    ListCalcViewsOutput,
    ListProceduresOutput,
)


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
    """Configure a mock connection's cursor to return sequential responses.

    Each response is a tuple of (description, fetchall_result).
    The cursor executes will cycle through the responses in order.
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


# === Tests for list_calculation_views ===


class TestHanaServiceListCalcViews:
    """Tests for HanaService.list_calculation_views."""

    @pytest.mark.asyncio
    async def test_list_calc_views_basic(self) -> None:
        """Test list_calculation_views returns calc views from SYS.VIEWS."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists check
                (None, [("MY_SCHEMA",)]),
                # Calc views query
                (
                    None,
                    [
                        ("CV_SALES", "MY_SCHEMA", "CALC", "Sales calc view", "TRUE", 5),
                        ("CV_ORDERS", "MY_SCHEMA", "JOIN", None, "TRUE", 3),
                        ("CV_REVENUE", "MY_SCHEMA", "OLAP", "Revenue view", "FALSE", 8),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA")

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 3
        assert result.schema_name == "MY_SCHEMA"

        view_map = {v.name: v for v in result.views}
        assert "CV_SALES" in view_map
        assert view_map["CV_SALES"].type == "CALC"
        assert view_map["CV_SALES"].is_active is True
        assert view_map["CV_SALES"].column_count == 5
        assert view_map["CV_SALES"].description == "Sales calc view"

        assert view_map["CV_ORDERS"].type == "JOIN"
        assert view_map["CV_ORDERS"].is_active is True

        assert view_map["CV_REVENUE"].type == "OLAP"
        assert view_map["CV_REVENUE"].is_active is False
        assert view_map["CV_REVENUE"].column_count == 8

    @pytest.mark.asyncio
    async def test_list_calc_views_with_columns(self) -> None:
        """Test include_columns=True fetches column metadata for each view."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists check
                (None, [("MY_SCHEMA",)]),
                # Calc views query (one view)
                (
                    None,
                    [
                        ("CV_SALES", "MY_SCHEMA", "CALC", None, "TRUE", 2),
                    ],
                ),
                # Columns for CV_SALES
                (
                    None,
                    [
                        ("AMOUNT", "DECIMAL", "Sales amount", "TRUE"),
                        ("REGION", "NVARCHAR", "Sales region", "FALSE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA", include_columns=True)

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 1
        view = result.views[0]
        assert len(view.columns) == 2
        assert view.columns[0].name == "AMOUNT"
        assert view.columns[0].data_type == "DECIMAL"
        assert view.columns[0].description == "Sales amount"
        assert view.columns[1].name == "REGION"
        assert view.columns[1].data_type == "NVARCHAR"

    @pytest.mark.asyncio
    async def test_list_calc_views_without_columns(self) -> None:
        """Test include_columns=False does NOT fetch column metadata."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Calc views
                (
                    None,
                    [
                        ("CV_SALES", "MY_SCHEMA", "CALC", None, "TRUE", 3),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA", include_columns=False)

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 1
        assert result.views[0].columns == []

    @pytest.mark.asyncio
    async def test_list_calc_views_empty_schema(self) -> None:
        """Test empty list when schema has no calculation views."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("EMPTY_SCHEMA",)]),
                # No calc views
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("EMPTY_SCHEMA")

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 0
        assert result.views == []

    @pytest.mark.asyncio
    async def test_list_calc_views_name_pattern(self) -> None:
        """Test name pattern filtering for calc views."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Calc views
                (
                    None,
                    [
                        ("CV_SALES", "MY_SCHEMA", "CALC", None, "TRUE", 3),
                        ("CV_SALES_DAILY", "MY_SCHEMA", "CALC", None, "TRUE", 5),
                        ("CV_ORDERS", "MY_SCHEMA", "JOIN", None, "TRUE", 2),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA", name_pattern="CV_SALES%")

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 2
        names = [v.name for v in result.views]
        assert "CV_SALES" in names
        assert "CV_SALES_DAILY" in names
        assert "CV_ORDERS" not in names

    @pytest.mark.asyncio
    async def test_list_calc_views_schema_not_found(self) -> None:
        """Test SCHEMA_NOT_FOUND with fuzzy suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema does not exist
                (None, []),
                # All schemas for fuzzy matching
                (
                    None,
                    [
                        ("MY_SCHEMA",),
                        ("MY_SCHEMA_DEV",),
                        ("OTHER_SCHEMA",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.SCHEMA_NOT_FOUND
        assert "MY_SCHMA" in result.message
        assert result.context is not None
        assert "similar_schemas" in result.context
        assert "MY_SCHEMA" in result.context["similar_schemas"]

    @pytest.mark.asyncio
    async def test_list_calc_views_connection_error(self) -> None:
        """Test list_calculation_views returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "list_calculation_views"

    @pytest.mark.asyncio
    async def test_list_calc_views_sql_error(self) -> None:
        """Test list_calculation_views returns ToolError on SQL failure."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = Exception("insufficient privilege")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert "insufficient privilege" in result.message

    @pytest.mark.asyncio
    async def test_list_calc_views_multiple_views_with_columns(self) -> None:
        """Test fetching columns for multiple views."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Two calc views
                (
                    None,
                    [
                        ("CV_A", "MY_SCHEMA", "CALC", None, "TRUE", 1),
                        ("CV_B", "MY_SCHEMA", "JOIN", None, "TRUE", 2),
                    ],
                ),
                # Columns for CV_A
                (
                    None,
                    [
                        ("COL_A1", "INTEGER", None, "FALSE"),
                    ],
                ),
                # Columns for CV_B
                (
                    None,
                    [
                        ("COL_B1", "NVARCHAR", None, "TRUE"),
                        ("COL_B2", "DECIMAL", None, "FALSE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA", include_columns=True)

        assert isinstance(result, ListCalcViewsOutput)
        assert result.count == 2
        view_map = {v.name: v for v in result.views}
        assert len(view_map["CV_A"].columns) == 1
        assert view_map["CV_A"].columns[0].name == "COL_A1"
        assert len(view_map["CV_B"].columns) == 2


# === Tests for get_table_store_type ===


class TestHanaServiceGetTableStoreType:
    """Tests for HanaService.get_table_store_type."""

    @pytest.mark.asyncio
    async def test_column_store_table(self) -> None:
        """Test COLUMN store type detection with metadata."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Table store type query
                (
                    None,
                    [
                        (
                            "SALES",
                            "MY_SCHEMA",
                            "TRUE",  # IS_COLUMN_TABLE
                            "TRUE",  # HAS_PARTITIONS
                            "RANGE",  # PARTITION_SPEC
                            "TRUE",  # IS_PRELOAD (compression indicator)
                        ),
                    ],
                ),
                # Partition count
                (None, [(4,)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "SALES")

        assert isinstance(result, GetTableStoreTypeOutput)
        info = result.store_info
        assert info.store_type == "COLUMN"
        assert info.is_column_table is True
        assert info.has_partitions is True
        assert info.partition_count == 4
        assert info.is_compressed is True
        assert "Column store" in info.implications
        assert "analytical" in info.implications

    @pytest.mark.asyncio
    async def test_row_store_table(self) -> None:
        """Test ROW store type detection."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Table store type query
                (
                    None,
                    [
                        (
                            "CONFIG",
                            "MY_SCHEMA",
                            "FALSE",  # IS_COLUMN_TABLE
                            "FALSE",  # HAS_PARTITIONS
                            None,  # PARTITION_SPEC
                            "FALSE",  # IS_PRELOAD
                        ),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "CONFIG")

        assert isinstance(result, GetTableStoreTypeOutput)
        info = result.store_info
        assert info.store_type == "ROW"
        assert info.is_column_table is False
        assert info.has_partitions is False
        assert info.partition_count == 0
        assert info.is_compressed is False
        assert "Row store" in info.implications
        assert "point lookups" in info.implications

    @pytest.mark.asyncio
    async def test_table_not_found(self) -> None:
        """Test TABLE_NOT_FOUND error with fuzzy suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Table not found in SYS.TABLES
                (None, []),
                # All objects for fuzzy matching
                (
                    None,
                    [
                        ("SALES",),
                        ("SALES_DAILY",),
                        ("ORDERS",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "SAELS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        assert "SAELS" in result.message
        assert result.context is not None
        assert "similar_tables" in result.context
        assert "SALES" in result.context["similar_tables"]

    @pytest.mark.asyncio
    async def test_view_not_a_table(self) -> None:
        """Test informative error when a view is passed instead of a table."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Is a view
                (None, [("MY_VIEW",)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "MY_VIEW")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.PARAMETER_ERROR
        assert "view" in result.message.lower()
        assert "store type" in result.message.lower()
        assert result.suggestion is not None
        assert "describe_table" in result.suggestion

    @pytest.mark.asyncio
    async def test_column_store_no_partitions(self) -> None:
        """Test column store table without partitions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Table store type
                (
                    None,
                    [
                        (
                            "SMALL_TABLE",
                            "MY_SCHEMA",
                            "TRUE",  # IS_COLUMN_TABLE
                            "FALSE",  # HAS_PARTITIONS
                            None,  # PARTITION_SPEC
                            "FALSE",  # IS_PRELOAD
                        ),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "SMALL_TABLE")

        assert isinstance(result, GetTableStoreTypeOutput)
        info = result.store_info
        assert info.store_type == "COLUMN"
        assert info.has_partitions is False
        assert info.partition_count == 0

    @pytest.mark.asyncio
    async def test_store_type_connection_error(self) -> None:
        """Test get_table_store_type returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "SALES")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "get_table_store_type"

    @pytest.mark.asyncio
    async def test_store_type_sql_error(self) -> None:
        """Test get_table_store_type returns ToolError on SQL failure."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = Exception("insufficient privilege")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "SALES")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert "insufficient privilege" in result.message

    @pytest.mark.asyncio
    async def test_store_type_implications_text(self) -> None:
        """Test implications text is correct for column and row store."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        # Column store
        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),
                (
                    None,
                    [("T1", "S1", "TRUE", "FALSE", None, "FALSE")],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("S1", "T1")

        assert isinstance(result, GetTableStoreTypeOutput)
        assert "foreign key" in result.store_info.implications.lower()
        assert "analytical" in result.store_info.implications.lower()

    @pytest.mark.asyncio
    async def test_table_not_found_no_suggestions(self) -> None:
        """Test TABLE_NOT_FOUND when no fuzzy matches exist."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Not a view
                (None, []),
                # Table not found
                (None, []),
                # No similar names
                (
                    None,
                    [
                        ("AAAA",),
                        ("BBBB",),
                        ("CCCC",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.get_table_store_type("MY_SCHEMA", "XXXX")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        assert result.context is None


# === Tests for list_procedures ===


class TestHanaServiceListProcedures:
    """Tests for HanaService.list_procedures."""

    @pytest.mark.asyncio
    async def test_list_procedures_basic(self) -> None:
        """Test list_procedures returns procedures with metadata."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedures query
                (
                    None,
                    [
                        ("PROC_REPORT", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 3),
                        ("PROC_LOAD", "MY_SCHEMA", "SQLSCRIPT", "FALSE", 1),
                        ("PROC_ANALYZE", "MY_SCHEMA", "R", "TRUE", 0),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA")

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 3
        assert result.schema_name == "MY_SCHEMA"

        proc_map = {p.name: p for p in result.procedures}
        assert proc_map["PROC_REPORT"].type == "SQLSCRIPT"
        assert proc_map["PROC_REPORT"].is_read_only is True
        assert proc_map["PROC_REPORT"].parameter_count == 3

        assert proc_map["PROC_LOAD"].is_read_only is False
        assert proc_map["PROC_LOAD"].parameter_count == 1

        assert proc_map["PROC_ANALYZE"].type == "R"
        assert proc_map["PROC_ANALYZE"].parameter_count == 0

    @pytest.mark.asyncio
    async def test_list_procedures_with_parameters(self) -> None:
        """Test include_parameters=True fetches parameter details."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedures query (one procedure)
                (
                    None,
                    [
                        ("PROC_REPORT", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 2),
                    ],
                ),
                # Parameters for PROC_REPORT
                (
                    None,
                    [
                        ("P_SCHEMA", "NVARCHAR", "IN", 1, None),
                        ("P_RESULT", "TABLE", "OUT", 2, None),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 1
        proc = result.procedures[0]
        assert len(proc.parameters) == 2
        assert proc.parameters[0].name == "P_SCHEMA"
        assert proc.parameters[0].data_type == "NVARCHAR"
        assert proc.parameters[0].direction == "IN"
        assert proc.parameters[0].position == 1
        assert proc.parameters[1].name == "P_RESULT"
        assert proc.parameters[1].direction == "OUT"

    @pytest.mark.asyncio
    async def test_list_procedures_without_parameters(self) -> None:
        """Test include_parameters=False does NOT fetch parameter details."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedures
                (
                    None,
                    [
                        ("PROC_A", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 2),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=False)

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 1
        assert result.procedures[0].parameters == []

    @pytest.mark.asyncio
    async def test_list_procedures_empty_schema(self) -> None:
        """Test empty list when schema has no procedures."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("EMPTY_SCHEMA",)]),
                # No procedures
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("EMPTY_SCHEMA")

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 0
        assert result.procedures == []

    @pytest.mark.asyncio
    async def test_list_procedures_no_parameters_procedure(self) -> None:
        """Test procedure with zero parameters returns empty parameter list."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedure with 0 parameters
                (
                    None,
                    [
                        ("PROC_NO_ARGS", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 0),
                    ],
                ),
                # Empty parameters result
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 1
        assert result.procedures[0].parameter_count == 0
        assert result.procedures[0].parameters == []

    @pytest.mark.asyncio
    async def test_list_procedures_name_pattern(self) -> None:
        """Test name pattern filtering for procedures."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedures
                (
                    None,
                    [
                        ("PROC_REPORT_DAILY", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 1),
                        ("PROC_REPORT_MONTHLY", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 2),
                        ("PROC_LOAD_DATA", "MY_SCHEMA", "SQLSCRIPT", "FALSE", 3),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", name_pattern="PROC_REPORT%")

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 2
        names = [p.name for p in result.procedures]
        assert "PROC_REPORT_DAILY" in names
        assert "PROC_REPORT_MONTHLY" in names
        assert "PROC_LOAD_DATA" not in names

    @pytest.mark.asyncio
    async def test_list_procedures_schema_not_found(self) -> None:
        """Test SCHEMA_NOT_FOUND with fuzzy suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema does not exist
                (None, []),
                # All schemas for fuzzy matching
                (
                    None,
                    [
                        ("MY_SCHEMA",),
                        ("MY_SCHEMA_DEV",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.SCHEMA_NOT_FOUND
        assert "MY_SCHMA" in result.message
        assert result.tool_name == "list_procedures"

    @pytest.mark.asyncio
    async def test_list_procedures_connection_error(self) -> None:
        """Test list_procedures returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "list_procedures"

    @pytest.mark.asyncio
    async def test_list_procedures_sql_error(self) -> None:
        """Test list_procedures returns ToolError on SQL failure."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = Exception("insufficient privilege")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert "insufficient privilege" in result.message

    @pytest.mark.asyncio
    async def test_list_procedures_inout_parameter(self) -> None:
        """Test procedure with INOUT parameter direction."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedure with INOUT
                (
                    None,
                    [
                        ("PROC_SWAP", "MY_SCHEMA", "SQLSCRIPT", "FALSE", 1),
                    ],
                ),
                # Parameters
                (
                    None,
                    [
                        ("P_VALUE", "INTEGER", "INOUT", 1, None),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert isinstance(result, ListProceduresOutput)
        assert result.procedures[0].parameters[0].direction == "INOUT"

    @pytest.mark.asyncio
    async def test_list_procedures_multiple_with_parameters(self) -> None:
        """Test fetching parameters for multiple procedures."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Two procedures
                (
                    None,
                    [
                        ("PROC_A", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 1),
                        ("PROC_B", "MY_SCHEMA", "L", "FALSE", 2),
                    ],
                ),
                # Params for PROC_A
                (
                    None,
                    [
                        ("P_INPUT", "NVARCHAR", "IN", 1, "'default'"),
                    ],
                ),
                # Params for PROC_B
                (
                    None,
                    [
                        ("P_X", "INTEGER", "IN", 1, None),
                        ("P_Y", "INTEGER", "OUT", 2, None),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert isinstance(result, ListProceduresOutput)
        assert result.count == 2
        proc_map = {p.name: p for p in result.procedures}
        assert len(proc_map["PROC_A"].parameters) == 1
        assert proc_map["PROC_A"].parameters[0].default_value == "'default'"
        assert len(proc_map["PROC_B"].parameters) == 2
        assert proc_map["PROC_B"].type == "L"

    @pytest.mark.asyncio
    async def test_list_procedures_parameter_default_values(self) -> None:
        """Test that parameter default values are captured."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists
                (None, [("MY_SCHEMA",)]),
                # Procedure
                (
                    None,
                    [
                        ("PROC_WITH_DEFAULTS", "MY_SCHEMA", "SQLSCRIPT", "TRUE", 2),
                    ],
                ),
                # Parameters with default values
                (
                    None,
                    [
                        ("P_LIMIT", "INTEGER", "IN", 1, "100"),
                        ("P_NAME", "NVARCHAR", "IN", 2, None),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_procedures("MY_SCHEMA", include_parameters=True)

        assert isinstance(result, ListProceduresOutput)
        params = result.procedures[0].parameters
        assert params[0].default_value == "100"
        assert params[1].default_value is None


# === Tests for connection release ===


class TestHanaServiceConnectionRelease:
    """Tests verifying connections are always released."""

    @pytest.mark.asyncio
    async def test_connection_released_on_calc_view_success(self) -> None:
        """Test connection is released after successful calc view query."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            await service.list_calculation_views("MY_SCHEMA")

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_connection_released_on_store_type_success(self) -> None:
        """Test connection is released after successful store type query."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),
                (None, [("T1", "S1", "TRUE", "FALSE", None, "FALSE")]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            await service.get_table_store_type("S1", "T1")

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_connection_released_on_procedure_success(self) -> None:
        """Test connection is released after successful procedure query."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            await service.list_procedures("MY_SCHEMA")

        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_connection_released_on_error(self) -> None:
        """Test connection is released even on SQL errors."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = Exception("SQL error")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = HanaService(pool)
            result = await service.list_calculation_views("MY_SCHEMA")

        assert isinstance(result, ToolError)
        assert pool.available_count == 1


# === Tests for asyncio.to_thread usage ===


class TestHanaServiceAsyncToThread:
    """Tests verifying all methods use asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_calc_views_uses_to_thread(self) -> None:
        """Test list_calculation_views uses asyncio.to_thread for DB calls."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (None, []),
            ],
        )

        with (
            patch(
                "mamba_mcp_sap_hana.database.connection._create_connection",
                return_value=mock_conn,
            ),
            patch(
                "mamba_mcp_sap_hana.database.hana.asyncio.to_thread",
                wraps=asyncio.to_thread,
            ) as mock_to_thread,
        ):
            service = HanaService(pool)
            await service.list_calculation_views("MY_SCHEMA")

        # At least 2 calls: schema check + views query
        assert mock_to_thread.call_count >= 2

    @pytest.mark.asyncio
    async def test_store_type_uses_to_thread(self) -> None:
        """Test get_table_store_type uses asyncio.to_thread for DB calls."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),
                (None, [("T1", "S1", "TRUE", "FALSE", None, "FALSE")]),
            ],
        )

        with (
            patch(
                "mamba_mcp_sap_hana.database.connection._create_connection",
                return_value=mock_conn,
            ),
            patch(
                "mamba_mcp_sap_hana.database.hana.asyncio.to_thread",
                wraps=asyncio.to_thread,
            ) as mock_to_thread,
        ):
            service = HanaService(pool)
            await service.get_table_store_type("S1", "T1")

        # At least 2 calls: view check + table query
        assert mock_to_thread.call_count >= 2

    @pytest.mark.asyncio
    async def test_procedures_uses_to_thread(self) -> None:
        """Test list_procedures uses asyncio.to_thread for DB calls."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (None, []),
            ],
        )

        with (
            patch(
                "mamba_mcp_sap_hana.database.connection._create_connection",
                return_value=mock_conn,
            ),
            patch(
                "mamba_mcp_sap_hana.database.hana.asyncio.to_thread",
                wraps=asyncio.to_thread,
            ) as mock_to_thread,
        ):
            service = HanaService(pool)
            await service.list_procedures("MY_SCHEMA")

        # At least 2 calls: schema check + procedures query
        assert mock_to_thread.call_count >= 2
