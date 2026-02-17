"""Tests for relationship discovery tools (Layer 2)."""

from unittest.mock import MagicMock

import pytest
from mamba_mcp_pg.database.relationships import RelationshipService

from tests.pg.conftest import create_mock_result


class TestGetForeignKeys:
    """Tests for get_foreign_keys functionality."""

    @pytest.mark.asyncio
    async def test_returns_outgoing_foreign_keys(self, mock_connection: MagicMock) -> None:
        """Test retrieval of outgoing foreign keys."""
        mock_result = create_mock_result(
            [
                {
                    "constraint_name": "orders_user_id_fkey",
                    "from_schema": "public",
                    "from_table": "orders",
                    "from_columns": ["user_id"],
                    "to_schema": "public",
                    "to_table": "users",
                    "to_columns": ["id"],
                    "on_update": "CASCADE",
                    "on_delete": "RESTRICT",
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = RelationshipService(mock_connection, 30000)
        fks = await service.get_outgoing_fks("public", "orders")

        assert len(fks) == 1
        assert fks[0]["to_table"] == "users"

    @pytest.mark.asyncio
    async def test_returns_incoming_foreign_keys(self, mock_connection: MagicMock) -> None:
        """Test retrieval of incoming foreign keys."""
        mock_result = create_mock_result(
            [
                {
                    "constraint_name": "order_items_order_id_fkey",
                    "from_schema": "public",
                    "from_table": "order_items",
                    "from_columns": ["order_id"],
                    "to_schema": "public",
                    "to_table": "orders",
                    "to_columns": ["id"],
                    "on_update": "CASCADE",
                    "on_delete": "CASCADE",
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = RelationshipService(mock_connection, 30000)
        fks = await service.get_incoming_fks("public", "orders")

        assert len(fks) == 1
        assert fks[0]["from_table"] == "order_items"


class TestFindJoinPath:
    """Tests for find_join_path functionality."""

    def test_bfs_finds_direct_path(self) -> None:
        """Test BFS finds direct single-hop path."""
        service = RelationshipService(None, 30000)  # type: ignore

        edges = [
            {
                "from": "public.orders",
                "to": "public.users",
                "from_col": "user_id",
                "to_col": "id",
                "constraint": "orders_user_id_fkey",
            },
        ]

        paths = service._bfs_paths(edges, "public.orders", "public.users", 4)

        assert len(paths) == 1
        assert len(paths[0]) == 1  # Single hop

    def test_bfs_finds_two_hop_path(self) -> None:
        """Test BFS finds two-hop path."""
        service = RelationshipService(None, 30000)  # type: ignore

        edges = [
            {
                "from": "public.order_items",
                "to": "public.orders",
                "from_col": "order_id",
                "to_col": "id",
                "constraint": "order_items_order_id_fkey",
            },
            {
                "from": "public.orders",
                "to": "public.users",
                "from_col": "user_id",
                "to_col": "id",
                "constraint": "orders_user_id_fkey",
            },
        ]

        paths = service._bfs_paths(edges, "public.order_items", "public.users", 4)

        assert len(paths) == 1
        assert len(paths[0]) == 2  # Two hops

    def test_bfs_respects_max_depth(self) -> None:
        """Test BFS respects max_depth parameter."""
        service = RelationshipService(None, 30000)  # type: ignore

        # Create a chain: A -> B -> C -> D
        edges = [
            {"from": "s.a", "to": "s.b", "from_col": "x", "to_col": "y", "constraint": "c1"},
            {"from": "s.b", "to": "s.c", "from_col": "x", "to_col": "y", "constraint": "c2"},
            {"from": "s.c", "to": "s.d", "from_col": "x", "to_col": "y", "constraint": "c3"},
        ]

        # With max_depth=2, shouldn't find path from A to D (requires 3 hops)
        paths = service._bfs_paths(edges, "s.a", "s.d", 2)
        assert len(paths) == 0

        # With max_depth=3, should find the path
        paths = service._bfs_paths(edges, "s.a", "s.d", 3)
        assert len(paths) == 1

    def test_bfs_returns_empty_for_same_table(self) -> None:
        """Test BFS returns empty for same start and end."""
        service = RelationshipService(None, 30000)  # type: ignore

        edges = [
            {"from": "s.a", "to": "s.b", "from_col": "x", "to_col": "y", "constraint": "c1"},
        ]

        # Same start and end should return empty
        paths = service._bfs_paths(edges, "s.a", "s.a", 4)
        assert len(paths) == 0

    def test_bfs_finds_multiple_paths(self) -> None:
        """Test BFS finds multiple paths when available."""
        service = RelationshipService(None, 30000)  # type: ignore

        # Create two paths: A -> B -> D and A -> C -> D
        edges = [
            {"from": "s.a", "to": "s.b", "from_col": "x", "to_col": "y", "constraint": "c1"},
            {"from": "s.b", "to": "s.d", "from_col": "x", "to_col": "y", "constraint": "c2"},
            {"from": "s.a", "to": "s.c", "from_col": "x", "to_col": "y", "constraint": "c3"},
            {"from": "s.c", "to": "s.d", "from_col": "x", "to_col": "y", "constraint": "c4"},
        ]

        paths = service._bfs_paths(edges, "s.a", "s.d", 4)
        assert len(paths) == 2
