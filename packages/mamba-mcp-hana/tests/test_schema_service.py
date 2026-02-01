"""Tests for SchemaService Layer 1 database operations."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mamba_mcp_sap_hana.database.connection import HanaConnectionPool
from mamba_mcp_sap_hana.database.schema_service import SchemaService
from mamba_mcp_sap_hana.errors import ErrorCode, ToolError
from mamba_mcp_sap_hana.models.schema import (
    DescribeTableOutput,
    ListSchemasOutput,
    ListTablesOutput,
    SampleRowsOutput,
)


def _make_pool(pool_size: int = 3, pool_timeout: float = 1.0) -> HanaConnectionPool:
    """Create a HanaConnectionPool with test defaults."""
    return HanaConnectionPool(
        connection_params={"address": "localhost", "port": 30015},
        pool_size=pool_size,
        pool_timeout=pool_timeout,
    )


def _make_mock_connection() -> MagicMock:
    """Create a mock hdbcli connection with cursor support.

    Returns a mock connection where cursor().execute() and cursor().fetchall()
    can be controlled via side_effect patterns.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # Default: health check passes
    cursor.description = None
    cursor.fetchall.return_value = []
    return conn


def _setup_cursor_responses(
    conn: MagicMock,
    responses: list[tuple[list[tuple[str, ...]] | None, list[tuple[Any, ...]]]],
) -> None:
    """Configure a mock connection's cursor to return sequential responses.

    Each response is a tuple of (description, fetchall_result).
    description is a list of (column_name, ...) tuples or None.
    fetchall_result is the list of row tuples to return.

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


class TestSchemaServiceListSchemas:
    """Tests for SchemaService.list_schemas."""

    @pytest.mark.asyncio
    async def test_list_schemas_returns_user_schemas(self) -> None:
        """Test list_schemas filters out system schemas by default."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (
                    None,
                    [
                        ("MY_SCHEMA", "DBADMIN", 5),
                        ("SYS", "SYS", 100),
                        ("SYSTEM", "SYS", 50),
                        ("_SYS_BIC", "SYS", 10),
                        ("APP_SCHEMA", "APP_USER", 3),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_schemas(include_system=False)

        assert isinstance(result, ListSchemasOutput)
        assert result.count == 2
        names = [s.name for s in result.schemas]
        assert "MY_SCHEMA" in names
        assert "APP_SCHEMA" in names
        assert "SYS" not in names
        assert "SYSTEM" not in names
        assert "_SYS_BIC" not in names

    @pytest.mark.asyncio
    async def test_list_schemas_include_system(self) -> None:
        """Test list_schemas includes system schemas when requested."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (
                    None,
                    [
                        ("MY_SCHEMA", "DBADMIN", 5),
                        ("SYS", "SYS", 100),
                        ("SYSTEM", "SYS", 50),
                        ("_SYS_BIC", "SYS", 10),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_schemas(include_system=True)

        assert isinstance(result, ListSchemasOutput)
        assert result.count == 4
        names = [s.name for s in result.schemas]
        assert "SYS" in names
        assert "SYSTEM" in names
        assert "_SYS_BIC" in names

    @pytest.mark.asyncio
    async def test_list_schemas_is_system_flag(self) -> None:
        """Test that is_system flag is correctly set on each schema."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (
                    None,
                    [
                        ("MY_SCHEMA", "DBADMIN", 5),
                        ("SYS", "SYS", 100),
                        ("_SYS_REPO", "SYS", 10),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_schemas(include_system=True)

        assert isinstance(result, ListSchemasOutput)
        schema_map = {s.name: s for s in result.schemas}
        assert schema_map["MY_SCHEMA"].is_system is False
        assert schema_map["SYS"].is_system is True
        assert schema_map["_SYS_REPO"].is_system is True

    @pytest.mark.asyncio
    async def test_list_schemas_empty_result(self) -> None:
        """Test list_schemas returns empty list when no schemas found."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_schemas()

        assert isinstance(result, ListSchemasOutput)
        assert result.count == 0
        assert result.schemas == []

    @pytest.mark.asyncio
    async def test_list_schemas_connection_error(self) -> None:
        """Test list_schemas returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = SchemaService(pool)
            result = await service.list_schemas()

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "list_schemas"

    @pytest.mark.asyncio
    async def test_list_schemas_sql_error(self) -> None:
        """Test list_schemas returns ToolError on SQL execution failure."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = Exception("SQL error: insufficient privilege")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_schemas()

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert "SQL error" in result.message


class TestSchemaServiceListTables:
    """Tests for SchemaService.list_tables."""

    @pytest.mark.asyncio
    async def test_list_tables_with_views(self) -> None:
        """Test list_tables returns both tables and views."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists check
                (None, [("MY_SCHEMA",)]),
                # Tables query
                (
                    None,
                    [
                        ("USERS", "TABLE", 1000, 5, "COLUMN", "TRUE"),
                        ("ORDERS", "TABLE", 5000, 8, "COLUMN", "TRUE"),
                    ],
                ),
                # Views query
                (
                    None,
                    [
                        ("ACTIVE_USERS_VIEW", "VIEW", 0, 3),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA", include_views=True)

        assert isinstance(result, ListTablesOutput)
        assert result.count == 3
        assert result.schema_name == "MY_SCHEMA"
        names = [t.name for t in result.tables]
        assert "USERS" in names
        assert "ORDERS" in names
        assert "ACTIVE_USERS_VIEW" in names

    @pytest.mark.asyncio
    async def test_list_tables_without_views(self) -> None:
        """Test list_tables excludes views when include_views is False."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Schema exists check
                (None, [("MY_SCHEMA",)]),
                # Tables query
                (
                    None,
                    [
                        ("USERS", "TABLE", 1000, 5, "COLUMN", "TRUE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA", include_views=False)

        assert isinstance(result, ListTablesOutput)
        assert result.count == 1
        types = [t.type for t in result.tables]
        assert "VIEW" not in types

    @pytest.mark.asyncio
    async def test_list_tables_name_pattern_like(self) -> None:
        """Test list_tables filters by SQL LIKE pattern (USER%)."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("USERS", "TABLE", 1000, 5, "COLUMN", "TRUE"),
                        ("USER_ROLES", "TABLE", 100, 3, "COLUMN", "TRUE"),
                        ("ORDERS", "TABLE", 5000, 8, "COLUMN", "TRUE"),
                    ],
                ),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA", name_pattern="USER%")

        assert isinstance(result, ListTablesOutput)
        assert result.count == 2
        names = [t.name for t in result.tables]
        assert "USERS" in names
        assert "USER_ROLES" in names
        assert "ORDERS" not in names

    @pytest.mark.asyncio
    async def test_list_tables_name_pattern_glob(self) -> None:
        """Test list_tables handles glob-style pattern (*ROLE*)."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("USERS", "TABLE", 1000, 5, "COLUMN", "TRUE"),
                        ("USER_ROLES", "TABLE", 100, 3, "COLUMN", "TRUE"),
                        ("ROLE_PERMS", "TABLE", 200, 4, "COLUMN", "TRUE"),
                    ],
                ),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA", name_pattern="%ROLE%")

        assert isinstance(result, ListTablesOutput)
        assert result.count == 2
        names = [t.name for t in result.tables]
        assert "USER_ROLES" in names
        assert "ROLE_PERMS" in names

    @pytest.mark.asyncio
    async def test_list_tables_schema_not_found(self) -> None:
        """Test list_tables returns SCHEMA_NOT_FOUND with fuzzy suggestions."""
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
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.SCHEMA_NOT_FOUND
        assert "MY_SCHMA" in result.message
        assert result.context is not None
        assert "similar_schemas" in result.context
        assert "MY_SCHEMA" in result.context["similar_schemas"]

    @pytest.mark.asyncio
    async def test_list_tables_empty_schema(self) -> None:
        """Test list_tables returns empty list for schema with no tables."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("EMPTY_SCHEMA",)]),
                (None, []),  # No tables
                (None, []),  # No views
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("EMPTY_SCHEMA")

        assert isinstance(result, ListTablesOutput)
        assert result.count == 0
        assert result.tables == []

    @pytest.mark.asyncio
    async def test_list_tables_store_type(self) -> None:
        """Test list_tables correctly identifies column vs row store."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("COL_TABLE", "TABLE", 100, 3, "COLUMN", "TRUE"),
                        ("ROW_TABLE", "TABLE", 200, 4, "ROW", "FALSE"),
                    ],
                ),
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA")

        assert isinstance(result, ListTablesOutput)
        table_map = {t.name: t for t in result.tables}
        assert table_map["COL_TABLE"].store_type == "COLUMN"
        assert table_map["COL_TABLE"].is_column_table is True
        assert table_map["ROW_TABLE"].store_type == "ROW"
        assert table_map["ROW_TABLE"].is_column_table is False

    @pytest.mark.asyncio
    async def test_list_tables_view_store_type_none(self) -> None:
        """Test views have store_type=None and is_column_table=False."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (None, []),
                (None, [("MY_VIEW", "VIEW", 0, 5)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA")

        assert isinstance(result, ListTablesOutput)
        assert result.count == 1
        view = result.tables[0]
        assert view.name == "MY_VIEW"
        assert view.type == "VIEW"
        assert view.store_type is None
        assert view.is_column_table is False

    @pytest.mark.asyncio
    async def test_list_tables_connection_error(self) -> None:
        """Test list_tables returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "list_tables"

    @pytest.mark.asyncio
    async def test_list_tables_sorted_by_name(self) -> None:
        """Test list_tables returns tables sorted alphabetically."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("MY_SCHEMA",)]),
                (
                    None,
                    [
                        ("ZEBRA", "TABLE", 10, 2, "COLUMN", "TRUE"),
                        ("ALPHA", "TABLE", 20, 3, "COLUMN", "TRUE"),
                    ],
                ),
                (
                    None,
                    [
                        ("MIDDLE_VIEW", "VIEW", 0, 4),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("MY_SCHEMA")

        assert isinstance(result, ListTablesOutput)
        names = [t.name for t in result.tables]
        assert names == ["ALPHA", "MIDDLE_VIEW", "ZEBRA"]


class TestSchemaServiceDescribeTable:
    """Tests for SchemaService.describe_table."""

    @pytest.mark.asyncio
    async def test_describe_table_full(self) -> None:
        """Test describe_table returns columns, indexes, and constraints."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Table exists check
                (None, [("USERS",)]),
                # Columns
                (
                    None,
                    [
                        ("ID", "INTEGER", None, None, "FALSE", None, 1, None),
                        ("NAME", "NVARCHAR", 255, None, "TRUE", None, 2, "User name"),
                        ("EMAIL", "NVARCHAR", 320, None, "FALSE", None, 3, None),
                    ],
                ),
                # Indexes
                (
                    None,
                    [
                        ("IDX_EMAIL", "EMAIL", "UNIQUE", "CPBTREE"),
                    ],
                ),
                # Constraints
                (
                    None,
                    [
                        ("PK_USERS", "ID", "TRUE", "FALSE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "USERS")

        assert isinstance(result, DescribeTableOutput)
        assert result.table_name == "USERS"
        assert result.schema_name == "MY_SCHEMA"
        assert result.is_view is False
        assert len(result.columns) == 3

        # Column details
        id_col = result.columns[0]
        assert id_col.name == "ID"
        assert id_col.data_type == "INTEGER"
        assert id_col.nullable is False
        assert id_col.position == 1

        name_col = result.columns[1]
        assert name_col.name == "NAME"
        assert name_col.length == 255
        assert name_col.nullable is True
        assert name_col.comment == "User name"

        # Indexes
        assert len(result.indexes) == 1
        assert result.indexes[0].name == "IDX_EMAIL"
        assert result.indexes[0].columns == ["EMAIL"]
        assert result.indexes[0].is_unique is True

        # Constraints
        assert len(result.constraints) == 1
        assert result.constraints[0].name == "PK_USERS"
        assert result.constraints[0].constraint_type == "PRIMARY KEY"
        assert result.constraints[0].columns == ["ID"]

    @pytest.mark.asyncio
    async def test_describe_view_skips_indexes_constraints(self) -> None:
        """Test describe_table for a view: is_view=True, empty indexes/constraints."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Table does NOT exist
                (None, []),
                # View exists
                (None, [("ACTIVE_USERS",)]),
                # View columns
                (
                    None,
                    [
                        ("ID", "INTEGER", None, None, "FALSE", None, 1, None),
                        ("NAME", "NVARCHAR", 255, None, "TRUE", None, 2, None),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "ACTIVE_USERS")

        assert isinstance(result, DescribeTableOutput)
        assert result.is_view is True
        assert len(result.columns) == 2
        assert result.indexes == []
        assert result.constraints == []

    @pytest.mark.asyncio
    async def test_describe_table_not_found_fuzzy(self) -> None:
        """Test describe_table returns TABLE_NOT_FOUND with fuzzy suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Table does not exist
                (None, []),
                # View does not exist
                (None, []),
                # All tables/views for fuzzy matching
                (
                    None,
                    [
                        ("USERS",),
                        ("USER_ROLES",),
                        ("ORDERS",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "USRES")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        assert "USRES" in result.message
        assert result.context is not None
        assert "similar_tables" in result.context
        assert "USERS" in result.context["similar_tables"]

    @pytest.mark.asyncio
    async def test_describe_table_no_indexes(self) -> None:
        """Test describe_table with include_indexes=False."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("USERS",)]),
                # Columns
                (
                    None,
                    [
                        ("ID", "INTEGER", None, None, "FALSE", None, 1, None),
                    ],
                ),
                # Constraints (indexes skipped)
                (
                    None,
                    [
                        ("PK_USERS", "ID", "TRUE", "FALSE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "USERS", include_indexes=False)

        assert isinstance(result, DescribeTableOutput)
        assert result.indexes == []
        assert len(result.constraints) == 1

    @pytest.mark.asyncio
    async def test_describe_table_no_constraints(self) -> None:
        """Test describe_table with include_constraints=False."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("USERS",)]),
                # Columns
                (
                    None,
                    [
                        ("ID", "INTEGER", None, None, "FALSE", None, 1, None),
                    ],
                ),
                # Indexes (constraints skipped)
                (
                    None,
                    [
                        ("IDX_ID", "ID", "UNIQUE", "BTREE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "USERS", include_constraints=False)

        assert isinstance(result, DescribeTableOutput)
        assert len(result.indexes) == 1
        assert result.constraints == []

    @pytest.mark.asyncio
    async def test_describe_table_multi_column_index(self) -> None:
        """Test describe_table groups multi-column indexes correctly."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("ORDERS",)]),
                # Columns
                (
                    None,
                    [
                        ("ID", "INTEGER", None, None, "FALSE", None, 1, None),
                        ("USER_ID", "INTEGER", None, None, "FALSE", None, 2, None),
                        ("STATUS", "NVARCHAR", 50, None, "FALSE", None, 3, None),
                    ],
                ),
                # Indexes with multi-column composite
                (
                    None,
                    [
                        ("IDX_USER_STATUS", "USER_ID", "NOT UNIQUE", "CPBTREE"),
                        ("IDX_USER_STATUS", "STATUS", "NOT UNIQUE", "CPBTREE"),
                    ],
                ),
                # Constraints
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "ORDERS")

        assert isinstance(result, DescribeTableOutput)
        assert len(result.indexes) == 1
        idx = result.indexes[0]
        assert idx.name == "IDX_USER_STATUS"
        assert idx.columns == ["USER_ID", "STATUS"]
        assert idx.is_unique is False

    @pytest.mark.asyncio
    async def test_describe_table_connection_error(self) -> None:
        """Test describe_table returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "USERS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "describe_table"

    @pytest.mark.asyncio
    async def test_describe_table_multi_column_constraint(self) -> None:
        """Test describe_table groups multi-column constraints correctly."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("ORDERS",)]),
                (
                    None,
                    [
                        ("COL_A", "NVARCHAR", 50, None, "FALSE", None, 1, None),
                        ("COL_B", "NVARCHAR", 50, None, "FALSE", None, 2, None),
                    ],
                ),
                (None, []),
                (
                    None,
                    [
                        ("UQ_AB", "COL_A", "FALSE", "TRUE"),
                        ("UQ_AB", "COL_B", "FALSE", "TRUE"),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "ORDERS")

        assert isinstance(result, DescribeTableOutput)
        assert len(result.constraints) == 1
        c = result.constraints[0]
        assert c.name == "UQ_AB"
        assert c.constraint_type == "UNIQUE"
        assert c.columns == ["COL_A", "COL_B"]


class TestSchemaServiceGetSampleRows:
    """Tests for SchemaService.get_sample_rows."""

    @pytest.mark.asyncio
    async def test_get_sample_rows_basic(self) -> None:
        """Test get_sample_rows returns limited result set with column names."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                # Table exists
                (None, [("USERS",)]),
                # SELECT query
                (
                    [("ID",), ("NAME",), ("EMAIL",)],
                    [
                        (1, "Alice", "alice@example.com"),
                        (2, "Bob", "bob@example.com"),
                    ],
                ),
                # Total count
                (None, [(1000,)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows("MY_SCHEMA", "USERS", limit=5)

        assert isinstance(result, SampleRowsOutput)
        assert result.table_name == "USERS"
        assert result.schema_name == "MY_SCHEMA"
        assert result.columns == ["ID", "NAME", "EMAIL"]
        assert result.row_count == 2
        assert result.total_count == 1000
        assert len(result.rows) == 2
        assert result.rows[0]["ID"] == 1
        assert result.rows[0]["NAME"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_sample_rows_with_columns(self) -> None:
        """Test get_sample_rows with specific column selection."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("USERS",)]),
                (
                    [("ID",), ("NAME",)],
                    [(1, "Alice"), (2, "Bob")],
                ),
                (None, [(1000,)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows(
                "MY_SCHEMA",
                "USERS",
                columns=["ID", "NAME"],
            )

        assert isinstance(result, SampleRowsOutput)
        assert result.columns == ["ID", "NAME"]
        # Verify the query included quoted column names
        cursor = mock_conn.cursor.return_value
        calls = cursor.execute.call_args_list
        select_call = calls[1]  # Second call is the SELECT
        assert '"ID"' in select_call[0][0]
        assert '"NAME"' in select_call[0][0]

    @pytest.mark.asyncio
    async def test_get_sample_rows_empty_table(self) -> None:
        """Test get_sample_rows returns empty rows for empty table."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("EMPTY_TABLE",)]),
                ([], []),  # Empty result set
                (None, [(0,)]),  # Total count = 0
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows("MY_SCHEMA", "EMPTY_TABLE")

        assert isinstance(result, SampleRowsOutput)
        assert result.row_count == 0
        assert result.total_count == 0
        assert result.rows == []

    @pytest.mark.asyncio
    async def test_get_sample_rows_table_not_found(self) -> None:
        """Test get_sample_rows returns TABLE_NOT_FOUND with suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),  # Table not found
                (None, []),  # View not found
                (
                    None,
                    [("USERS",), ("USER_ROLES",), ("ORDERS",)],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows("MY_SCHEMA", "USRES")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        assert "USRES" in result.message
        assert result.context is not None
        assert "USERS" in result.context["similar_tables"]

    @pytest.mark.asyncio
    async def test_get_sample_rows_connection_error(self) -> None:
        """Test get_sample_rows returns ToolError on connection failure."""
        pool = _make_pool()

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows("MY_SCHEMA", "USERS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR
        assert result.tool_name == "get_sample_rows"

    @pytest.mark.asyncio
    async def test_get_sample_rows_from_view(self) -> None:
        """Test get_sample_rows works with views using COUNT(*)."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),  # Not a table
                (None, [("MY_VIEW",)]),  # Is a view
                (
                    [("COL_A",), ("COL_B",)],
                    [(1, "x"), (2, "y")],
                ),
                # Count query for view
                (None, [(42,)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows("MY_SCHEMA", "MY_VIEW")

        assert isinstance(result, SampleRowsOutput)
        assert result.row_count == 2
        assert result.total_count == 42

    @pytest.mark.asyncio
    async def test_get_sample_rows_with_where_clause(self) -> None:
        """Test get_sample_rows with WHERE clause filtering."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("USERS",)]),
                (
                    [("ID",), ("NAME",)],
                    [(1, "Alice")],
                ),
                (None, [(1000,)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows(
                "MY_SCHEMA",
                "USERS",
                where_clause="NAME = 'Alice'",
            )

        assert isinstance(result, SampleRowsOutput)
        # Verify WHERE clause was included in the query
        cursor = mock_conn.cursor.return_value
        calls = cursor.execute.call_args_list
        select_call = calls[1]
        assert "WHERE NAME = 'Alice'" in select_call[0][0]

    @pytest.mark.asyncio
    async def test_get_sample_rows_randomize(self) -> None:
        """Test get_sample_rows with randomize=True uses ORDER BY RAND()."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, [("USERS",)]),
                (
                    [("ID",)],
                    [(3,), (1,)],
                ),
                (None, [(1000,)]),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows(
                "MY_SCHEMA",
                "USERS",
                randomize=True,
            )

        assert isinstance(result, SampleRowsOutput)
        cursor = mock_conn.cursor.return_value
        calls = cursor.execute.call_args_list
        select_call = calls[1]
        assert "ORDER BY RAND()" in select_call[0][0]

    @pytest.mark.asyncio
    async def test_get_sample_rows_sql_error(self) -> None:
        """Test get_sample_rows returns ToolError on SQL execution failure."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        # First call (table exists check) succeeds, second (SELECT) fails
        call_count = {"n": 0}

        def execute_side_effect(*args: Any, **kwargs: Any) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                cursor.description = None
                return
            raise Exception("insufficient privilege")

        cursor.execute = MagicMock(side_effect=execute_side_effect)
        cursor.fetchall = MagicMock(return_value=[("USERS",)])

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.get_sample_rows("MY_SCHEMA", "USERS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR


class TestSchemaServiceFuzzyMatching:
    """Tests for fuzzy matching integration in service methods."""

    @pytest.mark.asyncio
    async def test_schema_fuzzy_match_with_suggestions(self) -> None:
        """Test fuzzy matching provides relevant schema suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),  # Schema not found
                (
                    None,
                    [
                        ("PRODUCTION",),
                        ("PRODUCTION_DEV",),
                        ("STAGING",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_tables("PRODUCTON")

        assert isinstance(result, ToolError)
        assert result.suggestion is not None
        assert "PRODUCTION" in result.suggestion

    @pytest.mark.asyncio
    async def test_table_fuzzy_match_with_suggestions(self) -> None:
        """Test fuzzy matching provides relevant table suggestions."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),  # Table not found
                (None, []),  # View not found
                (
                    None,
                    [
                        ("CUSTOMERS",),
                        ("CUSTOMER_ORDERS",),
                        ("PRODUCTS",),
                    ],
                ),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "CUSTMERS")

        assert isinstance(result, ToolError)
        assert result.suggestion is not None
        assert "CUSTOMERS" in result.suggestion

    @pytest.mark.asyncio
    async def test_no_fuzzy_suggestions_when_far(self) -> None:
        """Test no suggestions when all candidates are too far."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),  # Table not found
                (None, []),  # View not found
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
            service = SchemaService(pool)
            result = await service.describe_table("MY_SCHEMA", "XXXX")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        # No context when no similar names found
        assert result.context is None


class TestSchemaServiceConnectionRelease:
    """Tests verifying connections are always released."""

    @pytest.mark.asyncio
    async def test_connection_released_on_success(self) -> None:
        """Test connection is released back to pool after successful query."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                (None, []),
            ],
        )

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            await service.list_schemas()

        # Connection should be back in the pool
        assert pool.available_count == 1

    @pytest.mark.asyncio
    async def test_connection_released_on_error(self) -> None:
        """Test connection is released back to pool even on SQL errors."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = Exception("SQL error")

        with patch(
            "mamba_mcp_sap_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = SchemaService(pool)
            result = await service.list_schemas()

        assert isinstance(result, ToolError)
        # Connection should still be released
        assert pool.available_count == 1
