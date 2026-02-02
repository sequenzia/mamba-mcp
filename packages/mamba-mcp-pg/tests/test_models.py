"""Tests for Pydantic models: schema, relationships, and results."""

import pytest
from mamba_mcp_pg.models import (
    ColumnInfo,
    ConstraintInfo,
    DescribeTableOutput,
    ErrorDetail,
    ExecuteQueryOutput,
    ExplainQueryInput,
    ExplainQueryOutput,
    FindJoinPathInput,
    FindJoinPathOutput,
    ForeignKeyRef,
    ForeignKeyRelation,
    GetForeignKeysOutput,
    GetSampleRowsInput,
    GetSampleRowsOutput,
    IndexInfo,
    JoinPath,
    JoinStep,
    ListSchemasOutput,
    ListTablesOutput,
    QueryColumn,
    SchemaInfo,
    TableInfo,
    ToolError,
)
from pydantic import ValidationError


class TestSchemaModels:
    """Tests for schema discovery models (Layer 1)."""

    def test_schema_info_basic(self) -> None:
        """Test SchemaInfo construction with all required fields."""
        info = SchemaInfo(name="public", owner="postgres", table_count=10)
        assert info.name == "public"
        assert info.owner == "postgres"
        assert info.description is None
        assert info.table_count == 10

    def test_schema_info_with_description(self) -> None:
        """Test SchemaInfo with optional description."""
        info = SchemaInfo(
            name="analytics", owner="admin", description="Analytics tables", table_count=5
        )
        assert info.description == "Analytics tables"

    def test_schema_info_model_dump(self) -> None:
        """Test SchemaInfo serialization to dict."""
        info = SchemaInfo(name="public", owner="postgres", table_count=3)
        data = info.model_dump()
        assert data == {
            "name": "public",
            "owner": "postgres",
            "description": None,
            "table_count": 3,
        }

    def test_list_schemas_output(self) -> None:
        """Test ListSchemasOutput with nested SchemaInfo list."""
        schemas = [
            SchemaInfo(name="public", owner="postgres", table_count=10),
            SchemaInfo(name="analytics", owner="admin", table_count=5),
        ]
        output = ListSchemasOutput(schemas=schemas, total_count=2)
        assert output.total_count == 2
        assert len(output.schemas) == 2
        assert output.schemas[0].name == "public"

    def test_list_schemas_output_empty(self) -> None:
        """Test ListSchemasOutput with no schemas."""
        output = ListSchemasOutput(schemas=[], total_count=0)
        assert output.schemas == []
        assert output.total_count == 0

    def test_table_info_basic(self) -> None:
        """Test TableInfo with required fields and defaults."""
        table = TableInfo(
            name="users",
            schema_name="public",
            type="table",
            estimated_row_count=1000,
            has_primary_key=True,
            column_count=8,
        )
        assert table.name == "users"
        assert table.type == "table"
        assert table.description is None
        assert table.size_bytes is None
        assert table.size_pretty is None
        assert table.has_primary_key is True

    def test_table_info_with_size(self) -> None:
        """Test TableInfo with optional size fields populated."""
        table = TableInfo(
            name="orders",
            schema_name="public",
            type="table",
            estimated_row_count=50000,
            size_bytes=1048576,
            size_pretty="1 MB",
            has_primary_key=True,
            column_count=12,
        )
        assert table.size_bytes == 1048576
        assert table.size_pretty == "1 MB"

    def test_table_info_view(self) -> None:
        """Test TableInfo representing a view."""
        view = TableInfo(
            name="active_users",
            schema_name="public",
            type="view",
            estimated_row_count=500,
            has_primary_key=False,
            column_count=4,
        )
        assert view.type == "view"
        assert view.has_primary_key is False
        assert view.size_bytes is None

    def test_list_tables_output(self) -> None:
        """Test ListTablesOutput with nested TableInfo list."""
        tables = [
            TableInfo(
                name="users",
                schema_name="public",
                type="table",
                estimated_row_count=100,
                has_primary_key=True,
                column_count=5,
            ),
        ]
        output = ListTablesOutput(tables=tables, schema_name="public", total_count=1)
        assert output.schema_name == "public"
        assert output.total_count == 1
        assert output.tables[0].name == "users"

    def test_column_info_minimal(self) -> None:
        """Test ColumnInfo with only required fields."""
        col = ColumnInfo(name="id", data_type="integer", is_nullable=False)
        assert col.name == "id"
        assert col.data_type == "integer"
        assert col.is_nullable is False
        assert col.default_value is None
        assert col.is_primary_key is False
        assert col.is_unique is False
        assert col.foreign_key is None
        assert col.character_maximum_length is None
        assert col.numeric_precision is None
        assert col.numeric_scale is None

    def test_column_info_full(self) -> None:
        """Test ColumnInfo with all optional fields populated."""
        fk = ForeignKeyRef(
            constraint_name="fk_order_user",
            referenced_schema="public",
            referenced_table="users",
            referenced_column="id",
            on_update="NO ACTION",
            on_delete="CASCADE",
        )
        col = ColumnInfo(
            name="user_id",
            data_type="integer",
            is_nullable=False,
            default_value=None,
            description="Reference to user",
            is_primary_key=False,
            is_unique=False,
            foreign_key=fk,
            numeric_precision=32,
            numeric_scale=0,
        )
        assert col.foreign_key is not None
        assert col.foreign_key.referenced_table == "users"
        assert col.foreign_key.on_delete == "CASCADE"
        assert col.description == "Reference to user"

    def test_column_info_varchar(self) -> None:
        """Test ColumnInfo for a varchar column with character_maximum_length."""
        col = ColumnInfo(
            name="email",
            data_type="character varying",
            is_nullable=False,
            is_unique=True,
            character_maximum_length=255,
        )
        assert col.character_maximum_length == 255
        assert col.is_unique is True

    def test_foreign_key_ref(self) -> None:
        """Test ForeignKeyRef construction."""
        fk = ForeignKeyRef(
            constraint_name="fk_orders_users",
            referenced_schema="public",
            referenced_table="users",
            referenced_column="id",
            on_update="NO ACTION",
            on_delete="SET NULL",
        )
        assert fk.constraint_name == "fk_orders_users"
        assert fk.on_delete == "SET NULL"

    def test_index_info(self) -> None:
        """Test IndexInfo construction."""
        idx = IndexInfo(
            name="idx_users_email",
            columns=["email"],
            is_unique=True,
            is_primary=False,
            index_type="btree",
        )
        assert idx.name == "idx_users_email"
        assert idx.columns == ["email"]
        assert idx.is_unique is True
        assert idx.is_primary is False
        assert idx.description is None

    def test_index_info_composite(self) -> None:
        """Test IndexInfo with multiple columns and description."""
        idx = IndexInfo(
            name="idx_orders_user_date",
            columns=["user_id", "created_at"],
            is_unique=False,
            is_primary=False,
            index_type="btree",
            description="Index for user order lookups",
        )
        assert len(idx.columns) == 2
        assert idx.description == "Index for user order lookups"

    def test_constraint_info_primary_key(self) -> None:
        """Test ConstraintInfo for a primary key constraint."""
        constraint = ConstraintInfo(
            name="users_pkey",
            type="PRIMARY KEY",
            columns=["id"],
        )
        assert constraint.type == "PRIMARY KEY"
        assert constraint.definition is None
        assert constraint.referenced_table is None

    def test_constraint_info_foreign_key(self) -> None:
        """Test ConstraintInfo for a foreign key constraint."""
        constraint = ConstraintInfo(
            name="fk_orders_users",
            type="FOREIGN KEY",
            columns=["user_id"],
            referenced_table="users",
        )
        assert constraint.referenced_table == "users"

    def test_constraint_info_check(self) -> None:
        """Test ConstraintInfo for a check constraint with definition."""
        constraint = ConstraintInfo(
            name="chk_positive_amount",
            type="CHECK",
            columns=["amount"],
            definition="(amount > 0)",
        )
        assert constraint.definition == "(amount > 0)"

    def test_describe_table_output_minimal(self) -> None:
        """Test DescribeTableOutput with only required fields."""
        col = ColumnInfo(name="id", data_type="integer", is_nullable=False)
        output = DescribeTableOutput(
            table_name="users",
            schema_name="public",
            type="table",
            columns=[col],
            estimated_row_count=100,
        )
        assert output.table_name == "users"
        assert output.description is None
        assert output.indexes is None
        assert output.constraints is None
        assert output.size_pretty is None

    def test_describe_table_output_full(self) -> None:
        """Test DescribeTableOutput with indexes and constraints."""
        col = ColumnInfo(name="id", data_type="integer", is_nullable=False, is_primary_key=True)
        idx = IndexInfo(
            name="users_pkey", columns=["id"], is_unique=True, is_primary=True, index_type="btree"
        )
        constraint = ConstraintInfo(name="users_pkey", type="PRIMARY KEY", columns=["id"])
        output = DescribeTableOutput(
            table_name="users",
            schema_name="public",
            type="table",
            description="Application users",
            columns=[col],
            indexes=[idx],
            constraints=[constraint],
            estimated_row_count=1000,
            size_pretty="128 kB",
        )
        assert output.description == "Application users"
        assert len(output.indexes) == 1
        assert len(output.constraints) == 1
        assert output.size_pretty == "128 kB"

    def test_get_sample_rows_output(self) -> None:
        """Test GetSampleRowsOutput construction."""
        output = GetSampleRowsOutput(
            table_name="users",
            schema_name="public",
            columns=["id", "name"],
            rows=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            row_count=2,
            total_table_rows=100,
        )
        assert output.row_count == 2
        assert output.note is None
        assert output.rows[0]["name"] == "Alice"

    def test_get_sample_rows_output_with_note(self) -> None:
        """Test GetSampleRowsOutput with a note."""
        output = GetSampleRowsOutput(
            table_name="users",
            schema_name="public",
            columns=["id"],
            rows=[{"id": 1}],
            row_count=1,
            total_table_rows=50,
            note="randomized",
        )
        assert output.note == "randomized"

    def test_get_sample_rows_output_model_dump(self) -> None:
        """Test GetSampleRowsOutput serialization includes all fields."""
        output = GetSampleRowsOutput(
            table_name="t",
            schema_name="s",
            columns=["c"],
            rows=[],
            row_count=0,
            total_table_rows=0,
        )
        data = output.model_dump()
        assert "table_name" in data
        assert "schema_name" in data
        assert "columns" in data
        assert "rows" in data
        assert "row_count" in data
        assert "total_table_rows" in data
        assert "note" in data


class TestRelationshipModels:
    """Tests for relationship discovery models (Layer 2)."""

    def test_foreign_key_relation(self) -> None:
        """Test ForeignKeyRelation construction with multi-column FK."""
        fk = ForeignKeyRelation(
            constraint_name="fk_order_items_orders",
            from_schema="public",
            from_table="order_items",
            from_columns=["order_id"],
            to_schema="public",
            to_table="orders",
            to_columns=["id"],
            on_update="NO ACTION",
            on_delete="CASCADE",
        )
        assert fk.constraint_name == "fk_order_items_orders"
        assert fk.from_columns == ["order_id"]
        assert fk.to_columns == ["id"]
        assert fk.on_delete == "CASCADE"

    def test_foreign_key_relation_composite(self) -> None:
        """Test ForeignKeyRelation with composite key columns."""
        fk = ForeignKeyRelation(
            constraint_name="fk_composite",
            from_schema="public",
            from_table="child",
            from_columns=["parent_a", "parent_b"],
            to_schema="public",
            to_table="parent",
            to_columns=["col_a", "col_b"],
            on_update="CASCADE",
            on_delete="RESTRICT",
        )
        assert len(fk.from_columns) == 2
        assert len(fk.to_columns) == 2

    def test_get_foreign_keys_output(self) -> None:
        """Test GetForeignKeysOutput with outgoing and incoming FKs."""
        outgoing = ForeignKeyRelation(
            constraint_name="fk_orders_users",
            from_schema="public",
            from_table="orders",
            from_columns=["user_id"],
            to_schema="public",
            to_table="users",
            to_columns=["id"],
            on_update="NO ACTION",
            on_delete="CASCADE",
        )
        incoming = ForeignKeyRelation(
            constraint_name="fk_items_orders",
            from_schema="public",
            from_table="order_items",
            from_columns=["order_id"],
            to_schema="public",
            to_table="orders",
            to_columns=["id"],
            on_update="NO ACTION",
            on_delete="CASCADE",
        )
        output = GetForeignKeysOutput(
            table_name="orders",
            schema_name="public",
            outgoing=[outgoing],
            incoming=[incoming],
            outgoing_count=1,
            incoming_count=1,
        )
        assert output.outgoing_count == 1
        assert output.incoming_count == 1
        assert output.outgoing[0].to_table == "users"
        assert output.incoming[0].from_table == "order_items"

    def test_get_foreign_keys_output_empty(self) -> None:
        """Test GetForeignKeysOutput with no relationships."""
        output = GetForeignKeysOutput(
            table_name="standalone",
            schema_name="public",
            outgoing=[],
            incoming=[],
            outgoing_count=0,
            incoming_count=0,
        )
        assert output.outgoing == []
        assert output.incoming == []

    def test_join_step(self) -> None:
        """Test JoinStep construction."""
        step = JoinStep(
            from_table="orders",
            from_schema="public",
            from_column="user_id",
            to_table="users",
            to_schema="public",
            to_column="id",
            join_type="INNER JOIN",
            constraint_name="fk_orders_users",
        )
        assert step.from_table == "orders"
        assert step.to_table == "users"
        assert step.join_type == "INNER JOIN"

    def test_join_path(self) -> None:
        """Test JoinPath with a single step."""
        step = JoinStep(
            from_table="orders",
            from_schema="public",
            from_column="user_id",
            to_table="users",
            to_schema="public",
            to_column="id",
            join_type="INNER JOIN",
            constraint_name="fk_orders_users",
        )
        path = JoinPath(
            steps=[step],
            depth=1,
            sql_example="JOIN public.users ON orders.user_id = users.id",
        )
        assert path.depth == 1
        assert len(path.steps) == 1
        assert "JOIN" in path.sql_example

    def test_join_path_multi_step(self) -> None:
        """Test JoinPath with multiple join steps."""
        step1 = JoinStep(
            from_table="order_items",
            from_schema="public",
            from_column="order_id",
            to_table="orders",
            to_schema="public",
            to_column="id",
            join_type="INNER JOIN",
            constraint_name="fk_items_orders",
        )
        step2 = JoinStep(
            from_table="orders",
            from_schema="public",
            from_column="user_id",
            to_table="users",
            to_schema="public",
            to_column="id",
            join_type="INNER JOIN",
            constraint_name="fk_orders_users",
        )
        path = JoinPath(
            steps=[step1, step2],
            depth=2,
            sql_example=(
                "JOIN public.orders ON order_items.order_id = orders.id "
                "JOIN public.users ON orders.user_id = users.id"
            ),
        )
        assert path.depth == 2
        assert len(path.steps) == 2

    def test_find_join_path_output(self) -> None:
        """Test FindJoinPathOutput with paths found."""
        step = JoinStep(
            from_table="orders",
            from_schema="public",
            from_column="user_id",
            to_table="users",
            to_schema="public",
            to_column="id",
            join_type="INNER JOIN",
            constraint_name="fk_orders_users",
        )
        path = JoinPath(
            steps=[step],
            depth=1,
            sql_example="JOIN public.users ON orders.user_id = users.id",
        )
        output = FindJoinPathOutput(
            from_table="orders",
            to_table="users",
            paths=[path],
            paths_found=1,
        )
        assert output.paths_found == 1
        assert output.note is None

    def test_find_join_path_output_with_note(self) -> None:
        """Test FindJoinPathOutput with a note about multiple paths."""
        output = FindJoinPathOutput(
            from_table="a",
            to_table="b",
            paths=[],
            paths_found=0,
            note="No path found within max_depth",
        )
        assert output.note == "No path found within max_depth"
        assert output.paths == []

    def test_find_join_path_output_model_dump(self) -> None:
        """Test FindJoinPathOutput serialization."""
        output = FindJoinPathOutput(
            from_table="a",
            to_table="b",
            paths=[],
            paths_found=0,
        )
        data = output.model_dump()
        assert data["from_table"] == "a"
        assert data["to_table"] == "b"
        assert data["paths"] == []
        assert data["paths_found"] == 0
        assert data["note"] is None


class TestQueryModels:
    """Tests for query execution models (Layer 3)."""

    def test_query_column(self) -> None:
        """Test QueryColumn construction."""
        col = QueryColumn(name="id", data_type="integer")
        assert col.name == "id"
        assert col.data_type == "integer"

    def test_execute_query_output(self) -> None:
        """Test ExecuteQueryOutput construction."""
        output = ExecuteQueryOutput(
            columns=[QueryColumn(name="id", data_type="integer")],
            rows=[{"id": 1}, {"id": 2}],
            row_count=2,
            has_more=False,
            execution_time_ms=12.5,
            query_hash="abc123",
        )
        assert output.row_count == 2
        assert output.has_more is False
        assert output.execution_time_ms == 12.5
        assert output.query_hash == "abc123"

    def test_execute_query_output_with_truncation(self) -> None:
        """Test ExecuteQueryOutput when results are truncated."""
        output = ExecuteQueryOutput(
            columns=[QueryColumn(name="val", data_type="text")],
            rows=[{"val": "a"}],
            row_count=1,
            has_more=True,
            execution_time_ms=0.5,
            query_hash="def456",
        )
        assert output.has_more is True

    def test_execute_query_output_model_dump(self) -> None:
        """Test ExecuteQueryOutput serialization."""
        output = ExecuteQueryOutput(
            columns=[QueryColumn(name="x", data_type="int")],
            rows=[],
            row_count=0,
            has_more=False,
            execution_time_ms=1.0,
            query_hash="hash",
        )
        data = output.model_dump()
        assert data["columns"] == [{"name": "x", "data_type": "int"}]
        assert data["rows"] == []
        assert data["has_more"] is False

    def test_explain_query_input_defaults(self) -> None:
        """Test ExplainQueryInput default values."""
        inp = ExplainQueryInput(sql="SELECT 1")
        assert inp.params is None
        assert inp.analyze is False
        assert inp.format == "text"
        assert inp.verbose is False
        assert inp.buffers is False

    def test_explain_query_input_format_text(self) -> None:
        """Test ExplainQueryInput accepts 'text' format."""
        inp = ExplainQueryInput(sql="SELECT 1", format="text")
        assert inp.format == "text"

    def test_explain_query_input_format_json(self) -> None:
        """Test ExplainQueryInput accepts 'json' format."""
        inp = ExplainQueryInput(sql="SELECT 1", format="json")
        assert inp.format == "json"

    def test_explain_query_input_format_yaml(self) -> None:
        """Test ExplainQueryInput accepts 'yaml' format."""
        inp = ExplainQueryInput(sql="SELECT 1", format="yaml")
        assert inp.format == "yaml"

    def test_explain_query_input_with_analyze(self) -> None:
        """Test ExplainQueryInput with analyze and buffers enabled."""
        inp = ExplainQueryInput(
            sql="SELECT * FROM users",
            analyze=True,
            verbose=True,
            buffers=True,
            format="json",
        )
        assert inp.analyze is True
        assert inp.verbose is True
        assert inp.buffers is True

    def test_explain_query_output_minimal(self) -> None:
        """Test ExplainQueryOutput with only required fields."""
        output = ExplainQueryOutput(plan="Seq Scan on users", format="text")
        assert output.plan == "Seq Scan on users"
        assert output.format == "text"
        assert output.estimated_cost is None
        assert output.estimated_rows is None
        assert output.actual_time_ms is None
        assert output.warnings is None

    def test_explain_query_output_full(self) -> None:
        """Test ExplainQueryOutput with all optional fields populated."""
        output = ExplainQueryOutput(
            plan={"Plan": {"Node Type": "Seq Scan"}},
            format="json",
            estimated_cost=100.5,
            estimated_rows=1000,
            actual_time_ms=45.2,
            warnings=["Sequential scan on large table"],
        )
        assert isinstance(output.plan, dict)
        assert output.estimated_cost == 100.5
        assert output.estimated_rows == 1000
        assert output.actual_time_ms == 45.2
        assert len(output.warnings) == 1

    def test_explain_query_output_plan_as_list(self) -> None:
        """Test ExplainQueryOutput accepts a list plan (JSON format returns a list)."""
        output = ExplainQueryOutput(
            plan=[{"Plan": {"Node Type": "Seq Scan"}}],
            format="json",
        )
        assert isinstance(output.plan, list)


class TestErrorModels:
    """Tests for error response models."""

    def test_error_detail_minimal(self) -> None:
        """Test ErrorDetail with only required fields."""
        err = ErrorDetail(code="SCHEMA_NOT_FOUND", message="Schema 'foo' not found")
        assert err.code == "SCHEMA_NOT_FOUND"
        assert err.message == "Schema 'foo' not found"
        assert err.suggestion is None
        assert err.context is None

    def test_error_detail_full(self) -> None:
        """Test ErrorDetail with all optional fields populated."""
        err = ErrorDetail(
            code="TABLE_NOT_FOUND",
            message="Table 'orders' not found in schema 'public'",
            suggestion="Did you mean 'order_items'?",
            context={"schema": "public", "available_tables": ["users", "order_items"]},
        )
        assert err.suggestion == "Did you mean 'order_items'?"
        assert err.context["schema"] == "public"

    def test_error_detail_model_dump(self) -> None:
        """Test ErrorDetail serialization."""
        err = ErrorDetail(code="ERR", message="msg")
        data = err.model_dump()
        assert data == {
            "code": "ERR",
            "message": "msg",
            "suggestion": None,
            "context": None,
        }

    def test_tool_error_minimal(self) -> None:
        """Test ToolError with nested ErrorDetail and no input."""
        err = ToolError(
            error=ErrorDetail(code="QUERY_ERROR", message="Syntax error"),
            tool_name="execute_query",
        )
        assert err.tool_name == "execute_query"
        assert err.error.code == "QUERY_ERROR"
        assert err.input_received is None

    def test_tool_error_with_input(self) -> None:
        """Test ToolError with input_received for debugging."""
        err = ToolError(
            error=ErrorDetail(
                code="SCHEMA_NOT_FOUND",
                message="Schema 'foo' not found",
                suggestion="Did you mean 'public'?",
            ),
            tool_name="list_tables",
            input_received={"schema_name": "foo"},
        )
        assert err.input_received == {"schema_name": "foo"}
        assert err.error.suggestion == "Did you mean 'public'?"

    def test_tool_error_model_dump(self) -> None:
        """Test ToolError serialization preserves nested structure."""
        err = ToolError(
            error=ErrorDetail(code="ERR", message="fail"),
            tool_name="test_tool",
        )
        data = err.model_dump()
        assert data["tool_name"] == "test_tool"
        assert data["error"]["code"] == "ERR"
        assert data["error"]["message"] == "fail"
        assert data["input_received"] is None


class TestInputValidation:
    """Tests for field validation constraints on input models."""

    def test_get_sample_rows_input_defaults(self) -> None:
        """Test GetSampleRowsInput default values."""
        inp = GetSampleRowsInput(table_name="users")
        assert inp.schema_name == "public"
        assert inp.limit == 5
        assert inp.columns is None
        assert inp.where_clause is None
        assert inp.randomize is False

    def test_get_sample_rows_input_limit_min(self) -> None:
        """Test GetSampleRowsInput accepts limit=1 (minimum)."""
        inp = GetSampleRowsInput(table_name="users", limit=1)
        assert inp.limit == 1

    def test_get_sample_rows_input_limit_max(self) -> None:
        """Test GetSampleRowsInput accepts limit=100 (maximum)."""
        inp = GetSampleRowsInput(table_name="users", limit=100)
        assert inp.limit == 100

    def test_get_sample_rows_input_limit_below_min(self) -> None:
        """Test GetSampleRowsInput rejects limit=0 (below minimum)."""
        with pytest.raises(ValidationError) as exc_info:
            GetSampleRowsInput(table_name="users", limit=0)
        errors = exc_info.value.errors()
        assert any(e["type"] == "greater_than_equal" for e in errors)

    def test_get_sample_rows_input_limit_above_max(self) -> None:
        """Test GetSampleRowsInput rejects limit=101 (above maximum)."""
        with pytest.raises(ValidationError) as exc_info:
            GetSampleRowsInput(table_name="users", limit=101)
        errors = exc_info.value.errors()
        assert any(e["type"] == "less_than_equal" for e in errors)

    def test_get_sample_rows_input_limit_negative(self) -> None:
        """Test GetSampleRowsInput rejects negative limit."""
        with pytest.raises(ValidationError):
            GetSampleRowsInput(table_name="users", limit=-1)

    def test_get_sample_rows_input_with_options(self) -> None:
        """Test GetSampleRowsInput with all optional fields set."""
        inp = GetSampleRowsInput(
            table_name="orders",
            schema_name="sales",
            limit=50,
            columns=["id", "total"],
            where_clause="total > 100",
            randomize=True,
        )
        assert inp.schema_name == "sales"
        assert inp.limit == 50
        assert inp.columns == ["id", "total"]
        assert inp.where_clause == "total > 100"
        assert inp.randomize is True

    def test_find_join_path_input_defaults(self) -> None:
        """Test FindJoinPathInput default values."""
        inp = FindJoinPathInput(from_table="orders", to_table="users")
        assert inp.from_schema == "public"
        assert inp.to_schema == "public"
        assert inp.max_depth == 4

    def test_find_join_path_input_max_depth_min(self) -> None:
        """Test FindJoinPathInput accepts max_depth=1 (minimum)."""
        inp = FindJoinPathInput(from_table="a", to_table="b", max_depth=1)
        assert inp.max_depth == 1

    def test_find_join_path_input_max_depth_max(self) -> None:
        """Test FindJoinPathInput accepts max_depth=6 (maximum)."""
        inp = FindJoinPathInput(from_table="a", to_table="b", max_depth=6)
        assert inp.max_depth == 6

    def test_find_join_path_input_max_depth_below_min(self) -> None:
        """Test FindJoinPathInput rejects max_depth=0 (below minimum)."""
        with pytest.raises(ValidationError) as exc_info:
            FindJoinPathInput(from_table="a", to_table="b", max_depth=0)
        errors = exc_info.value.errors()
        assert any(e["type"] == "greater_than_equal" for e in errors)

    def test_find_join_path_input_max_depth_above_max(self) -> None:
        """Test FindJoinPathInput rejects max_depth=7 (above maximum)."""
        with pytest.raises(ValidationError) as exc_info:
            FindJoinPathInput(from_table="a", to_table="b", max_depth=7)
        errors = exc_info.value.errors()
        assert any(e["type"] == "less_than_equal" for e in errors)

    def test_explain_query_input_format_invalid(self) -> None:
        """Test ExplainQueryInput rejects invalid format values."""
        with pytest.raises(ValidationError) as exc_info:
            ExplainQueryInput(sql="SELECT 1", format="xml")
        errors = exc_info.value.errors()
        assert any(e["type"] == "string_pattern_mismatch" for e in errors)

    def test_explain_query_input_format_invalid_empty(self) -> None:
        """Test ExplainQueryInput rejects empty string format."""
        with pytest.raises(ValidationError):
            ExplainQueryInput(sql="SELECT 1", format="")

    def test_explain_query_input_format_invalid_case(self) -> None:
        """Test ExplainQueryInput rejects uppercase format (pattern is case-sensitive)."""
        with pytest.raises(ValidationError):
            ExplainQueryInput(sql="SELECT 1", format="TEXT")

    @pytest.mark.parametrize("fmt", ["text", "json", "yaml"])
    def test_explain_query_input_valid_formats(self, fmt: str) -> None:
        """Test ExplainQueryInput accepts all valid format values."""
        inp = ExplainQueryInput(sql="SELECT 1", format=fmt)
        assert inp.format == fmt

    @pytest.mark.parametrize("fmt", ["xml", "csv", "html", "TEXT", "Json", ""])
    def test_explain_query_input_invalid_formats(self, fmt: str) -> None:
        """Test ExplainQueryInput rejects various invalid format values."""
        with pytest.raises(ValidationError):
            ExplainQueryInput(sql="SELECT 1", format=fmt)

    @pytest.mark.parametrize("limit", [1, 5, 50, 100])
    def test_get_sample_rows_input_valid_limits(self, limit: int) -> None:
        """Test GetSampleRowsInput accepts valid limit values."""
        inp = GetSampleRowsInput(table_name="t", limit=limit)
        assert inp.limit == limit

    @pytest.mark.parametrize("limit", [-10, -1, 0, 101, 200, 1000])
    def test_get_sample_rows_input_invalid_limits(self, limit: int) -> None:
        """Test GetSampleRowsInput rejects out-of-range limit values."""
        with pytest.raises(ValidationError):
            GetSampleRowsInput(table_name="t", limit=limit)

    @pytest.mark.parametrize("depth", [1, 2, 3, 4, 5, 6])
    def test_find_join_path_input_valid_depths(self, depth: int) -> None:
        """Test FindJoinPathInput accepts valid max_depth values."""
        inp = FindJoinPathInput(from_table="a", to_table="b", max_depth=depth)
        assert inp.max_depth == depth

    @pytest.mark.parametrize("depth", [-1, 0, 7, 10, 100])
    def test_find_join_path_input_invalid_depths(self, depth: int) -> None:
        """Test FindJoinPathInput rejects out-of-range max_depth values."""
        with pytest.raises(ValidationError):
            FindJoinPathInput(from_table="a", to_table="b", max_depth=depth)
