"""Tests for schema discovery tools (Layer 1)."""

from unittest.mock import MagicMock

import pytest
from mamba_mcp_pg.database.schema import SchemaService

from tests.conftest import create_mock_result


class TestListSchemas:
    """Tests for list_schemas functionality."""

    @pytest.mark.asyncio
    async def test_list_schemas_excludes_system_by_default(
        self, mock_connection: MagicMock
    ) -> None:
        """Test that system schemas are excluded by default."""
        # Setup mock result
        mock_result = create_mock_result(
            [
                {
                    "name": "public",
                    "owner": "postgres",
                    "description": "Default schema",
                    "table_count": 10,
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = SchemaService(mock_connection, 30000)
        schemas = await service.list_schemas(include_system=False)

        assert len(schemas) == 1
        assert schemas[0]["name"] == "public"

    @pytest.mark.asyncio
    async def test_list_schemas_includes_system_when_requested(
        self, mock_connection: MagicMock
    ) -> None:
        """Test that system schemas are included when requested."""
        mock_result = create_mock_result(
            [
                {"name": "public", "owner": "postgres", "description": None, "table_count": 10},
                {
                    "name": "pg_catalog",
                    "owner": "postgres",
                    "description": None,
                    "table_count": 100,
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = SchemaService(mock_connection, 30000)
        schemas = await service.list_schemas(include_system=True)

        assert len(schemas) == 2


class TestListTables:
    """Tests for list_tables functionality."""

    @pytest.mark.asyncio
    async def test_list_tables_returns_tables(self, mock_connection: MagicMock) -> None:
        """Test basic table listing."""
        mock_result = create_mock_result(
            [
                {
                    "name": "users",
                    "schema_name": "public",
                    "type": "table",
                    "description": None,
                    "estimated_row_count": 100,
                    "size_bytes": 1024,
                    "size_pretty": "1 KB",
                    "has_primary_key": True,
                    "column_count": 5,
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = SchemaService(mock_connection, 30000)
        tables = await service.list_tables("public", include_views=False)

        assert len(tables) >= 1
        assert tables[0]["name"] == "users"

    @pytest.mark.asyncio
    async def test_list_tables_with_name_pattern(self, mock_connection: MagicMock) -> None:
        """Test table listing with name pattern filter."""
        mock_result = create_mock_result(
            [
                {
                    "name": "user_accounts",
                    "schema_name": "public",
                    "type": "table",
                    "description": None,
                    "estimated_row_count": 50,
                    "size_bytes": 512,
                    "size_pretty": "512 B",
                    "has_primary_key": True,
                    "column_count": 3,
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = SchemaService(mock_connection, 30000)
        tables = await service.list_tables("public", name_pattern="user%")

        # The mock returns the same result regardless, but we verify the call works
        assert len(tables) >= 1


class TestDescribeTable:
    """Tests for describe_table functionality."""

    @pytest.mark.asyncio
    async def test_describe_columns(self, mock_connection: MagicMock) -> None:
        """Test column description."""
        mock_result = create_mock_result(
            [
                {
                    "name": "id",
                    "data_type": "integer",
                    "udt_name": "int4",
                    "is_nullable": False,
                    "default_value": None,
                    "description": "Primary key",
                    "character_maximum_length": None,
                    "numeric_precision": 32,
                    "numeric_scale": 0,
                },
                {
                    "name": "email",
                    "data_type": "character varying",
                    "udt_name": "varchar",
                    "is_nullable": False,
                    "default_value": None,
                    "description": "User email",
                    "character_maximum_length": 255,
                    "numeric_precision": None,
                    "numeric_scale": None,
                },
            ]
        )
        mock_connection.execute.return_value = mock_result

        service = SchemaService(mock_connection, 30000)
        columns = await service.describe_columns("public", "users")

        assert len(columns) == 2
        assert columns[0]["name"] == "id"
        assert columns[1]["name"] == "email"


class TestGetSampleRows:
    """Tests for get_sample_rows functionality."""

    @pytest.mark.asyncio
    async def test_get_sample_rows_basic(self, mock_connection: MagicMock) -> None:
        """Test basic sample row retrieval."""
        # First call for PK columns (empty)
        pk_result = create_mock_result([])

        # Second call for sample rows
        sample_result = create_mock_result(
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        )

        # Setup mock to return different results for different calls
        mock_connection.execute.side_effect = [
            pk_result,  # SET timeout
            pk_result,  # PK columns query
            pk_result,  # SET timeout
            sample_result,  # Sample rows query
        ]

        service = SchemaService(mock_connection, 30000)
        result = await service.get_sample_rows("public", "users", limit=2)

        assert result["row_count"] == 2
        assert len(result["rows"]) == 2
