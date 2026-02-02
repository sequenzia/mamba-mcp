"""Tests for Layer 1 schema discovery Pydantic models."""

import json

import pytest
from mamba_mcp_hana.models.schema import (
    ColumnInfo,
    ConstraintInfo,
    DescribeTableInput,
    DescribeTableOutput,
    GetSampleRowsInput,
    IndexInfo,
    ListSchemasInput,
    ListSchemasOutput,
    ListTablesInput,
    ListTablesOutput,
    SampleRowsOutput,
    SchemaInfo,
    TableInfo,
)
from pydantic import ValidationError

# === SchemaInfo ===


class TestSchemaInfo:
    """Tests for SchemaInfo model."""

    def test_valid_schema_info(self) -> None:
        """SchemaInfo should accept valid data with all required fields."""
        info = SchemaInfo(name="MY_SCHEMA", owner="ADMIN", table_count=42, is_system=False)
        assert info.name == "MY_SCHEMA"
        assert info.owner == "ADMIN"
        assert info.table_count == 42
        assert info.is_system is False

    def test_system_schema(self) -> None:
        """SchemaInfo should correctly represent a system schema."""
        info = SchemaInfo(name="SYS", owner="SYS", table_count=500, is_system=True)
        assert info.is_system is True

    def test_serialization_to_dict(self) -> None:
        """SchemaInfo should serialize to a dict for MCP transport."""
        info = SchemaInfo(name="PUBLIC", owner="SYSTEM", table_count=10, is_system=False)
        data = info.model_dump()
        assert data == {
            "name": "PUBLIC",
            "owner": "SYSTEM",
            "table_count": 10,
            "is_system": False,
        }

    def test_serialization_to_json(self) -> None:
        """SchemaInfo should serialize to valid JSON."""
        info = SchemaInfo(name="PUBLIC", owner="SYSTEM", table_count=10, is_system=False)
        json_str = info.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["name"] == "PUBLIC"
        assert parsed["table_count"] == 10

    def test_missing_required_field_rejected(self) -> None:
        """SchemaInfo should reject missing required fields."""
        with pytest.raises(ValidationError):
            SchemaInfo(name="X", owner="Y")  # type: ignore[call-arg]


# === ListSchemasInput ===


class TestListSchemasInput:
    """Tests for ListSchemasInput model."""

    def test_defaults(self) -> None:
        """ListSchemasInput should default include_system to False."""
        inp = ListSchemasInput()
        assert inp.include_system is False

    def test_include_system_true(self) -> None:
        """ListSchemasInput should accept include_system=True."""
        inp = ListSchemasInput(include_system=True)
        assert inp.include_system is True


# === ListSchemasOutput ===


class TestListSchemasOutput:
    """Tests for ListSchemasOutput model."""

    def test_valid_output(self) -> None:
        """ListSchemasOutput should accept a list of schemas and count."""
        schemas = [
            SchemaInfo(name="S1", owner="ADMIN", table_count=5, is_system=False),
            SchemaInfo(name="S2", owner="ADMIN", table_count=3, is_system=False),
        ]
        output = ListSchemasOutput(schemas=schemas, count=2)
        assert len(output.schemas) == 2
        assert output.count == 2

    def test_empty_schemas(self) -> None:
        """ListSchemasOutput should handle an empty list of schemas."""
        output = ListSchemasOutput(schemas=[], count=0)
        assert output.schemas == []
        assert output.count == 0

    def test_serialization_to_json(self) -> None:
        """ListSchemasOutput should serialize to valid JSON for MCP transport."""
        output = ListSchemasOutput(
            schemas=[SchemaInfo(name="S1", owner="O", table_count=1, is_system=False)],
            count=1,
        )
        parsed = json.loads(output.model_dump_json())
        assert isinstance(parsed["schemas"], list)
        assert parsed["count"] == 1


# === TableInfo ===


class TestTableInfo:
    """Tests for TableInfo model."""

    def test_column_store_table(self) -> None:
        """TableInfo should represent a column store table."""
        info = TableInfo(
            name="ORDERS",
            type="TABLE",
            record_count=1000,
            column_count=12,
            store_type="COLUMN",
            is_column_table=True,
        )
        assert info.name == "ORDERS"
        assert info.type == "TABLE"
        assert info.store_type == "COLUMN"
        assert info.is_column_table is True

    def test_row_store_table(self) -> None:
        """TableInfo should represent a row store table."""
        info = TableInfo(
            name="CONFIG",
            type="TABLE",
            record_count=50,
            column_count=5,
            store_type="ROW",
            is_column_table=False,
        )
        assert info.store_type == "ROW"
        assert info.is_column_table is False

    def test_view_with_no_store_type(self) -> None:
        """TableInfo should allow None store_type for views."""
        info = TableInfo(
            name="V_ORDERS",
            type="VIEW",
            record_count=0,
            column_count=8,
            store_type=None,
            is_column_table=False,
        )
        assert info.type == "VIEW"
        assert info.store_type is None

    def test_invalid_type_rejected(self) -> None:
        """TableInfo should reject invalid type values."""
        with pytest.raises(ValidationError):
            TableInfo(
                name="X",
                type="MATERIALIZED_VIEW",  # type: ignore[arg-type]
                record_count=0,
                column_count=0,
                is_column_table=False,
            )

    def test_invalid_store_type_rejected(self) -> None:
        """TableInfo should reject invalid store_type values."""
        with pytest.raises(ValidationError):
            TableInfo(
                name="X",
                type="TABLE",
                record_count=0,
                column_count=0,
                store_type="MEMORY",  # type: ignore[arg-type]
                is_column_table=False,
            )

    def test_serialization_to_dict(self) -> None:
        """TableInfo should serialize store_type to dict."""
        info = TableInfo(
            name="T1",
            type="TABLE",
            record_count=100,
            column_count=5,
            store_type="COLUMN",
            is_column_table=True,
        )
        data = info.model_dump()
        assert data["store_type"] == "COLUMN"
        assert data["is_column_table"] is True

    def test_serialization_to_json(self) -> None:
        """TableInfo should serialize to valid JSON."""
        info = TableInfo(
            name="T1",
            type="TABLE",
            record_count=100,
            column_count=5,
            store_type="COLUMN",
            is_column_table=True,
        )
        parsed = json.loads(info.model_dump_json())
        assert parsed["store_type"] == "COLUMN"


# === ListTablesInput ===


class TestListTablesInput:
    """Tests for ListTablesInput model."""

    def test_required_schema_name(self) -> None:
        """ListTablesInput should require schema_name."""
        inp = ListTablesInput(schema_name="MY_SCHEMA")
        assert inp.schema_name == "MY_SCHEMA"

    def test_defaults(self) -> None:
        """ListTablesInput should default include_views=True and name_pattern=None."""
        inp = ListTablesInput(schema_name="S")
        assert inp.include_views is True
        assert inp.name_pattern is None

    def test_name_pattern(self) -> None:
        """ListTablesInput should accept a LIKE pattern."""
        inp = ListTablesInput(schema_name="S", name_pattern="USER%")
        assert inp.name_pattern == "USER%"

    def test_missing_schema_name_rejected(self) -> None:
        """ListTablesInput should reject missing schema_name."""
        with pytest.raises(ValidationError):
            ListTablesInput()  # type: ignore[call-arg]


# === ListTablesOutput ===


class TestListTablesOutput:
    """Tests for ListTablesOutput model."""

    def test_valid_output(self) -> None:
        """ListTablesOutput should accept valid table list."""
        tables = [
            TableInfo(
                name="T1",
                type="TABLE",
                record_count=10,
                column_count=3,
                store_type="COLUMN",
                is_column_table=True,
            ),
        ]
        output = ListTablesOutput(tables=tables, schema_name="PUBLIC", count=1)
        assert len(output.tables) == 1
        assert output.schema_name == "PUBLIC"

    def test_empty_tables(self) -> None:
        """ListTablesOutput should handle empty table list."""
        output = ListTablesOutput(tables=[], schema_name="EMPTY", count=0)
        assert output.tables == []
        assert output.count == 0

    def test_serialization_to_json(self) -> None:
        """ListTablesOutput should serialize to valid JSON for MCP transport."""
        output = ListTablesOutput(tables=[], schema_name="S", count=0)
        parsed = json.loads(output.model_dump_json())
        assert isinstance(parsed["tables"], list)
        assert parsed["schema_name"] == "S"


# === ColumnInfo ===


class TestColumnInfo:
    """Tests for ColumnInfo model."""

    def test_all_fields(self) -> None:
        """ColumnInfo should accept all fields including optional ones."""
        col = ColumnInfo(
            name="ORDER_ID",
            data_type="BIGINT",
            length=8,
            scale=None,
            nullable=False,
            default_value=None,
            position=1,
            comment="Primary key",
        )
        assert col.name == "ORDER_ID"
        assert col.data_type == "BIGINT"
        assert col.length == 8
        assert col.scale is None
        assert col.nullable is False
        assert col.default_value is None
        assert col.position == 1
        assert col.comment == "Primary key"

    def test_optional_fields_default_none(self) -> None:
        """ColumnInfo optional fields should default to None."""
        col = ColumnInfo(
            name="STATUS",
            data_type="NVARCHAR",
            nullable=True,
            position=3,
        )
        assert col.length is None
        assert col.scale is None
        assert col.default_value is None
        assert col.comment is None

    def test_decimal_column_with_length_and_scale(self) -> None:
        """ColumnInfo should handle DECIMAL columns with length and scale."""
        col = ColumnInfo(
            name="AMOUNT",
            data_type="DECIMAL",
            length=15,
            scale=2,
            nullable=False,
            position=5,
        )
        assert col.length == 15
        assert col.scale == 2

    def test_column_with_default_value(self) -> None:
        """ColumnInfo should store default value expressions."""
        col = ColumnInfo(
            name="CREATED_AT",
            data_type="TIMESTAMP",
            nullable=False,
            default_value="CURRENT_TIMESTAMP",
            position=10,
        )
        assert col.default_value == "CURRENT_TIMESTAMP"

    def test_serialization_to_dict(self) -> None:
        """ColumnInfo should serialize correctly, including None optional fields."""
        col = ColumnInfo(
            name="ID",
            data_type="INTEGER",
            nullable=False,
            position=1,
        )
        data = col.model_dump()
        assert data["name"] == "ID"
        assert data["length"] is None
        assert data["comment"] is None

    def test_serialization_to_json(self) -> None:
        """ColumnInfo should serialize to valid JSON."""
        col = ColumnInfo(
            name="ID",
            data_type="INTEGER",
            nullable=False,
            position=1,
            comment="Primary key",
        )
        parsed = json.loads(col.model_dump_json())
        assert parsed["comment"] == "Primary key"

    def test_missing_required_field_rejected(self) -> None:
        """ColumnInfo should reject missing required fields."""
        with pytest.raises(ValidationError):
            ColumnInfo(name="X", data_type="INT")  # type: ignore[call-arg]


# === IndexInfo ===


class TestIndexInfo:
    """Tests for IndexInfo model."""

    def test_valid_index(self) -> None:
        """IndexInfo should accept valid index data."""
        idx = IndexInfo(
            name="IDX_ORDERS_DATE",
            columns=["ORDER_DATE"],
            is_unique=False,
            index_type="CPBTREE",
        )
        assert idx.name == "IDX_ORDERS_DATE"
        assert idx.columns == ["ORDER_DATE"]
        assert idx.is_unique is False
        assert idx.index_type == "CPBTREE"

    def test_multi_column_unique_index(self) -> None:
        """IndexInfo should handle multi-column unique indexes."""
        idx = IndexInfo(
            name="UNQ_COMPOSITE",
            columns=["COL_A", "COL_B", "COL_C"],
            is_unique=True,
            index_type="BTREE",
        )
        assert len(idx.columns) == 3
        assert idx.is_unique is True

    def test_empty_columns_list(self) -> None:
        """IndexInfo should accept empty columns list (edge case)."""
        idx = IndexInfo(
            name="IDX_EMPTY",
            columns=[],
            is_unique=False,
            index_type="BTREE",
        )
        assert idx.columns == []

    def test_serialization_to_json(self) -> None:
        """IndexInfo should serialize to valid JSON."""
        idx = IndexInfo(
            name="IDX1",
            columns=["A", "B"],
            is_unique=True,
            index_type="INVERTED HASH",
        )
        parsed = json.loads(idx.model_dump_json())
        assert parsed["columns"] == ["A", "B"]
        assert parsed["index_type"] == "INVERTED HASH"


# === ConstraintInfo ===


class TestConstraintInfo:
    """Tests for ConstraintInfo model."""

    def test_primary_key_constraint(self) -> None:
        """ConstraintInfo should accept PRIMARY KEY constraint type."""
        c = ConstraintInfo(
            name="PK_ORDERS",
            constraint_type="PRIMARY KEY",
            columns=["ORDER_ID"],
        )
        assert c.constraint_type == "PRIMARY KEY"

    def test_unique_constraint(self) -> None:
        """ConstraintInfo should accept UNIQUE constraint type."""
        c = ConstraintInfo(
            name="UNQ_EMAIL",
            constraint_type="UNIQUE",
            columns=["EMAIL"],
        )
        assert c.constraint_type == "UNIQUE"

    def test_check_constraint(self) -> None:
        """ConstraintInfo should accept CHECK constraint type."""
        c = ConstraintInfo(
            name="CHK_STATUS",
            constraint_type="CHECK",
            columns=["STATUS"],
        )
        assert c.constraint_type == "CHECK"

    def test_invalid_constraint_type_rejected(self) -> None:
        """ConstraintInfo should reject invalid constraint types."""
        with pytest.raises(ValidationError):
            ConstraintInfo(
                name="FK_INVALID",
                constraint_type="FOREIGN KEY",  # type: ignore[arg-type]
                columns=["COL"],
            )

    def test_multi_column_constraint(self) -> None:
        """ConstraintInfo should handle composite constraints."""
        c = ConstraintInfo(
            name="PK_COMPOSITE",
            constraint_type="PRIMARY KEY",
            columns=["SCHEMA_NAME", "TABLE_NAME"],
        )
        assert len(c.columns) == 2

    def test_empty_columns_list(self) -> None:
        """ConstraintInfo should accept empty columns list (edge case)."""
        c = ConstraintInfo(
            name="CHK_EXPR",
            constraint_type="CHECK",
            columns=[],
        )
        assert c.columns == []

    def test_serialization_to_json(self) -> None:
        """ConstraintInfo should serialize to valid JSON."""
        c = ConstraintInfo(
            name="PK1",
            constraint_type="PRIMARY KEY",
            columns=["ID"],
        )
        parsed = json.loads(c.model_dump_json())
        assert parsed["constraint_type"] == "PRIMARY KEY"


# === DescribeTableInput ===


class TestDescribeTableInput:
    """Tests for DescribeTableInput model."""

    def test_required_fields(self) -> None:
        """DescribeTableInput should require table_name and schema_name."""
        inp = DescribeTableInput(table_name="ORDERS", schema_name="MY_SCHEMA")
        assert inp.table_name == "ORDERS"
        assert inp.schema_name == "MY_SCHEMA"

    def test_defaults(self) -> None:
        """DescribeTableInput should default indexes and constraints to True."""
        inp = DescribeTableInput(table_name="T", schema_name="S")
        assert inp.include_indexes is True
        assert inp.include_constraints is True

    def test_exclude_indexes_and_constraints(self) -> None:
        """DescribeTableInput should allow disabling indexes and constraints."""
        inp = DescribeTableInput(
            table_name="T",
            schema_name="S",
            include_indexes=False,
            include_constraints=False,
        )
        assert inp.include_indexes is False
        assert inp.include_constraints is False

    def test_missing_table_name_rejected(self) -> None:
        """DescribeTableInput should reject missing table_name."""
        with pytest.raises(ValidationError):
            DescribeTableInput(schema_name="S")  # type: ignore[call-arg]


# === DescribeTableOutput ===


class TestDescribeTableOutput:
    """Tests for DescribeTableOutput model."""

    def test_full_table_description(self) -> None:
        """DescribeTableOutput should hold complete table metadata."""
        output = DescribeTableOutput(
            table_name="ORDERS",
            schema_name="MY_SCHEMA",
            columns=[
                ColumnInfo(
                    name="ORDER_ID",
                    data_type="BIGINT",
                    nullable=False,
                    position=1,
                ),
                ColumnInfo(
                    name="CUSTOMER_ID",
                    data_type="INTEGER",
                    nullable=False,
                    position=2,
                ),
            ],
            indexes=[
                IndexInfo(
                    name="IDX_ORDER_CUSTOMER",
                    columns=["CUSTOMER_ID"],
                    is_unique=False,
                    index_type="CPBTREE",
                ),
            ],
            constraints=[
                ConstraintInfo(
                    name="PK_ORDERS",
                    constraint_type="PRIMARY KEY",
                    columns=["ORDER_ID"],
                ),
            ],
            is_view=False,
        )
        assert output.table_name == "ORDERS"
        assert len(output.columns) == 2
        assert len(output.indexes) == 1
        assert len(output.constraints) == 1
        assert output.is_view is False

    def test_view_description(self) -> None:
        """DescribeTableOutput should handle views with is_view=True."""
        output = DescribeTableOutput(
            table_name="V_ORDERS",
            schema_name="MY_SCHEMA",
            columns=[
                ColumnInfo(
                    name="ORDER_ID",
                    data_type="BIGINT",
                    nullable=False,
                    position=1,
                ),
            ],
            is_view=True,
        )
        assert output.is_view is True
        assert output.indexes == []
        assert output.constraints == []

    def test_empty_indexes_and_constraints_default(self) -> None:
        """DescribeTableOutput should default indexes and constraints to empty lists."""
        output = DescribeTableOutput(
            table_name="T",
            schema_name="S",
            columns=[
                ColumnInfo(name="C", data_type="INT", nullable=False, position=1),
            ],
        )
        assert output.indexes == []
        assert output.constraints == []
        assert output.is_view is False

    def test_serialization_to_json(self) -> None:
        """DescribeTableOutput should serialize to valid JSON for MCP transport."""
        output = DescribeTableOutput(
            table_name="T",
            schema_name="S",
            columns=[
                ColumnInfo(name="C", data_type="INT", nullable=False, position=1),
            ],
            is_view=True,
        )
        parsed = json.loads(output.model_dump_json())
        assert parsed["is_view"] is True
        assert isinstance(parsed["columns"], list)
        assert isinstance(parsed["indexes"], list)
        assert isinstance(parsed["constraints"], list)


# === GetSampleRowsInput ===


class TestGetSampleRowsInput:
    """Tests for GetSampleRowsInput model."""

    def test_required_fields(self) -> None:
        """GetSampleRowsInput should require table_name and schema_name."""
        inp = GetSampleRowsInput(table_name="ORDERS", schema_name="MY_SCHEMA")
        assert inp.table_name == "ORDERS"
        assert inp.schema_name == "MY_SCHEMA"

    def test_defaults(self) -> None:
        """GetSampleRowsInput should have sensible defaults."""
        inp = GetSampleRowsInput(table_name="T", schema_name="S")
        assert inp.limit == 5
        assert inp.columns is None
        assert inp.where_clause is None
        assert inp.randomize is False

    def test_limit_minimum(self) -> None:
        """GetSampleRowsInput should accept limit=1."""
        inp = GetSampleRowsInput(table_name="T", schema_name="S", limit=1)
        assert inp.limit == 1

    def test_limit_maximum(self) -> None:
        """GetSampleRowsInput should accept limit=100."""
        inp = GetSampleRowsInput(table_name="T", schema_name="S", limit=100)
        assert inp.limit == 100

    def test_limit_below_minimum_rejected(self) -> None:
        """GetSampleRowsInput should reject limit < 1."""
        with pytest.raises(ValidationError):
            GetSampleRowsInput(table_name="T", schema_name="S", limit=0)

    def test_limit_above_maximum_rejected(self) -> None:
        """GetSampleRowsInput should reject limit > 100."""
        with pytest.raises(ValidationError):
            GetSampleRowsInput(table_name="T", schema_name="S", limit=101)

    def test_columns_selection(self) -> None:
        """GetSampleRowsInput should accept a column list."""
        inp = GetSampleRowsInput(
            table_name="T",
            schema_name="S",
            columns=["ORDER_ID", "CREATED_AT"],
        )
        assert inp.columns == ["ORDER_ID", "CREATED_AT"]

    def test_where_clause(self) -> None:
        """GetSampleRowsInput should accept a where clause."""
        inp = GetSampleRowsInput(
            table_name="T",
            schema_name="S",
            where_clause="STATUS = 'ACTIVE'",
        )
        assert inp.where_clause == "STATUS = 'ACTIVE'"

    def test_randomize_true(self) -> None:
        """GetSampleRowsInput should accept randomize=True."""
        inp = GetSampleRowsInput(table_name="T", schema_name="S", randomize=True)
        assert inp.randomize is True


# === SampleRowsOutput ===


class TestSampleRowsOutput:
    """Tests for SampleRowsOutput model."""

    def test_valid_output(self) -> None:
        """SampleRowsOutput should hold sample data with metadata."""
        output = SampleRowsOutput(
            table_name="ORDERS",
            schema_name="MY_SCHEMA",
            columns=["ORDER_ID", "STATUS"],
            rows=[
                {"ORDER_ID": 1, "STATUS": "OPEN"},
                {"ORDER_ID": 2, "STATUS": "CLOSED"},
            ],
            row_count=2,
            total_count=1000,
        )
        assert output.table_name == "ORDERS"
        assert len(output.rows) == 2
        assert output.row_count == 2
        assert output.total_count == 1000

    def test_empty_rows(self) -> None:
        """SampleRowsOutput should handle empty tables."""
        output = SampleRowsOutput(
            table_name="EMPTY_TABLE",
            schema_name="S",
            columns=["ID"],
            rows=[],
            row_count=0,
            total_count=0,
        )
        assert output.rows == []
        assert output.row_count == 0

    def test_serialization_to_json(self) -> None:
        """SampleRowsOutput should serialize to valid JSON for MCP transport."""
        output = SampleRowsOutput(
            table_name="T",
            schema_name="S",
            columns=["A", "B"],
            rows=[{"A": 1, "B": "x"}, {"A": 2, "B": "y"}],
            row_count=2,
            total_count=50,
        )
        parsed = json.loads(output.model_dump_json())
        assert isinstance(parsed["rows"], list)
        assert parsed["row_count"] == 2
        assert parsed["total_count"] == 50

    def test_serialization_to_dict(self) -> None:
        """SampleRowsOutput should serialize rows as list of dicts."""
        output = SampleRowsOutput(
            table_name="T",
            schema_name="S",
            columns=["ID"],
            rows=[{"ID": 42}],
            row_count=1,
            total_count=100,
        )
        data = output.model_dump()
        assert data["rows"] == [{"ID": 42}]

    def test_rows_with_none_values(self) -> None:
        """SampleRowsOutput should handle None values in rows."""
        output = SampleRowsOutput(
            table_name="T",
            schema_name="S",
            columns=["ID", "COMMENT"],
            rows=[{"ID": 1, "COMMENT": None}],
            row_count=1,
            total_count=10,
        )
        parsed = json.loads(output.model_dump_json())
        assert parsed["rows"][0]["COMMENT"] is None


# === Cross-Model Integration ===


class TestModelImports:
    """Tests that all models are importable from the models package."""

    def test_schema_models_importable_from_package(self) -> None:
        """All Layer 1 models should be importable from models package."""
        from mamba_mcp_hana.models import (  # noqa: F401
            ColumnInfo,
            ConstraintInfo,
            DescribeTableInput,
            DescribeTableOutput,
            GetSampleRowsInput,
            IndexInfo,
            ListSchemasInput,
            ListSchemasOutput,
            ListTablesInput,
            ListTablesOutput,
            SampleRowsOutput,
            SchemaInfo,
            TableInfo,
        )

    def test_all_exports_in_package(self) -> None:
        """All Layer 1 models should be in the models __all__."""
        from mamba_mcp_hana import models

        expected = [
            "ListSchemasInput",
            "ListSchemasOutput",
            "SchemaInfo",
            "ListTablesInput",
            "ListTablesOutput",
            "TableInfo",
            "DescribeTableInput",
            "DescribeTableOutput",
            "ColumnInfo",
            "IndexInfo",
            "ConstraintInfo",
            "GetSampleRowsInput",
            "SampleRowsOutput",
        ]
        for name in expected:
            assert name in models.__all__, f"{name} not in models.__all__"
