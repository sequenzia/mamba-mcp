"""Tests for Layer 2 relationship discovery MCP tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_sap_hana.errors import ErrorCode, create_tool_error
from mamba_mcp_sap_hana.models.relationships import (
    FindJoinPathOutput,
    ForeignKeyInfo,
    ForeignKeysOutput,
    JoinPath,
    JoinStep,
)
from mamba_mcp_sap_hana.tools.relationship_tools import find_join_path, get_foreign_keys


def _make_mock_ctx() -> MagicMock:
    """Create a mock FastMCP context with pool accessible via lifespan_context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context.pool = MagicMock()
    return ctx


def _make_fk_output(
    table_name: str = "ORDERS",
    schema_name: str = "SALES",
    outgoing: list[ForeignKeyInfo] | None = None,
    incoming: list[ForeignKeyInfo] | None = None,
) -> ForeignKeysOutput:
    """Build a ForeignKeysOutput for testing."""
    out = outgoing or []
    inc = incoming or []
    return ForeignKeysOutput(
        table_name=table_name,
        schema_name=schema_name,
        outgoing=out,
        incoming=inc,
        outgoing_count=len(out),
        incoming_count=len(inc),
    )


def _make_join_path_output(
    from_table: str = "ORDER_ITEMS",
    to_table: str = "CUSTOMERS",
    paths: list[JoinPath] | None = None,
) -> FindJoinPathOutput:
    """Build a FindJoinPathOutput for testing."""
    p = paths or []
    return FindJoinPathOutput(
        from_table=from_table,
        to_table=to_table,
        paths=p,
        path_count=len(p),
    )


# ---------------------------------------------------------------------------
# get_foreign_keys tests
# ---------------------------------------------------------------------------


class TestGetForeignKeys:
    """Tests for get_foreign_keys MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_outgoing_and_incoming_fks(self) -> None:
        """Tool returns JSON with outgoing and incoming FK details."""
        outgoing_fk = ForeignKeyInfo(
            constraint_name="FK_ORDER_CUST",
            source_schema="SALES",
            source_table="ORDERS",
            source_columns=["CUSTOMER_ID"],
            target_schema="SALES",
            target_table="CUSTOMERS",
            target_columns=["ID"],
            delete_rule="CASCADE",
        )
        incoming_fk = ForeignKeyInfo(
            constraint_name="FK_ITEM_ORDER",
            source_schema="SALES",
            source_table="ORDER_ITEMS",
            source_columns=["ORDER_ID"],
            target_schema="SALES",
            target_table="ORDERS",
            target_columns=["ID"],
            delete_rule="RESTRICT",
        )
        output = _make_fk_output(
            outgoing=[outgoing_fk],
            incoming=[incoming_fk],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            result_json = await get_foreign_keys(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["table_name"] == "ORDERS"
        assert data["schema_name"] == "SALES"
        assert data["outgoing_count"] == 1
        assert data["incoming_count"] == 1
        assert data["outgoing"][0]["constraint_name"] == "FK_ORDER_CUST"
        assert data["incoming"][0]["constraint_name"] == "FK_ITEM_ORDER"

    @pytest.mark.asyncio
    async def test_returns_empty_lists_when_no_fks(self) -> None:
        """Tool returns empty outgoing/incoming lists for table without FKs."""
        output = _make_fk_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            result_json = await get_foreign_keys(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["outgoing"] == []
        assert data["incoming"] == []
        assert data["outgoing_count"] == 0
        assert data["incoming_count"] == 0

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns JSON error when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'ORDERS' not found in schema 'SALES'",
            tool_name="get_foreign_keys",
            input_received={"schema_name": "SALES", "table_name": "ORDERS"},
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=tool_error)

            result_json = await get_foreign_keys(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "not found" in data["message"]
        assert data["tool_name"] == "get_foreign_keys"

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error JSON when no context is provided."""
        result_json = await get_foreign_keys(
            table_name="ORDERS",
            schema_name="SALES",
            ctx=None,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in data["message"].lower()
        assert data["tool_name"] == "get_foreign_keys"

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_service(self) -> None:
        """Tool passes table_name and schema_name to RelationshipService."""
        output = _make_fk_output(
            table_name="MY_TABLE",
            schema_name="MY_SCHEMA",
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            await get_foreign_keys(
                table_name="MY_TABLE",
                schema_name="MY_SCHEMA",
                ctx=ctx,
            )

            mock_service.get_foreign_keys.assert_awaited_once_with(
                schema_name="MY_SCHEMA",
                table_name="MY_TABLE",
            )

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates RelationshipService with pool from context."""
        output = _make_fk_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            await get_foreign_keys(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )


# ---------------------------------------------------------------------------
# find_join_path tests
# ---------------------------------------------------------------------------


class TestFindJoinPath:
    """Tests for find_join_path MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_paths_with_sql_examples(self) -> None:
        """Tool returns JSON with join paths and SQL examples."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDER_ITEMS",
            from_column="ORDER_ID",
            to_schema="SALES",
            to_table="ORDERS",
            to_column="ID",
            constraint_name="FK_ITEM_ORDER",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example='SELECT *\nFROM "SALES"."ORDER_ITEMS"\n  JOIN "SALES"."ORDERS"\n'
            '    ON "SALES"."ORDER_ITEMS"."ORDER_ID" = "SALES"."ORDERS"."ID"',
        )
        output = _make_join_path_output(paths=[path])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            result_json = await find_join_path(
                from_table="ORDER_ITEMS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["path_count"] == 1
        assert len(data["paths"]) == 1
        assert data["paths"][0]["length"] == 1
        assert "sql_example" in data["paths"][0]

    @pytest.mark.asyncio
    async def test_to_schema_defaults_to_from_schema(self) -> None:
        """Tool defaults to_schema to from_schema when not provided."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="ORDER_ITEMS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                to_schema=None,
                ctx=ctx,
            )

            mock_service.find_join_path.assert_awaited_once_with(
                from_schema="SALES",
                from_table="ORDER_ITEMS",
                to_schema="SALES",
                to_table="CUSTOMERS",
                max_depth=4,
            )

    @pytest.mark.asyncio
    async def test_to_schema_explicit_value(self) -> None:
        """Tool passes explicit to_schema when provided."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="ORDER_ITEMS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                to_schema="MASTER_DATA",
                ctx=ctx,
            )

            mock_service.find_join_path.assert_awaited_once_with(
                from_schema="SALES",
                from_table="ORDER_ITEMS",
                to_schema="MASTER_DATA",
                to_table="CUSTOMERS",
                max_depth=4,
            )

    @pytest.mark.asyncio
    async def test_max_depth_clamped_to_min(self) -> None:
        """Tool clamps max_depth to minimum of 1."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="A",
                to_table="B",
                from_schema="S",
                max_depth=0,
                ctx=ctx,
            )

            call_kwargs = mock_service.find_join_path.call_args.kwargs
            assert call_kwargs["max_depth"] == 1

    @pytest.mark.asyncio
    async def test_max_depth_clamped_to_max(self) -> None:
        """Tool clamps max_depth to maximum of 6."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="A",
                to_table="B",
                from_schema="S",
                max_depth=10,
                ctx=ctx,
            )

            call_kwargs = mock_service.find_join_path.call_args.kwargs
            assert call_kwargs["max_depth"] == 6

    @pytest.mark.asyncio
    async def test_max_depth_within_range_passed_through(self) -> None:
        """Tool passes through max_depth values within 1-6 range."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="A",
                to_table="B",
                from_schema="S",
                max_depth=3,
                ctx=ctx,
            )

            call_kwargs = mock_service.find_join_path.call_args.kwargs
            assert call_kwargs["max_depth"] == 3

    @pytest.mark.asyncio
    async def test_handles_service_tool_error(self) -> None:
        """Tool returns JSON error when service returns ToolError."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'MISSING' not found in schema 'SALES'",
            tool_name="find_join_path",
            input_received={
                "from_schema": "SALES",
                "from_table": "MISSING",
                "to_schema": "SALES",
                "to_table": "CUSTOMERS",
            },
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=tool_error)

            result_json = await find_join_path(
                from_table="MISSING",
                to_table="CUSTOMERS",
                from_schema="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "not found" in data["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Tool returns error JSON when no context is provided."""
        result_json = await find_join_path(
            from_table="A",
            to_table="B",
            from_schema="S",
            ctx=None,
        )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.CONNECTION_ERROR
        assert "context" in data["message"].lower()
        assert data["tool_name"] == "find_join_path"

    @pytest.mark.asyncio
    async def test_returns_empty_paths_when_no_path_found(self) -> None:
        """Tool returns empty paths list when no join path exists."""
        output = _make_join_path_output(paths=[])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            result_json = await find_join_path(
                from_table="ORDER_ITEMS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["path_count"] == 0
        assert data["paths"] == []

    @pytest.mark.asyncio
    async def test_service_instantiated_with_pool(self) -> None:
        """Tool creates RelationshipService with pool from context."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="A",
                to_table="B",
                from_schema="S",
                ctx=ctx,
            )

            mock_cls.assert_called_once_with(
                ctx.request_context.lifespan_context.pool,
            )

    @pytest.mark.asyncio
    async def test_multiple_paths_returned(self) -> None:
        """Tool returns multiple join paths when available."""
        step1 = JoinStep(
            from_schema="S",
            from_table="A",
            from_column="X",
            to_schema="S",
            to_table="B",
            to_column="Y",
            constraint_name="FK1",
            direction="outgoing",
        )
        step2 = JoinStep(
            from_schema="S",
            from_table="A",
            from_column="Z",
            to_schema="S",
            to_table="C",
            to_column="W",
            constraint_name="FK2",
            direction="outgoing",
        )
        step3 = JoinStep(
            from_schema="S",
            from_table="C",
            from_column="P",
            to_schema="S",
            to_table="B",
            to_column="Q",
            constraint_name="FK3",
            direction="outgoing",
        )
        path1 = JoinPath(steps=[step1], length=1, sql_example="SELECT * FROM A JOIN B")
        path2 = JoinPath(
            steps=[step2, step3], length=2, sql_example="SELECT * FROM A JOIN C JOIN B"
        )
        output = _make_join_path_output(paths=[path1, path2])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            result_json = await find_join_path(
                from_table="A",
                to_table="B",
                from_schema="S",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["path_count"] == 2
        assert len(data["paths"]) == 2
        assert data["paths"][0]["length"] == 1
        assert data["paths"][1]["length"] == 2


# ---------------------------------------------------------------------------
# Tool registration test
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests for tool registration with FastMCP."""

    def test_tools_are_registered_on_mcp(self) -> None:
        """Both relationship tools are registered on the mcp server instance."""
        from mamba_mcp_sap_hana.server import mcp as server

        # Collect registered tool names
        tool_names = []
        for tool in server._tool_manager._tools.values():
            tool_names.append(tool.name)

        assert "get_foreign_keys" in tool_names
        assert "find_join_path" in tool_names

    def test_tools_have_docstrings(self) -> None:
        """Each tool function has a non-empty docstring."""
        assert get_foreign_keys.__doc__
        assert find_join_path.__doc__


# ---------------------------------------------------------------------------
# Phase 2: Extended relationship tool tests
# ---------------------------------------------------------------------------


class TestGetForeignKeysExtended:
    """Extended tests for get_foreign_keys tool covering composite FKs and edge cases."""

    @pytest.mark.asyncio
    async def test_composite_fk_output(self) -> None:
        """Tool returns composite (multi-column) FK details correctly."""
        composite_fk = ForeignKeyInfo(
            constraint_name="FK_SHIPMENTS_ADDR",
            source_schema="SALES",
            source_table="SHIPMENTS",
            source_columns=["COUNTRY_CODE", "POSTAL_CODE"],
            target_schema="MASTER",
            target_table="ADDRESSES",
            target_columns=["COUNTRY", "POSTAL"],
            delete_rule="RESTRICT",
        )
        output = _make_fk_output(
            table_name="SHIPMENTS",
            schema_name="SALES",
            outgoing=[composite_fk],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            result_json = await get_foreign_keys(
                table_name="SHIPMENTS",
                schema_name="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        fk = data["outgoing"][0]
        assert fk["source_columns"] == ["COUNTRY_CODE", "POSTAL_CODE"]
        assert fk["target_columns"] == ["COUNTRY", "POSTAL"]
        assert fk["delete_rule"] == "RESTRICT"

    @pytest.mark.asyncio
    async def test_multiple_outgoing_fks(self) -> None:
        """Tool returns multiple outgoing FKs for a table."""
        fk1 = ForeignKeyInfo(
            constraint_name="FK_ORDER_CUST",
            source_schema="SALES",
            source_table="ORDERS",
            source_columns=["CUSTOMER_ID"],
            target_schema="SALES",
            target_table="CUSTOMERS",
            target_columns=["ID"],
            delete_rule="CASCADE",
        )
        fk2 = ForeignKeyInfo(
            constraint_name="FK_ORDER_PROD",
            source_schema="SALES",
            source_table="ORDERS",
            source_columns=["PRODUCT_ID"],
            target_schema="SALES",
            target_table="PRODUCTS",
            target_columns=["ID"],
            delete_rule="RESTRICT",
        )
        output = _make_fk_output(
            outgoing=[fk1, fk2],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            result_json = await get_foreign_keys(
                table_name="ORDERS",
                schema_name="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["outgoing_count"] == 2
        names = {fk["constraint_name"] for fk in data["outgoing"]}
        assert names == {"FK_ORDER_CUST", "FK_ORDER_PROD"}

    @pytest.mark.asyncio
    async def test_service_exception_wrapped_in_error(self) -> None:
        """Tool catches unexpected exceptions from service calls."""
        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(side_effect=RuntimeError("Network timeout"))

            # The tool does not wrap service exceptions (unlike schema tools);
            # it lets them propagate. Verify the exception is raised.
            with pytest.raises(RuntimeError, match="Network timeout"):
                await get_foreign_keys(
                    table_name="ORDERS",
                    schema_name="SALES",
                    ctx=ctx,
                )

    @pytest.mark.asyncio
    async def test_self_referencing_fk_output(self) -> None:
        """Tool handles self-referencing FK (same source and target table)."""
        self_fk = ForeignKeyInfo(
            constraint_name="FK_EMP_MANAGER",
            source_schema="HR",
            source_table="EMPLOYEES",
            source_columns=["MANAGER_ID"],
            target_schema="HR",
            target_table="EMPLOYEES",
            target_columns=["ID"],
            delete_rule="SET NULL",
        )
        output = _make_fk_output(
            table_name="EMPLOYEES",
            schema_name="HR",
            outgoing=[self_fk],
            incoming=[self_fk],
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.get_foreign_keys = AsyncMock(return_value=output)

            result_json = await get_foreign_keys(
                table_name="EMPLOYEES",
                schema_name="HR",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["outgoing_count"] == 1
        assert data["incoming_count"] == 1
        assert data["outgoing"][0]["source_table"] == "EMPLOYEES"
        assert data["outgoing"][0]["target_table"] == "EMPLOYEES"


class TestFindJoinPathExtended:
    """Extended tests for find_join_path with cross-schema, multi-hop, and edge cases."""

    @pytest.mark.asyncio
    async def test_cross_schema_path(self) -> None:
        """Tool resolves cross-schema join path when to_schema differs."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="MASTER",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORDERS_CUST",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example='SELECT * FROM "SALES"."ORDERS" JOIN "MASTER"."CUSTOMERS"',
        )
        output = _make_join_path_output(paths=[path])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            result_json = await find_join_path(
                from_table="ORDERS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                to_schema="MASTER",
                ctx=ctx,
            )

        mock_service.find_join_path.assert_awaited_once_with(
            from_schema="SALES",
            from_table="ORDERS",
            to_schema="MASTER",
            to_table="CUSTOMERS",
            max_depth=4,
        )
        data = json.loads(result_json)
        assert data["path_count"] == 1

    @pytest.mark.asyncio
    async def test_multi_hop_path_with_steps(self) -> None:
        """Tool returns multi-hop path with step details."""
        step1 = JoinStep(
            from_schema="S",
            from_table="ORDER_ITEMS",
            from_column="ORDER_ID",
            to_schema="S",
            to_table="ORDERS",
            to_column="ID",
            constraint_name="FK_ITEMS_ORDER",
            direction="outgoing",
        )
        step2 = JoinStep(
            from_schema="S",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="S",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORDER_CUST",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step1, step2],
            length=2,
            sql_example="SELECT * FROM ORDER_ITEMS JOIN ORDERS JOIN CUSTOMERS",
        )
        output = _make_join_path_output(paths=[path])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            result_json = await find_join_path(
                from_table="ORDER_ITEMS",
                to_table="CUSTOMERS",
                from_schema="S",
                ctx=ctx,
            )

        data = json.loads(result_json)
        path_data = data["paths"][0]
        assert path_data["length"] == 2
        assert len(path_data["steps"]) == 2
        assert path_data["steps"][0]["from_table"] == "ORDER_ITEMS"
        assert path_data["steps"][0]["to_table"] == "ORDERS"
        assert path_data["steps"][0]["direction"] == "outgoing"
        assert path_data["steps"][1]["from_table"] == "ORDERS"
        assert path_data["steps"][1]["to_table"] == "CUSTOMERS"

    @pytest.mark.asyncio
    async def test_max_depth_negative_clamped(self) -> None:
        """Tool clamps negative max_depth to 1."""
        output = _make_join_path_output()

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            await find_join_path(
                from_table="A",
                to_table="B",
                from_schema="S",
                max_depth=-5,
                ctx=ctx,
            )

        call_kwargs = mock_service.find_join_path.call_args.kwargs
        assert call_kwargs["max_depth"] == 1

    @pytest.mark.asyncio
    async def test_sql_example_in_paths(self) -> None:
        """Tool returns SQL JOIN example for each path."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="SALES",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORD_CUST",
            direction="outgoing",
        )
        sql_example = (
            'SELECT *\nFROM "SALES"."ORDERS"\n'
            '  JOIN "SALES"."CUSTOMERS"\n'
            '    ON "SALES"."ORDERS"."CUSTOMER_ID" = "SALES"."CUSTOMERS"."ID"'
        )
        path = JoinPath(steps=[step], length=1, sql_example=sql_example)
        output = _make_join_path_output(paths=[path])

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=output)

            result_json = await find_join_path(
                from_table="ORDERS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert "SELECT *" in data["paths"][0]["sql_example"]
        assert "JOIN" in data["paths"][0]["sql_example"]

    @pytest.mark.asyncio
    async def test_table_not_found_error(self) -> None:
        """Tool returns error with suggestions when from_table not found."""
        tool_error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'ORDRS' not found in schema 'SALES'",
            suggestion="Did you mean: ORDERS, ORDER_ITEMS?",
            tool_name="find_join_path",
            input_received={
                "from_schema": "SALES",
                "from_table": "ORDRS",
            },
        )

        ctx = _make_mock_ctx()
        with patch("mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService") as mock_cls:
            mock_service = mock_cls.return_value
            mock_service.find_join_path = AsyncMock(return_value=tool_error)

            result_json = await find_join_path(
                from_table="ORDRS",
                to_table="CUSTOMERS",
                from_schema="SALES",
                ctx=ctx,
            )

        data = json.loads(result_json)
        assert data["code"] == ErrorCode.TABLE_NOT_FOUND
        assert "ORDERS" in data["suggestion"]
