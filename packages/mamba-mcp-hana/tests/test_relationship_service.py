"""Tests for the RelationshipService (Layer 2 database operations)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mamba_mcp_hana.database.connection import HanaConnectionPool
from mamba_mcp_hana.database.relationship_service import (
    RelationshipService,
    _bfs_find_paths,
    _build_fk_graph,
    _generate_sql_join,
    _group_fk_rows,
    _path_to_join_steps,
)
from mamba_mcp_hana.errors import ErrorCode, ToolError
from mamba_mcp_hana.models.relationships import (
    FindJoinPathOutput,
    ForeignKeysOutput,
    JoinPath,
)

# --- Test Helpers ---


def _make_pool(
    pool_size: int = 3,
    pool_timeout: float = 1.0,
) -> HanaConnectionPool:
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
    return conn


def _setup_cursor_responses(
    mock_conn: MagicMock,
    responses: list[list[tuple[Any, ...]]],
) -> None:
    """Configure mock cursor to return different results for sequential queries.

    Args:
        mock_conn: Mock connection object.
        responses: List of result sets (each a list of tuples) for sequential calls.
    """
    cursor = mock_conn.cursor.return_value
    cursor.fetchall.side_effect = responses


# --- Sample FK Data Fixtures ---


def _outgoing_fk_rows() -> list[tuple[Any, ...]]:
    """Sample outgoing FK rows for ORDERS -> CUSTOMERS."""
    return [
        # constraint_name, source_schema, source_table, source_column,
        # target_schema, target_table, target_column, delete_rule
        (
            "FK_ORDERS_CUSTOMER",
            "SALES",
            "ORDERS",
            "CUSTOMER_ID",
            "SALES",
            "CUSTOMERS",
            "ID",
            "CASCADE",
        ),
    ]


def _incoming_fk_rows() -> list[tuple[Any, ...]]:
    """Sample incoming FK rows for CUSTOMERS <- ORDER_ITEMS."""
    return [
        ("FK_ITEMS_ORDER", "SALES", "ORDER_ITEMS", "ORDER_ID", "SALES", "ORDERS", "ID", "CASCADE"),
    ]


def _composite_fk_rows() -> list[tuple[Any, ...]]:
    """Sample composite FK rows (multi-column FK)."""
    return [
        (
            "FK_SHIPMENTS_ADDR",
            "SALES",
            "SHIPMENTS",
            "COUNTRY_CODE",
            "MASTER",
            "ADDRESSES",
            "COUNTRY",
            "RESTRICT",
        ),
        (
            "FK_SHIPMENTS_ADDR",
            "SALES",
            "SHIPMENTS",
            "POSTAL_CODE",
            "MASTER",
            "ADDRESSES",
            "POSTAL",
            "RESTRICT",
        ),
    ]


def _self_referencing_fk_rows() -> list[tuple[Any, ...]]:
    """Sample self-referencing FK rows (EMPLOYEES -> EMPLOYEES).

    8-column format matching OUTGOING_FK_SQL / INCOMING_FK_SQL result shape.
    """
    return [
        ("FK_EMP_MANAGER", "HR", "EMPLOYEES", "MANAGER_ID", "HR", "EMPLOYEES", "ID", "SET NULL"),
    ]


# --- 7-column graph fixtures (matching ALL_FK_SQL result shape, no DELETE_RULE) ---


def _graph_fk_rows() -> list[tuple[Any, ...]]:
    """FK rows for a graph: ORDERS -> CUSTOMERS, ORDER_ITEMS -> ORDERS.

    7-column format matching ALL_FK_SQL result shape.
    """
    return [
        # ORDERS -> CUSTOMERS
        ("FK_ORDERS_CUST", "SALES", "ORDERS", "CUSTOMER_ID", "SALES", "CUSTOMERS", "ID"),
        # ORDER_ITEMS -> ORDERS
        ("FK_ITEMS_ORDER", "SALES", "ORDER_ITEMS", "ORDER_ID", "SALES", "ORDERS", "ID"),
    ]


def _self_ref_graph_fk_rows() -> list[tuple[Any, ...]]:
    """Self-referencing FK rows in 7-column graph format (for BFS tests)."""
    return [
        ("FK_EMP_MANAGER", "HR", "EMPLOYEES", "MANAGER_ID", "HR", "EMPLOYEES", "ID"),
    ]


def _complex_graph_fk_rows() -> list[tuple[Any, ...]]:
    """FK rows for a complex graph with multiple paths.

    7-column format matching ALL_FK_SQL result shape.

    ORDER_ITEMS -> ORDERS -> CUSTOMERS
    ORDER_ITEMS -> PRODUCTS -> CATEGORIES
    PRODUCTS -> SUPPLIERS
    """
    return [
        ("FK_ITEMS_ORDER", "SALES", "ORDER_ITEMS", "ORDER_ID", "SALES", "ORDERS", "ID"),
        ("FK_ORDERS_CUST", "SALES", "ORDERS", "CUSTOMER_ID", "SALES", "CUSTOMERS", "ID"),
        ("FK_ITEMS_PROD", "SALES", "ORDER_ITEMS", "PRODUCT_ID", "SALES", "PRODUCTS", "ID"),
        ("FK_PROD_CAT", "SALES", "PRODUCTS", "CATEGORY_ID", "SALES", "CATEGORIES", "ID"),
        ("FK_PROD_SUPP", "SALES", "PRODUCTS", "SUPPLIER_ID", "SALES", "SUPPLIERS", "ID"),
    ]


def _cross_schema_fk_rows() -> list[tuple[Any, ...]]:
    """FK rows that span schemas: SALES.ORDERS -> MASTER.CUSTOMERS.

    7-column format matching ALL_FK_SQL result shape.
    """
    return [
        ("FK_ORDERS_CUST", "SALES", "ORDERS", "CUSTOMER_ID", "MASTER", "CUSTOMERS", "ID"),
    ]


# ==========================================================================
# Unit Tests: _group_fk_rows
# ==========================================================================


class TestGroupFkRows:
    """Tests for grouping FK rows into ForeignKeyInfo models."""

    def test_single_fk(self) -> None:
        """Test grouping a single-column FK."""
        rows = _outgoing_fk_rows()
        result = _group_fk_rows(rows)

        assert len(result) == 1
        fk = result[0]
        assert fk.constraint_name == "FK_ORDERS_CUSTOMER"
        assert fk.source_schema == "SALES"
        assert fk.source_table == "ORDERS"
        assert fk.source_columns == ["CUSTOMER_ID"]
        assert fk.target_schema == "SALES"
        assert fk.target_table == "CUSTOMERS"
        assert fk.target_columns == ["ID"]
        assert fk.delete_rule == "CASCADE"

    def test_composite_fk(self) -> None:
        """Test grouping a composite (multi-column) FK."""
        rows = _composite_fk_rows()
        result = _group_fk_rows(rows)

        assert len(result) == 1
        fk = result[0]
        assert fk.constraint_name == "FK_SHIPMENTS_ADDR"
        assert fk.source_columns == ["COUNTRY_CODE", "POSTAL_CODE"]
        assert fk.target_columns == ["COUNTRY", "POSTAL"]
        assert fk.delete_rule == "RESTRICT"

    def test_multiple_fks(self) -> None:
        """Test grouping multiple FKs into separate models."""
        rows = _outgoing_fk_rows() + _incoming_fk_rows()
        result = _group_fk_rows(rows)

        assert len(result) == 2
        names = {fk.constraint_name for fk in result}
        assert names == {"FK_ORDERS_CUSTOMER", "FK_ITEMS_ORDER"}

    def test_empty_rows(self) -> None:
        """Test grouping with no FK rows."""
        result = _group_fk_rows([])
        assert result == []

    def test_self_referencing_fk(self) -> None:
        """Test grouping a self-referencing FK."""
        rows = _self_referencing_fk_rows()
        result = _group_fk_rows(rows)

        assert len(result) == 1
        fk = result[0]
        assert fk.source_table == "EMPLOYEES"
        assert fk.target_table == "EMPLOYEES"
        assert fk.source_columns == ["MANAGER_ID"]
        assert fk.target_columns == ["ID"]

    def test_delete_rule_default(self) -> None:
        """Test that None delete_rule defaults to RESTRICT."""
        rows = [
            ("FK_TEST", "S", "T1", "C1", "S", "T2", "C2", None),
        ]
        result = _group_fk_rows(rows)
        assert result[0].delete_rule == "RESTRICT"


# ==========================================================================
# Unit Tests: _build_fk_graph
# ==========================================================================


class TestBuildFkGraph:
    """Tests for building FK edge graph."""

    def test_basic_graph(self) -> None:
        """Test building a graph from simple FK rows."""
        rows = _graph_fk_rows()
        edges = _build_fk_graph(rows)

        assert len(edges) == 2
        sources = {e["source"] for e in edges}
        assert "SALES.ORDERS" in sources
        assert "SALES.ORDER_ITEMS" in sources

    def test_composite_fk_single_edge(self) -> None:
        """Test that composite FK produces a single edge with multiple columns."""
        rows = [
            ("FK_COMP", "S", "T1", "C1", "S", "T2", "D1"),
            ("FK_COMP", "S", "T1", "C2", "S", "T2", "D2"),
        ]
        edges = _build_fk_graph(rows)

        assert len(edges) == 1
        assert edges[0]["source_columns"] == ["C1", "C2"]
        assert edges[0]["target_columns"] == ["D1", "D2"]

    def test_empty_rows(self) -> None:
        """Test building graph from empty rows."""
        edges = _build_fk_graph([])
        assert edges == []

    def test_cross_schema_edges(self) -> None:
        """Test edges crossing schema boundaries."""
        rows = _cross_schema_fk_rows()
        edges = _build_fk_graph(rows)

        assert len(edges) == 1
        assert edges[0]["source"] == "SALES.ORDERS"
        assert edges[0]["target"] == "MASTER.CUSTOMERS"


# ==========================================================================
# Unit Tests: _bfs_find_paths
# ==========================================================================


class TestBfsFindPaths:
    """Tests for BFS pathfinding."""

    def _make_edges(self, fk_rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        """Helper to build edges from FK rows."""
        return _build_fk_graph(fk_rows)

    def test_direct_path(self) -> None:
        """Test finding a direct (1-hop) path."""
        edges = self._make_edges(_graph_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDERS", "SALES.CUSTOMERS", max_depth=4)

        assert len(paths) >= 1
        # Shortest path should be 1 hop
        assert len(paths[0]) == 1

    def test_two_hop_path(self) -> None:
        """Test finding a 2-hop path: ORDER_ITEMS -> ORDERS -> CUSTOMERS."""
        edges = self._make_edges(_graph_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDER_ITEMS", "SALES.CUSTOMERS", max_depth=4)

        assert len(paths) >= 1
        assert len(paths[0]) == 2

    def test_same_start_and_end(self) -> None:
        """Test that same start/end returns empty paths."""
        edges = self._make_edges(_graph_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDERS", "SALES.ORDERS", max_depth=4)
        assert paths == []

    def test_no_path_exists(self) -> None:
        """Test when no path exists between disconnected tables."""
        edges = self._make_edges(_graph_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDER_ITEMS", "OTHER.UNRELATED", max_depth=4)
        assert paths == []

    def test_max_depth_limits_search(self) -> None:
        """Test that max_depth=1 only returns direct relationships."""
        edges = self._make_edges(_graph_fk_rows())
        # ORDER_ITEMS -> CUSTOMERS is 2 hops, should not be found with max_depth=1
        paths = _bfs_find_paths(edges, "SALES.ORDER_ITEMS", "SALES.CUSTOMERS", max_depth=1)
        assert paths == []

    def test_max_depth_allows_direct(self) -> None:
        """Test that max_depth=1 returns direct (1-hop) relationships."""
        edges = self._make_edges(_graph_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDERS", "SALES.CUSTOMERS", max_depth=1)
        assert len(paths) >= 1
        assert len(paths[0]) == 1

    def test_paths_sorted_by_length(self) -> None:
        """Test that paths are sorted shortest first."""
        edges = self._make_edges(_complex_graph_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDER_ITEMS", "SALES.CATEGORIES", max_depth=4)

        if len(paths) > 1:
            for i in range(len(paths) - 1):
                assert len(paths[i]) <= len(paths[i + 1])

    def test_bidirectional_traversal(self) -> None:
        """Test that BFS traverses in both FK directions."""
        edges = self._make_edges(_graph_fk_rows())
        # CUSTOMERS -> ORDERS: traverses incoming direction (reverse of ORDERS->CUSTOMERS FK)
        paths = _bfs_find_paths(edges, "SALES.CUSTOMERS", "SALES.ORDERS", max_depth=4)
        assert len(paths) >= 1

    def test_cross_schema_path(self) -> None:
        """Test path finding across schemas."""
        edges = self._make_edges(_cross_schema_fk_rows())
        paths = _bfs_find_paths(edges, "SALES.ORDERS", "MASTER.CUSTOMERS", max_depth=4)
        assert len(paths) >= 1

    def test_self_referencing_table(self) -> None:
        """Test handling of self-referencing FK (should not cause infinite loop)."""
        edges = self._make_edges(_self_ref_graph_fk_rows())
        # Self-referencing: same start and end returns empty (handled at top)
        paths = _bfs_find_paths(edges, "HR.EMPLOYEES", "HR.EMPLOYEES", max_depth=4)
        assert paths == []

    def test_empty_graph(self) -> None:
        """Test BFS on an empty graph."""
        paths = _bfs_find_paths([], "A.B", "C.D", max_depth=4)
        assert paths == []


# ==========================================================================
# Unit Tests: _generate_sql_join
# ==========================================================================


class TestGenerateSqlJoin:
    """Tests for SQL JOIN clause generation."""

    def test_single_join(self) -> None:
        """Test generating SQL for a single join step."""
        path = [
            {
                "from_schema": "SALES",
                "from_table": "ORDERS",
                "from_columns": ["CUSTOMER_ID"],
                "to_schema": "SALES",
                "to_table": "CUSTOMERS",
                "to_columns": ["ID"],
                "constraint": "FK_ORDERS_CUST",
                "direction": "outgoing",
            }
        ]
        sql = _generate_sql_join(path, "SALES", "ORDERS")

        assert '"SALES"."ORDERS"' in sql
        assert 'JOIN "SALES"."CUSTOMERS"' in sql
        assert '"SALES"."ORDERS"."CUSTOMER_ID"' in sql
        assert '"SALES"."CUSTOMERS"."ID"' in sql
        assert "SELECT *" in sql

    def test_multi_join(self) -> None:
        """Test generating SQL for a multi-step join path."""
        path = [
            {
                "from_schema": "SALES",
                "from_table": "ORDER_ITEMS",
                "from_columns": ["ORDER_ID"],
                "to_schema": "SALES",
                "to_table": "ORDERS",
                "to_columns": ["ID"],
                "constraint": "FK_ITEMS_ORDER",
                "direction": "outgoing",
            },
            {
                "from_schema": "SALES",
                "from_table": "ORDERS",
                "from_columns": ["CUSTOMER_ID"],
                "to_schema": "SALES",
                "to_table": "CUSTOMERS",
                "to_columns": ["ID"],
                "constraint": "FK_ORDERS_CUST",
                "direction": "outgoing",
            },
        ]
        sql = _generate_sql_join(path, "SALES", "ORDER_ITEMS")

        assert 'FROM "SALES"."ORDER_ITEMS"' in sql
        assert 'JOIN "SALES"."ORDERS"' in sql
        assert 'JOIN "SALES"."CUSTOMERS"' in sql

    def test_composite_join_conditions(self) -> None:
        """Test SQL generation with composite FK (multiple ON conditions)."""
        path = [
            {
                "from_schema": "SALES",
                "from_table": "SHIPMENTS",
                "from_columns": ["COUNTRY_CODE", "POSTAL_CODE"],
                "to_schema": "MASTER",
                "to_table": "ADDRESSES",
                "to_columns": ["COUNTRY", "POSTAL"],
                "constraint": "FK_SHIP_ADDR",
                "direction": "outgoing",
            }
        ]
        sql = _generate_sql_join(path, "SALES", "SHIPMENTS")

        assert '"SALES"."SHIPMENTS"."COUNTRY_CODE"' in sql
        assert '"MASTER"."ADDRESSES"."COUNTRY"' in sql
        assert '"SALES"."SHIPMENTS"."POSTAL_CODE"' in sql
        assert '"MASTER"."ADDRESSES"."POSTAL"' in sql
        assert " AND " in sql

    def test_cross_schema_join(self) -> None:
        """Test SQL generation for cross-schema joins."""
        path = [
            {
                "from_schema": "SALES",
                "from_table": "ORDERS",
                "from_columns": ["CUSTOMER_ID"],
                "to_schema": "MASTER",
                "to_table": "CUSTOMERS",
                "to_columns": ["ID"],
                "constraint": "FK_ORDERS_CUST",
                "direction": "outgoing",
            }
        ]
        sql = _generate_sql_join(path, "SALES", "ORDERS")

        assert 'FROM "SALES"."ORDERS"' in sql
        assert 'JOIN "MASTER"."CUSTOMERS"' in sql


# ==========================================================================
# Unit Tests: _path_to_join_steps
# ==========================================================================


class TestPathToJoinSteps:
    """Tests for converting raw paths to JoinStep models."""

    def test_outgoing_direction(self) -> None:
        """Test conversion of an outgoing edge to JoinStep."""
        path = [
            {
                "from_schema": "SALES",
                "from_table": "ORDERS",
                "from_columns": ["CUSTOMER_ID"],
                "to_schema": "SALES",
                "to_table": "CUSTOMERS",
                "to_columns": ["ID"],
                "constraint": "FK_ORDERS_CUST",
                "direction": "outgoing",
            }
        ]
        steps = _path_to_join_steps(path)

        assert len(steps) == 1
        step = steps[0]
        assert step.from_schema == "SALES"
        assert step.from_table == "ORDERS"
        assert step.from_column == "CUSTOMER_ID"
        assert step.to_schema == "SALES"
        assert step.to_table == "CUSTOMERS"
        assert step.to_column == "ID"
        assert step.constraint_name == "FK_ORDERS_CUST"
        assert step.direction == "outgoing"

    def test_incoming_direction(self) -> None:
        """Test conversion of an incoming (reversed) edge to JoinStep."""
        path = [
            {
                "from_schema": "SALES",
                "from_table": "CUSTOMERS",
                "from_columns": ["ID"],
                "to_schema": "SALES",
                "to_table": "ORDERS",
                "to_columns": ["CUSTOMER_ID"],
                "constraint": "FK_ORDERS_CUST",
                "direction": "incoming",
            }
        ]
        steps = _path_to_join_steps(path)

        assert len(steps) == 1
        assert steps[0].direction == "incoming"

    def test_composite_fk_uses_first_column(self) -> None:
        """Test that composite FKs use the first column in JoinStep."""
        path = [
            {
                "from_schema": "S",
                "from_table": "T1",
                "from_columns": ["C1", "C2"],
                "to_schema": "S",
                "to_table": "T2",
                "to_columns": ["D1", "D2"],
                "constraint": "FK_COMP",
                "direction": "outgoing",
            }
        ]
        steps = _path_to_join_steps(path)

        assert steps[0].from_column == "C1"
        assert steps[0].to_column == "D1"


# ==========================================================================
# Integration Tests: RelationshipService.get_foreign_keys
# ==========================================================================


class TestGetForeignKeys:
    """Tests for get_foreign_keys with mocked connection pool."""

    @pytest.mark.asyncio
    async def test_returns_outgoing_and_incoming_fks(self) -> None:
        """Test that both outgoing and incoming FKs are returned."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        # Responses: table_exists, table_exists(view), outgoing FKs, incoming FKs
        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDERS",)],  # TABLE_EXISTS_SQL: table found
                _outgoing_fk_rows(),  # OUTGOING_FK_SQL
                _incoming_fk_rows(),  # INCOMING_FK_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("SALES", "ORDERS")

        assert isinstance(result, ForeignKeysOutput)
        assert result.table_name == "ORDERS"
        assert result.schema_name == "SALES"
        assert result.outgoing_count == 1
        assert result.incoming_count == 1
        assert result.outgoing[0].constraint_name == "FK_ORDERS_CUSTOMER"
        assert result.incoming[0].constraint_name == "FK_ITEMS_ORDER"

    @pytest.mark.asyncio
    async def test_no_foreign_keys(self) -> None:
        """Test table with no foreign keys returns empty lists."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("STANDALONE_TABLE",)],  # TABLE_EXISTS_SQL: found
                [],  # OUTGOING_FK_SQL: none
                [],  # INCOMING_FK_SQL: none
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("SALES", "STANDALONE_TABLE")

        assert isinstance(result, ForeignKeysOutput)
        assert result.outgoing == []
        assert result.incoming == []
        assert result.outgoing_count == 0
        assert result.incoming_count == 0

    @pytest.mark.asyncio
    async def test_table_not_found_with_suggestions(self) -> None:
        """Test error response with fuzzy suggestions when table not found."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        # TABLE_EXISTS_SQL is a single UNION ALL query (tables + views):
        #   fetchall 1: [] (not found)
        # TABLES_IN_SCHEMA_SQL is another single UNION ALL query:
        #   fetchall 2: candidates for fuzzy matching
        _setup_cursor_responses(
            mock_conn,
            [
                [],  # TABLE_EXISTS_SQL: not found (single UNION ALL query)
                [("ORDERS",), ("ORDER_ITEMS",), ("CUSTOMERS",)],  # TABLES_IN_SCHEMA_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("SALES", "ORDRS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND
        assert "ORDRS" in result.message
        assert result.context is not None
        assert "similar_tables" in result.context

    @pytest.mark.asyncio
    async def test_table_not_found_no_suggestions(self) -> None:
        """Test error response without suggestions when nothing is similar."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [],  # TABLE_EXISTS_SQL: not found (single UNION ALL query)
                [("COMPLETELY_DIFFERENT",)],  # TABLES_IN_SCHEMA_SQL: nothing similar
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("SALES", "XYZABC")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_connection_error_during_fk_query(self) -> None:
        """Test that connection errors during FK query are wrapped in ToolError."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        # Flow: _verify_table_exists does 1 fetchall (TABLE_EXISTS_SQL),
        # then get_foreign_keys does OUTGOING_FK_SQL which should fail.
        cursor = mock_conn.cursor.return_value
        fetchall_count = 0

        def fetchall_side_effect() -> list[tuple[Any, ...]]:
            nonlocal fetchall_count
            fetchall_count += 1
            if fetchall_count == 1:
                return [("ORDERS",)]  # TABLE_EXISTS_SQL: found
            raise Exception("Connection lost")  # OUTGOING_FK_SQL fails

        cursor.fetchall.side_effect = fetchall_side_effect

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("SALES", "ORDERS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_composite_fk_grouped(self) -> None:
        """Test composite FK columns are grouped correctly."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("SHIPMENTS",)],  # TABLE_EXISTS_SQL: found
                _composite_fk_rows(),  # OUTGOING_FK_SQL: composite FK
                [],  # INCOMING_FK_SQL: none
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("SALES", "SHIPMENTS")

        assert isinstance(result, ForeignKeysOutput)
        assert result.outgoing_count == 1
        fk = result.outgoing[0]
        assert len(fk.source_columns) == 2
        assert len(fk.target_columns) == 2

    @pytest.mark.asyncio
    async def test_self_referencing_fk(self) -> None:
        """Test self-referencing FK is handled correctly."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("EMPLOYEES",)],  # TABLE_EXISTS_SQL: found
                _self_referencing_fk_rows(),  # OUTGOING_FK_SQL
                _self_referencing_fk_rows(),  # INCOMING_FK_SQL (same table ref'd)
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.get_foreign_keys("HR", "EMPLOYEES")

        assert isinstance(result, ForeignKeysOutput)
        assert result.outgoing_count == 1
        assert result.incoming_count == 1
        assert result.outgoing[0].source_table == "EMPLOYEES"
        assert result.outgoing[0].target_table == "EMPLOYEES"


# ==========================================================================
# Integration Tests: RelationshipService.find_join_path
# ==========================================================================


class TestFindJoinPath:
    """Tests for find_join_path with mocked connection pool."""

    @pytest.mark.asyncio
    async def test_direct_join_path(self) -> None:
        """Test finding a direct (1-hop) join path."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDERS",)],  # from table exists
                [("CUSTOMERS",)],  # to table exists
                _graph_fk_rows(),  # ALL_FK_SQL for graph building
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDERS", "SALES", "CUSTOMERS")

        assert isinstance(result, FindJoinPathOutput)
        assert result.from_table == "ORDERS"
        assert result.to_table == "CUSTOMERS"
        assert result.path_count >= 1
        assert result.paths[0].length == 1
        assert "JOIN" in result.paths[0].sql_example

    @pytest.mark.asyncio
    async def test_multi_hop_join_path(self) -> None:
        """Test finding a multi-hop join path."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDER_ITEMS",)],  # from table exists
                [("CUSTOMERS",)],  # to table exists
                _graph_fk_rows(),  # ALL_FK_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDER_ITEMS", "SALES", "CUSTOMERS")

        assert isinstance(result, FindJoinPathOutput)
        assert result.path_count >= 1
        assert result.paths[0].length == 2

    @pytest.mark.asyncio
    async def test_no_path_exists(self) -> None:
        """Test empty paths when tables are not connected."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDERS",)],  # from table exists
                [("UNRELATED",)],  # to table exists
                _graph_fk_rows(),  # ALL_FK_SQL (no path to UNRELATED)
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDERS", "SALES", "UNRELATED")

        assert isinstance(result, FindJoinPathOutput)
        assert result.path_count == 0
        assert result.paths == []

    @pytest.mark.asyncio
    async def test_max_depth_1_only_direct(self) -> None:
        """Test that max_depth=1 only returns direct relationships."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDER_ITEMS",)],  # from table exists
                [("CUSTOMERS",)],  # to table exists
                _graph_fk_rows(),  # ALL_FK_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path(
                "SALES", "ORDER_ITEMS", "SALES", "CUSTOMERS", max_depth=1
            )

        assert isinstance(result, FindJoinPathOutput)
        # ORDER_ITEMS -> CUSTOMERS is 2 hops, should not be found with depth=1
        assert result.path_count == 0

    @pytest.mark.asyncio
    async def test_from_table_not_found(self) -> None:
        """Test error when source table does not exist."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        # _verify_table_exists: TABLE_EXISTS_SQL (single UNION ALL) returns [],
        # then TABLES_IN_SCHEMA_SQL returns candidates
        _setup_cursor_responses(
            mock_conn,
            [
                [],  # TABLE_EXISTS_SQL: not found (single UNION ALL)
                [("ORDERS",), ("ORDER_ITEMS",)],  # TABLES_IN_SCHEMA_SQL: candidates
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDRS", "SALES", "CUSTOMERS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_to_table_not_found(self) -> None:
        """Test error when target table does not exist."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        # from table: TABLE_EXISTS_SQL returns found
        # to table: TABLE_EXISTS_SQL returns not found, TABLES_IN_SCHEMA_SQL returns candidates
        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDERS",)],  # from: TABLE_EXISTS_SQL found
                [],  # to: TABLE_EXISTS_SQL not found (single UNION ALL)
                [("CUSTOMERS",)],  # to: TABLES_IN_SCHEMA_SQL candidates
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDERS", "SALES", "CUSTMRS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.TABLE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_cross_schema_join_path(self) -> None:
        """Test finding paths across schema boundaries."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDERS",)],  # from table exists
                [("CUSTOMERS",)],  # to table exists
                _cross_schema_fk_rows(),  # ALL_FK_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDERS", "MASTER", "CUSTOMERS")

        assert isinstance(result, FindJoinPathOutput)
        assert result.path_count >= 1

    @pytest.mark.asyncio
    async def test_sql_example_generated(self) -> None:
        """Test that SQL JOIN examples are generated for each path."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDERS",)],  # from table exists
                [("CUSTOMERS",)],  # to table exists
                _graph_fk_rows(),  # ALL_FK_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDERS", "SALES", "CUSTOMERS")

        assert isinstance(result, FindJoinPathOutput)
        for path in result.paths:
            assert isinstance(path, JoinPath)
            assert "SELECT *" in path.sql_example
            assert "JOIN" in path.sql_example
            assert path.length == len(path.steps)

    @pytest.mark.asyncio
    async def test_connection_error_during_graph_build(self) -> None:
        """Test that connection errors during graph building are handled."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        cursor = mock_conn.cursor.return_value
        fetchall_count = 0

        def fetchall_side_effect() -> list[tuple[Any, ...]]:
            nonlocal fetchall_count
            fetchall_count += 1
            if fetchall_count == 1:
                return [("ORDERS",)]  # from: TABLE_EXISTS_SQL found
            if fetchall_count == 2:
                return [("CUSTOMERS",)]  # to: TABLE_EXISTS_SQL found
            # fetchall 3: ALL_FK_SQL fails
            raise Exception("Network error")

        cursor.fetchall.side_effect = fetchall_side_effect

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDERS", "SALES", "CUSTOMERS")

        assert isinstance(result, ToolError)
        assert result.code == ErrorCode.CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_paths_sorted_shortest_first(self) -> None:
        """Test that returned paths are sorted by length."""
        pool = _make_pool()
        mock_conn = _make_mock_connection()

        _setup_cursor_responses(
            mock_conn,
            [
                [("ORDER_ITEMS",)],  # from table exists
                [("CATEGORIES",)],  # to table exists
                _complex_graph_fk_rows(),  # ALL_FK_SQL
            ],
        )

        with patch(
            "mamba_mcp_hana.database.connection._create_connection",
            return_value=mock_conn,
        ):
            service = RelationshipService(pool)
            result = await service.find_join_path("SALES", "ORDER_ITEMS", "SALES", "CATEGORIES")

        assert isinstance(result, FindJoinPathOutput)
        if result.path_count > 1:
            for i in range(len(result.paths) - 1):
                assert result.paths[i].length <= result.paths[i + 1].length
