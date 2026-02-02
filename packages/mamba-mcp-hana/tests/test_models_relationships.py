"""Tests for Layer 2 relationship discovery models."""

import json

import pytest
from mamba_mcp_hana.models.relationships import (
    FindJoinPathInput,
    FindJoinPathOutput,
    ForeignKeyInfo,
    ForeignKeysOutput,
    GetForeignKeysInput,
    JoinPath,
    JoinStep,
)


class TestForeignKeyInfo:
    """Tests for the ForeignKeyInfo model."""

    def test_basic_instantiation(self) -> None:
        """ForeignKeyInfo can be created with all required fields."""
        fk = ForeignKeyInfo(
            constraint_name="FK_ORDER_CUSTOMER",
            source_schema="SALES",
            source_table="ORDERS",
            source_columns=["CUSTOMER_ID"],
            target_schema="SALES",
            target_table="CUSTOMERS",
            target_columns=["ID"],
            delete_rule="CASCADE",
        )
        assert fk.constraint_name == "FK_ORDER_CUSTOMER"
        assert fk.source_schema == "SALES"
        assert fk.source_table == "ORDERS"
        assert fk.source_columns == ["CUSTOMER_ID"]
        assert fk.target_schema == "SALES"
        assert fk.target_table == "CUSTOMERS"
        assert fk.target_columns == ["ID"]
        assert fk.delete_rule == "CASCADE"

    def test_default_delete_rule(self) -> None:
        """ForeignKeyInfo defaults delete_rule to RESTRICT."""
        fk = ForeignKeyInfo(
            constraint_name="FK_ITEM_ORDER",
            source_schema="SALES",
            source_table="ORDER_ITEMS",
            source_columns=["ORDER_ID"],
            target_schema="SALES",
            target_table="ORDERS",
            target_columns=["ID"],
        )
        assert fk.delete_rule == "RESTRICT"

    def test_composite_key_columns(self) -> None:
        """ForeignKeyInfo supports composite (multi-column) foreign keys."""
        fk = ForeignKeyInfo(
            constraint_name="FK_COMPOSITE",
            source_schema="WAREHOUSE",
            source_table="INVENTORY",
            source_columns=["PRODUCT_ID", "LOCATION_ID"],
            target_schema="WAREHOUSE",
            target_table="PRODUCT_LOCATIONS",
            target_columns=["PRODUCT_ID", "LOCATION_ID"],
            delete_rule="NO ACTION",
        )
        assert len(fk.source_columns) == 2
        assert len(fk.target_columns) == 2
        assert fk.source_columns == ["PRODUCT_ID", "LOCATION_ID"]
        assert fk.target_columns == ["PRODUCT_ID", "LOCATION_ID"]

    def test_cross_schema_foreign_key(self) -> None:
        """ForeignKeyInfo captures cross-schema references with different schemas on each side."""
        fk = ForeignKeyInfo(
            constraint_name="FK_CROSS_SCHEMA",
            source_schema="SALES",
            source_table="ORDERS",
            source_columns=["PRODUCT_ID"],
            target_schema="CATALOG",
            target_table="PRODUCTS",
            target_columns=["ID"],
            delete_rule="SET NULL",
        )
        assert fk.source_schema == "SALES"
        assert fk.target_schema == "CATALOG"
        assert fk.source_schema != fk.target_schema

    def test_serialization_to_dict(self) -> None:
        """ForeignKeyInfo serializes to a dictionary correctly."""
        fk = ForeignKeyInfo(
            constraint_name="FK_TEST",
            source_schema="S1",
            source_table="T1",
            source_columns=["COL_A"],
            target_schema="S2",
            target_table="T2",
            target_columns=["COL_B"],
            delete_rule="CASCADE",
        )
        data = fk.model_dump()
        assert isinstance(data, dict)
        assert data["constraint_name"] == "FK_TEST"
        assert data["source_schema"] == "S1"
        assert data["target_schema"] == "S2"
        assert data["source_columns"] == ["COL_A"]
        assert data["target_columns"] == ["COL_B"]
        assert data["delete_rule"] == "CASCADE"

    def test_serialization_to_json(self) -> None:
        """ForeignKeyInfo serializes to valid JSON for MCP transport."""
        fk = ForeignKeyInfo(
            constraint_name="FK_JSON",
            source_schema="SCHEMA_A",
            source_table="TABLE_A",
            source_columns=["ID"],
            target_schema="SCHEMA_B",
            target_table="TABLE_B",
            target_columns=["REF_ID"],
        )
        json_str = fk.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["constraint_name"] == "FK_JSON"
        assert parsed["source_columns"] == ["ID"]
        assert parsed["target_columns"] == ["REF_ID"]


class TestGetForeignKeysInput:
    """Tests for the GetForeignKeysInput model."""

    def test_basic_input(self) -> None:
        """GetForeignKeysInput requires table_name and schema_name."""
        inp = GetForeignKeysInput(table_name="ORDERS", schema_name="SALES")
        assert inp.table_name == "ORDERS"
        assert inp.schema_name == "SALES"

    def test_schema_name_required(self) -> None:
        """GetForeignKeysInput requires schema_name (no default for HANA)."""
        with pytest.raises(Exception):
            GetForeignKeysInput(table_name="ORDERS")  # type: ignore[call-arg]


class TestForeignKeysOutput:
    """Tests for the ForeignKeysOutput model."""

    def test_with_outgoing_and_incoming(self) -> None:
        """ForeignKeysOutput captures both outgoing and incoming FK relationships."""
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
        output = ForeignKeysOutput(
            table_name="ORDERS",
            schema_name="SALES",
            outgoing=[outgoing_fk],
            incoming=[incoming_fk],
            outgoing_count=1,
            incoming_count=1,
        )
        assert output.table_name == "ORDERS"
        assert output.schema_name == "SALES"
        assert len(output.outgoing) == 1
        assert len(output.incoming) == 1
        assert output.outgoing_count == 1
        assert output.incoming_count == 1
        assert output.outgoing[0].constraint_name == "FK_ORDER_CUST"
        assert output.incoming[0].constraint_name == "FK_ITEM_ORDER"

    def test_empty_fk_lists(self) -> None:
        """ForeignKeysOutput serializes correctly with empty FK lists."""
        output = ForeignKeysOutput(
            table_name="STANDALONE",
            schema_name="MYSCHEMA",
            outgoing=[],
            incoming=[],
            outgoing_count=0,
            incoming_count=0,
        )
        assert output.outgoing == []
        assert output.incoming == []
        assert output.outgoing_count == 0
        assert output.incoming_count == 0

    def test_empty_fk_lists_serialization(self) -> None:
        """Empty FK lists serialize to JSON correctly for MCP transport."""
        output = ForeignKeysOutput(
            table_name="STANDALONE",
            schema_name="MYSCHEMA",
            outgoing=[],
            incoming=[],
            outgoing_count=0,
            incoming_count=0,
        )
        data = output.model_dump()
        assert data["outgoing"] == []
        assert data["incoming"] == []
        json_str = output.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["outgoing"] == []
        assert parsed["incoming"] == []

    def test_default_factory_for_lists(self) -> None:
        """ForeignKeysOutput uses default_factory for empty lists."""
        output = ForeignKeysOutput(
            table_name="TABLE_X",
            schema_name="SCHEMA_Y",
            outgoing_count=0,
            incoming_count=0,
        )
        assert output.outgoing == []
        assert output.incoming == []

    def test_multiple_outgoing_fks(self) -> None:
        """ForeignKeysOutput handles multiple outgoing foreign keys."""
        fk1 = ForeignKeyInfo(
            constraint_name="FK_1",
            source_schema="S",
            source_table="T",
            source_columns=["A"],
            target_schema="S",
            target_table="REF1",
            target_columns=["ID"],
        )
        fk2 = ForeignKeyInfo(
            constraint_name="FK_2",
            source_schema="S",
            source_table="T",
            source_columns=["B"],
            target_schema="S",
            target_table="REF2",
            target_columns=["ID"],
        )
        output = ForeignKeysOutput(
            table_name="T",
            schema_name="S",
            outgoing=[fk1, fk2],
            incoming=[],
            outgoing_count=2,
            incoming_count=0,
        )
        assert len(output.outgoing) == 2
        assert output.outgoing_count == 2

    def test_cross_schema_fks_in_output(self) -> None:
        """ForeignKeysOutput handles cross-schema FK relationships."""
        fk = ForeignKeyInfo(
            constraint_name="FK_CROSS",
            source_schema="SALES",
            source_table="ORDERS",
            source_columns=["PRODUCT_ID"],
            target_schema="CATALOG",
            target_table="PRODUCTS",
            target_columns=["ID"],
        )
        output = ForeignKeysOutput(
            table_name="ORDERS",
            schema_name="SALES",
            outgoing=[fk],
            incoming=[],
            outgoing_count=1,
            incoming_count=0,
        )
        assert output.outgoing[0].source_schema == "SALES"
        assert output.outgoing[0].target_schema == "CATALOG"

    def test_full_serialization_to_json(self) -> None:
        """ForeignKeysOutput serializes full nested structure to JSON."""
        fk = ForeignKeyInfo(
            constraint_name="FK_NESTED",
            source_schema="S1",
            source_table="T1",
            source_columns=["C1", "C2"],
            target_schema="S2",
            target_table="T2",
            target_columns=["D1", "D2"],
            delete_rule="SET NULL",
        )
        output = ForeignKeysOutput(
            table_name="T1",
            schema_name="S1",
            outgoing=[fk],
            incoming=[],
            outgoing_count=1,
            incoming_count=0,
        )
        json_str = output.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["table_name"] == "T1"
        assert len(parsed["outgoing"]) == 1
        assert parsed["outgoing"][0]["source_columns"] == ["C1", "C2"]
        assert parsed["outgoing"][0]["delete_rule"] == "SET NULL"


class TestJoinStep:
    """Tests for the JoinStep model."""

    def test_outgoing_direction(self) -> None:
        """JoinStep with outgoing direction."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="SALES",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORDER_CUST",
            direction="outgoing",
        )
        assert step.direction == "outgoing"
        assert step.from_table == "ORDERS"
        assert step.to_table == "CUSTOMERS"

    def test_incoming_direction(self) -> None:
        """JoinStep with incoming direction."""
        step = JoinStep(
            from_schema="SALES",
            from_table="CUSTOMERS",
            from_column="ID",
            to_schema="SALES",
            to_table="ORDERS",
            to_column="CUSTOMER_ID",
            constraint_name="FK_ORDER_CUST",
            direction="incoming",
        )
        assert step.direction == "incoming"

    def test_cross_schema_step(self) -> None:
        """JoinStep supports cross-schema joins."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="PRODUCT_ID",
            to_schema="CATALOG",
            to_table="PRODUCTS",
            to_column="ID",
            constraint_name="FK_ORDER_PRODUCT",
            direction="outgoing",
        )
        assert step.from_schema == "SALES"
        assert step.to_schema == "CATALOG"
        assert step.from_schema != step.to_schema

    def test_invalid_direction_rejected(self) -> None:
        """JoinStep rejects invalid direction values."""
        with pytest.raises(Exception):
            JoinStep(
                from_schema="S",
                from_table="T",
                from_column="C",
                to_schema="S",
                to_table="T2",
                to_column="C2",
                constraint_name="FK",
                direction="sideways",  # type: ignore[arg-type]
            )

    def test_serialization_to_dict(self) -> None:
        """JoinStep serializes to dict correctly."""
        step = JoinStep(
            from_schema="S1",
            from_table="T1",
            from_column="C1",
            to_schema="S2",
            to_table="T2",
            to_column="C2",
            constraint_name="FK_TEST",
            direction="outgoing",
        )
        data = step.model_dump()
        assert data["direction"] == "outgoing"
        assert data["from_schema"] == "S1"
        assert data["to_schema"] == "S2"
        assert data["constraint_name"] == "FK_TEST"

    def test_serialization_to_json(self) -> None:
        """JoinStep serializes to valid JSON for MCP transport."""
        step = JoinStep(
            from_schema="S",
            from_table="T",
            from_column="C",
            to_schema="S",
            to_table="T2",
            to_column="C2",
            constraint_name="FK_X",
            direction="incoming",
        )
        json_str = step.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["direction"] == "incoming"


class TestJoinPath:
    """Tests for the JoinPath model."""

    def test_single_step_path(self) -> None:
        """JoinPath with a single step."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="SALES",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORDER_CUST",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example=(
                'SELECT * FROM "SALES"."ORDERS" o '
                'JOIN "SALES"."CUSTOMERS" c ON o."CUSTOMER_ID" = c."ID"'
            ),
        )
        assert path.length == 1
        assert len(path.steps) == 1
        assert "JOIN" in path.sql_example

    def test_multi_step_path(self) -> None:
        """JoinPath with multiple steps."""
        step1 = JoinStep(
            from_schema="SALES",
            from_table="ORDER_ITEMS",
            from_column="ORDER_ID",
            to_schema="SALES",
            to_table="ORDERS",
            to_column="ID",
            constraint_name="FK_ITEM_ORDER",
            direction="outgoing",
        )
        step2 = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="SALES",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORDER_CUST",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step1, step2],
            length=2,
            sql_example=(
                'SELECT * FROM "SALES"."ORDER_ITEMS" oi '
                'JOIN "SALES"."ORDERS" o ON oi."ORDER_ID" = o."ID" '
                'JOIN "SALES"."CUSTOMERS" c ON o."CUSTOMER_ID" = c."ID"'
            ),
        )
        assert path.length == 2
        assert len(path.steps) == 2

    def test_sql_example_included(self) -> None:
        """JoinPath includes a generated SQL JOIN example."""
        step = JoinStep(
            from_schema="S",
            from_table="A",
            from_column="B_ID",
            to_schema="S",
            to_table="B",
            to_column="ID",
            constraint_name="FK_A_B",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example='SELECT * FROM "S"."A" a JOIN "S"."B" b ON a."B_ID" = b."ID"',
        )
        assert path.sql_example.startswith("SELECT")
        assert "JOIN" in path.sql_example

    def test_serialization_to_json(self) -> None:
        """JoinPath serializes full structure including steps to JSON."""
        step = JoinStep(
            from_schema="S",
            from_table="T1",
            from_column="C1",
            to_schema="S",
            to_table="T2",
            to_column="C2",
            constraint_name="FK",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example="SELECT * FROM T1 JOIN T2 ON T1.C1 = T2.C2",
        )
        json_str = path.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["length"] == 1
        assert len(parsed["steps"]) == 1
        assert parsed["steps"][0]["direction"] == "outgoing"
        assert "JOIN" in parsed["sql_example"]


class TestFindJoinPathInput:
    """Tests for the FindJoinPathInput model."""

    def test_basic_input(self) -> None:
        """FindJoinPathInput accepts required fields."""
        inp = FindJoinPathInput(
            from_table="ORDERS",
            to_table="CUSTOMERS",
            from_schema="SALES",
            to_schema="SALES",
        )
        assert inp.from_table == "ORDERS"
        assert inp.to_table == "CUSTOMERS"
        assert inp.max_depth == 4  # default

    def test_custom_max_depth(self) -> None:
        """FindJoinPathInput accepts custom max_depth within bounds."""
        inp = FindJoinPathInput(
            from_table="A",
            to_table="B",
            from_schema="S",
            to_schema="S",
            max_depth=6,
        )
        assert inp.max_depth == 6

    def test_max_depth_lower_bound(self) -> None:
        """FindJoinPathInput rejects max_depth below 1."""
        with pytest.raises(Exception):
            FindJoinPathInput(
                from_table="A",
                to_table="B",
                from_schema="S",
                to_schema="S",
                max_depth=0,
            )

    def test_max_depth_upper_bound(self) -> None:
        """FindJoinPathInput rejects max_depth above 6."""
        with pytest.raises(Exception):
            FindJoinPathInput(
                from_table="A",
                to_table="B",
                from_schema="S",
                to_schema="S",
                max_depth=7,
            )

    def test_cross_schema_input(self) -> None:
        """FindJoinPathInput supports different from_schema and to_schema."""
        inp = FindJoinPathInput(
            from_table="ORDERS",
            to_table="PRODUCTS",
            from_schema="SALES",
            to_schema="CATALOG",
        )
        assert inp.from_schema == "SALES"
        assert inp.to_schema == "CATALOG"


class TestFindJoinPathOutput:
    """Tests for the FindJoinPathOutput model."""

    def test_single_path_output(self) -> None:
        """FindJoinPathOutput with one path."""
        step = JoinStep(
            from_schema="S",
            from_table="A",
            from_column="B_ID",
            to_schema="S",
            to_table="B",
            to_column="ID",
            constraint_name="FK_A_B",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example='SELECT * FROM "S"."A" JOIN "S"."B" ON "A"."B_ID" = "B"."ID"',
        )
        output = FindJoinPathOutput(
            from_table="A",
            to_table="B",
            paths=[path],
            path_count=1,
        )
        assert output.path_count == 1
        assert len(output.paths) == 1

    def test_multiple_paths_sorted_by_length(self) -> None:
        """FindJoinPathOutput paths are sorted by length (shortest first)."""
        short_step = JoinStep(
            from_schema="S",
            from_table="A",
            from_column="C_ID",
            to_schema="S",
            to_table="C",
            to_column="ID",
            constraint_name="FK_A_C",
            direction="outgoing",
        )
        long_step1 = JoinStep(
            from_schema="S",
            from_table="A",
            from_column="B_ID",
            to_schema="S",
            to_table="B",
            to_column="ID",
            constraint_name="FK_A_B",
            direction="outgoing",
        )
        long_step2 = JoinStep(
            from_schema="S",
            from_table="B",
            from_column="C_ID",
            to_schema="S",
            to_table="C",
            to_column="ID",
            constraint_name="FK_B_C",
            direction="outgoing",
        )
        short_path = JoinPath(
            steps=[short_step],
            length=1,
            sql_example="SELECT * FROM A JOIN C ON A.C_ID = C.ID",
        )
        long_path = JoinPath(
            steps=[long_step1, long_step2],
            length=2,
            sql_example="SELECT * FROM A JOIN B ON A.B_ID = B.ID JOIN C ON B.C_ID = C.ID",
        )
        # Paths provided sorted by length (shortest first)
        output = FindJoinPathOutput(
            from_table="A",
            to_table="C",
            paths=[short_path, long_path],
            path_count=2,
        )
        assert output.paths[0].length <= output.paths[1].length
        assert output.paths[0].length == 1
        assert output.paths[1].length == 2

    def test_no_paths_found(self) -> None:
        """FindJoinPathOutput with no paths."""
        output = FindJoinPathOutput(
            from_table="ISOLATED_A",
            to_table="ISOLATED_B",
            paths=[],
            path_count=0,
        )
        assert output.path_count == 0
        assert output.paths == []

    def test_full_serialization_to_json(self) -> None:
        """FindJoinPathOutput serializes full nested structure to JSON for MCP transport."""
        step = JoinStep(
            from_schema="SALES",
            from_table="ORDERS",
            from_column="CUSTOMER_ID",
            to_schema="SALES",
            to_table="CUSTOMERS",
            to_column="ID",
            constraint_name="FK_ORDER_CUST",
            direction="outgoing",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example=(
                'SELECT * FROM "SALES"."ORDERS" o '
                'JOIN "SALES"."CUSTOMERS" c ON o."CUSTOMER_ID" = c."ID"'
            ),
        )
        output = FindJoinPathOutput(
            from_table="ORDERS",
            to_table="CUSTOMERS",
            paths=[path],
            path_count=1,
        )
        json_str = output.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["from_table"] == "ORDERS"
        assert parsed["to_table"] == "CUSTOMERS"
        assert parsed["path_count"] == 1
        assert len(parsed["paths"]) == 1
        assert parsed["paths"][0]["length"] == 1
        assert len(parsed["paths"][0]["steps"]) == 1
        assert parsed["paths"][0]["steps"][0]["direction"] == "outgoing"
        assert "JOIN" in parsed["paths"][0]["sql_example"]

    def test_serialization_to_dict(self) -> None:
        """FindJoinPathOutput serializes nested structure to dict correctly."""
        step = JoinStep(
            from_schema="S",
            from_table="T1",
            from_column="C1",
            to_schema="S",
            to_table="T2",
            to_column="C2",
            constraint_name="FK",
            direction="incoming",
        )
        path = JoinPath(
            steps=[step],
            length=1,
            sql_example="SQL_EXAMPLE",
        )
        output = FindJoinPathOutput(
            from_table="T1",
            to_table="T2",
            paths=[path],
            path_count=1,
        )
        data = output.model_dump()
        assert isinstance(data, dict)
        assert isinstance(data["paths"], list)
        assert isinstance(data["paths"][0]["steps"], list)
        assert data["paths"][0]["steps"][0]["direction"] == "incoming"
