"""Tests for Layer 3 query execution Pydantic models."""

import json

import pytest
from mamba_mcp_sap_hana.models.query import (
    MAX_SQL_LENGTH,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    ExplainPlanNode,
    ExplainQueryInput,
    ExplainQueryOutput,
    QueryResult,
)


class TestExecuteQueryInput:
    """Tests for ExecuteQueryInput validation."""

    def test_creates_with_minimal_fields(self) -> None:
        """Should accept just a SQL string with defaults."""
        inp = ExecuteQueryInput(sql="SELECT 1 FROM DUMMY")
        assert inp.sql == "SELECT 1 FROM DUMMY"
        assert inp.params is None
        assert inp.limit == 1000
        assert inp.timeout_ms is None

    def test_creates_with_all_fields(self) -> None:
        """Should accept all fields including params and timeout."""
        inp = ExecuteQueryInput(
            sql="SELECT * FROM USERS WHERE ID = ?",
            params=[42],
            limit=500,
            timeout_ms=5000,
        )
        assert inp.sql == "SELECT * FROM USERS WHERE ID = ?"
        assert inp.params == [42]
        assert inp.limit == 500
        assert inp.timeout_ms == 5000

    def test_accepts_named_params_as_dict(self) -> None:
        """Should accept named parameters as a dict."""
        inp = ExecuteQueryInput(
            sql="SELECT * FROM USERS WHERE NAME = :name",
            params={"name": "Alice"},
        )
        assert inp.params == {"name": "Alice"}

    def test_accepts_positional_params_as_list(self) -> None:
        """Should accept positional parameters as a list."""
        inp = ExecuteQueryInput(
            sql="SELECT * FROM USERS WHERE ID = ? AND STATUS = ?",
            params=[1, "active"],
        )
        assert inp.params == [1, "active"]

    def test_rejects_empty_sql(self) -> None:
        """Should reject empty SQL string."""
        with pytest.raises(Exception):
            ExecuteQueryInput(sql="")

    def test_rejects_whitespace_only_sql(self) -> None:
        """Should reject SQL that is only whitespace."""
        with pytest.raises(Exception):
            ExecuteQueryInput(sql="   \n\t  ")

    def test_rejects_sql_exceeding_max_length(self) -> None:
        """Should reject SQL longer than MAX_SQL_LENGTH."""
        long_sql = "SELECT " + "x" * MAX_SQL_LENGTH
        with pytest.raises(Exception):
            ExecuteQueryInput(sql=long_sql)

    def test_accepts_sql_at_max_length(self) -> None:
        """Should accept SQL exactly at MAX_SQL_LENGTH."""
        # Build a valid SQL that is exactly at the limit
        prefix = "SELECT "
        sql = prefix + "x" * (MAX_SQL_LENGTH - len(prefix))
        assert len(sql) == MAX_SQL_LENGTH
        inp = ExecuteQueryInput(sql=sql)
        assert len(inp.sql) == MAX_SQL_LENGTH

    def test_limit_lower_bound(self) -> None:
        """Limit must be at least 1."""
        with pytest.raises(Exception):
            ExecuteQueryInput(sql="SELECT 1", limit=0)

    def test_limit_upper_bound(self) -> None:
        """Limit must not exceed 10000."""
        with pytest.raises(Exception):
            ExecuteQueryInput(sql="SELECT 1", limit=10001)

    def test_limit_at_bounds(self) -> None:
        """Limit should accept boundary values 1 and 10000."""
        inp_min = ExecuteQueryInput(sql="SELECT 1", limit=1)
        assert inp_min.limit == 1
        inp_max = ExecuteQueryInput(sql="SELECT 1", limit=10000)
        assert inp_max.limit == 10000

    def test_timeout_must_be_positive(self) -> None:
        """Timeout must be >= 1 if specified."""
        with pytest.raises(Exception):
            ExecuteQueryInput(sql="SELECT 1", timeout_ms=0)

    def test_serialization_round_trip(self) -> None:
        """Should survive model_dump -> model_validate round trip."""
        inp = ExecuteQueryInput(
            sql="SELECT * FROM T WHERE C = ?",
            params=[1],
            limit=100,
            timeout_ms=3000,
        )
        dumped = inp.model_dump()
        restored = ExecuteQueryInput.model_validate(dumped)
        assert restored == inp

    def test_json_serialization(self) -> None:
        """Should serialize to valid JSON."""
        inp = ExecuteQueryInput(sql="SELECT 1 FROM DUMMY")
        json_str = inp.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["sql"] == "SELECT 1 FROM DUMMY"
        assert parsed["params"] is None


class TestQueryResult:
    """Tests for QueryResult output model."""

    def test_creates_with_valid_result(self) -> None:
        """Should create with typical query result data."""
        result = QueryResult(
            columns=["ID", "NAME", "STATUS"],
            rows=[
                {"ID": 1, "NAME": "Alice", "STATUS": "active"},
                {"ID": 2, "NAME": "Bob", "STATUS": "inactive"},
            ],
            row_count=2,
            execution_time_ms=12.5,
        )
        assert result.columns == ["ID", "NAME", "STATUS"]
        assert len(result.rows) == 2
        assert result.row_count == 2
        assert result.execution_time_ms == 12.5
        assert result.truncated is False
        assert result.warning is None

    def test_empty_result_set(self) -> None:
        """Should handle empty result set with rows=[], row_count=0."""
        result = QueryResult(
            columns=["ID", "NAME"],
            rows=[],
            row_count=0,
            execution_time_ms=3.2,
        )
        assert result.rows == []
        assert result.row_count == 0
        assert result.truncated is False
        assert result.warning is None

    def test_empty_columns_with_no_rows(self) -> None:
        """Should allow empty columns list when there are no rows."""
        result = QueryResult(
            columns=[],
            rows=[],
            row_count=0,
            execution_time_ms=1.0,
        )
        assert result.columns == []
        assert result.rows == []

    def test_truncated_result(self) -> None:
        """Should correctly set truncated flag and warning."""
        result = QueryResult(
            columns=["ID"],
            rows=[{"ID": i} for i in range(1000)],
            row_count=1000,
            execution_time_ms=50.0,
            truncated=True,
            warning="Result set truncated at 1000 rows",
        )
        assert result.truncated is True
        assert result.warning == "Result set truncated at 1000 rows"

    def test_row_count_must_be_non_negative(self) -> None:
        """row_count must be >= 0."""
        with pytest.raises(Exception):
            QueryResult(
                columns=["ID"],
                rows=[],
                row_count=-1,
                execution_time_ms=1.0,
            )

    def test_execution_time_must_be_non_negative(self) -> None:
        """execution_time_ms must be >= 0."""
        with pytest.raises(Exception):
            QueryResult(
                columns=["ID"],
                rows=[],
                row_count=0,
                execution_time_ms=-1.0,
            )

    def test_model_dump_includes_all_fields(self) -> None:
        """model_dump should include all fields."""
        result = QueryResult(
            columns=["ID"],
            rows=[{"ID": 1}],
            row_count=1,
            execution_time_ms=5.0,
        )
        dumped = result.model_dump()
        assert "columns" in dumped
        assert "rows" in dumped
        assert "row_count" in dumped
        assert "execution_time_ms" in dumped
        assert "truncated" in dumped
        assert "warning" in dumped

    def test_json_serialization(self) -> None:
        """Should serialize to valid JSON for MCP transport."""
        result = QueryResult(
            columns=["A", "B"],
            rows=[{"A": 1, "B": "hello"}],
            row_count=1,
            execution_time_ms=2.0,
            truncated=False,
        )
        json_str = result.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["columns"] == ["A", "B"]
        assert parsed["row_count"] == 1
        assert parsed["truncated"] is False

    def test_serialization_round_trip(self) -> None:
        """Should survive model_dump -> model_validate round trip."""
        result = QueryResult(
            columns=["X"],
            rows=[{"X": 42}],
            row_count=1,
            execution_time_ms=10.0,
            truncated=True,
            warning="Truncated",
        )
        dumped = result.model_dump()
        restored = QueryResult.model_validate(dumped)
        assert restored == result

    def test_rows_with_various_types(self) -> None:
        """Should handle rows containing various Python types."""
        result = QueryResult(
            columns=["INT_COL", "STR_COL", "FLOAT_COL", "NULL_COL", "BOOL_COL"],
            rows=[
                {
                    "INT_COL": 42,
                    "STR_COL": "hello",
                    "FLOAT_COL": 3.14,
                    "NULL_COL": None,
                    "BOOL_COL": True,
                }
            ],
            row_count=1,
            execution_time_ms=1.0,
        )
        row = result.rows[0]
        assert row["INT_COL"] == 42
        assert row["STR_COL"] == "hello"
        assert row["FLOAT_COL"] == 3.14
        assert row["NULL_COL"] is None
        assert row["BOOL_COL"] is True


class TestExecuteQueryOutput:
    """Tests for ExecuteQueryOutput wrapping model."""

    def test_creates_with_result_and_hash(self) -> None:
        """Should wrap QueryResult with a query_hash."""
        result = QueryResult(
            columns=["ID"],
            rows=[{"ID": 1}],
            row_count=1,
            execution_time_ms=5.0,
        )
        output = ExecuteQueryOutput(
            result=result,
            query_hash="abc123def456",
        )
        assert output.result.row_count == 1
        assert output.query_hash == "abc123def456"

    def test_empty_result_output(self) -> None:
        """Should handle an empty result set."""
        result = QueryResult(
            columns=["NAME"],
            rows=[],
            row_count=0,
            execution_time_ms=1.5,
        )
        output = ExecuteQueryOutput(result=result, query_hash="empty_hash")
        assert output.result.rows == []
        assert output.result.row_count == 0

    def test_model_dump_nests_result(self) -> None:
        """model_dump should nest the result data correctly."""
        result = QueryResult(
            columns=["A"],
            rows=[{"A": 1}],
            row_count=1,
            execution_time_ms=2.0,
        )
        output = ExecuteQueryOutput(result=result, query_hash="h1")
        dumped = output.model_dump()
        assert "result" in dumped
        assert dumped["result"]["row_count"] == 1
        assert dumped["query_hash"] == "h1"

    def test_json_serialization(self) -> None:
        """Should serialize to valid JSON for MCP transport."""
        result = QueryResult(
            columns=["ID"],
            rows=[{"ID": 99}],
            row_count=1,
            execution_time_ms=3.0,
        )
        output = ExecuteQueryOutput(result=result, query_hash="json_test")
        json_str = output.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["query_hash"] == "json_test"
        assert parsed["result"]["columns"] == ["ID"]

    def test_serialization_round_trip(self) -> None:
        """Should survive model_dump -> model_validate round trip."""
        result = QueryResult(
            columns=["X"],
            rows=[{"X": "val"}],
            row_count=1,
            execution_time_ms=0.5,
            truncated=True,
            warning="truncated",
        )
        output = ExecuteQueryOutput(result=result, query_hash="rt_hash")
        dumped = output.model_dump()
        restored = ExecuteQueryOutput.model_validate(dumped)
        assert restored == output


class TestExplainQueryInput:
    """Tests for ExplainQueryInput validation."""

    def test_creates_with_minimal_fields(self) -> None:
        """Should accept just a SQL string with defaults."""
        inp = ExplainQueryInput(sql="SELECT * FROM ORDERS")
        assert inp.sql == "SELECT * FROM ORDERS"
        assert inp.params is None
        assert inp.format == "text"

    def test_creates_with_all_fields(self) -> None:
        """Should accept all fields."""
        inp = ExplainQueryInput(
            sql="SELECT * FROM T WHERE C = ?",
            params=[42],
            format="json",
        )
        assert inp.sql == "SELECT * FROM T WHERE C = ?"
        assert inp.params == [42]
        assert inp.format == "json"

    def test_accepts_text_format(self) -> None:
        """Should accept 'text' format."""
        inp = ExplainQueryInput(sql="SELECT 1", format="text")
        assert inp.format == "text"

    def test_accepts_json_format(self) -> None:
        """Should accept 'json' format."""
        inp = ExplainQueryInput(sql="SELECT 1", format="json")
        assert inp.format == "json"

    def test_rejects_invalid_format(self) -> None:
        """Should reject unsupported format values."""
        with pytest.raises(Exception):
            ExplainQueryInput(sql="SELECT 1", format="yaml")

    def test_rejects_empty_sql(self) -> None:
        """Should reject empty SQL string."""
        with pytest.raises(Exception):
            ExplainQueryInput(sql="")

    def test_rejects_whitespace_only_sql(self) -> None:
        """Should reject whitespace-only SQL."""
        with pytest.raises(Exception):
            ExplainQueryInput(sql="  \t\n  ")

    def test_rejects_sql_exceeding_max_length(self) -> None:
        """Should reject SQL exceeding MAX_SQL_LENGTH."""
        long_sql = "SELECT " + "x" * MAX_SQL_LENGTH
        with pytest.raises(Exception):
            ExplainQueryInput(sql=long_sql)

    def test_accepts_named_params(self) -> None:
        """Should accept named bind parameters as dict."""
        inp = ExplainQueryInput(
            sql="SELECT * FROM T WHERE C = :val",
            params={"val": 10},
        )
        assert inp.params == {"val": 10}

    def test_serialization_round_trip(self) -> None:
        """Should survive model_dump -> model_validate round trip."""
        inp = ExplainQueryInput(sql="SELECT 1", params=[1], format="json")
        dumped = inp.model_dump()
        restored = ExplainQueryInput.model_validate(dumped)
        assert restored == inp


class TestExplainPlanNode:
    """Tests for ExplainPlanNode model."""

    def test_creates_with_all_fields(self) -> None:
        """Should accept all plan node fields."""
        node = ExplainPlanNode(
            operator="TABLE SCAN",
            table_name="ORDERS",
            schema_name="PUBLIC",
            cost=150.0,
            cardinality=5000.0,
            details={"execution_engine": "COLUMN", "predicate": "STATUS = 'OPEN'"},
        )
        assert node.operator == "TABLE SCAN"
        assert node.table_name == "ORDERS"
        assert node.schema_name == "PUBLIC"
        assert node.cost == 150.0
        assert node.cardinality == 5000.0
        assert node.details["execution_engine"] == "COLUMN"

    def test_creates_with_minimal_fields(self) -> None:
        """Should accept just the operator with defaults."""
        node = ExplainPlanNode(operator="LIMIT")
        assert node.operator == "LIMIT"
        assert node.table_name is None
        assert node.schema_name is None
        assert node.cost is None
        assert node.cardinality is None
        assert node.details == {}

    def test_cost_must_be_non_negative(self) -> None:
        """Cost must be >= 0 if specified."""
        with pytest.raises(Exception):
            ExplainPlanNode(operator="SCAN", cost=-1.0)

    def test_cardinality_must_be_non_negative(self) -> None:
        """Cardinality must be >= 0 if specified."""
        with pytest.raises(Exception):
            ExplainPlanNode(operator="SCAN", cardinality=-100.0)

    def test_zero_cost_and_cardinality(self) -> None:
        """Should allow zero for cost and cardinality."""
        node = ExplainPlanNode(operator="EMPTY SCAN", cost=0.0, cardinality=0.0)
        assert node.cost == 0.0
        assert node.cardinality == 0.0

    def test_details_default_to_empty_dict(self) -> None:
        """Details should default to empty dict, not None."""
        node = ExplainPlanNode(operator="JOIN")
        assert node.details == {}
        assert isinstance(node.details, dict)

    def test_model_dump_includes_all_fields(self) -> None:
        """model_dump should include all fields."""
        node = ExplainPlanNode(
            operator="INDEX SCAN",
            table_name="T1",
            schema_name="S1",
            cost=10.0,
            cardinality=100.0,
            details={"index": "PK_T1"},
        )
        dumped = node.model_dump()
        assert "operator" in dumped
        assert "table_name" in dumped
        assert "schema_name" in dumped
        assert "cost" in dumped
        assert "cardinality" in dumped
        assert "details" in dumped

    def test_json_serialization(self) -> None:
        """Should serialize to valid JSON."""
        node = ExplainPlanNode(
            operator="HASH JOIN",
            cost=200.0,
            details={"join_type": "INNER"},
        )
        json_str = node.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["operator"] == "HASH JOIN"
        assert parsed["cost"] == 200.0


class TestExplainQueryOutput:
    """Tests for ExplainQueryOutput model."""

    def test_creates_with_full_plan(self) -> None:
        """Should accept a full execution plan."""
        nodes = [
            ExplainPlanNode(
                operator="TABLE SCAN",
                table_name="ORDERS",
                schema_name="PUBLIC",
                cost=100.0,
                cardinality=1000.0,
            ),
            ExplainPlanNode(
                operator="FILTER",
                cost=50.0,
                cardinality=100.0,
                details={"predicate": "STATUS = 'ACTIVE'"},
            ),
        ]
        output = ExplainQueryOutput(
            nodes=nodes,
            total_cost=150.0,
            plan_type="HANA EXPLAIN PLAN",
            original_query="SELECT * FROM ORDERS WHERE STATUS = 'ACTIVE'",
        )
        assert len(output.nodes) == 2
        assert output.total_cost == 150.0
        assert output.plan_type == "HANA EXPLAIN PLAN"
        assert "ORDERS" in output.original_query

    def test_empty_plan_nodes(self) -> None:
        """Should allow empty nodes list."""
        output = ExplainQueryOutput(
            nodes=[],
            total_cost=None,
            plan_type="HANA EXPLAIN PLAN",
            original_query="SELECT 1 FROM DUMMY",
        )
        assert output.nodes == []
        assert output.total_cost is None

    def test_total_cost_must_be_non_negative(self) -> None:
        """total_cost must be >= 0 if specified."""
        with pytest.raises(Exception):
            ExplainQueryOutput(
                nodes=[],
                total_cost=-10.0,
                plan_type="HANA EXPLAIN PLAN",
                original_query="SELECT 1",
            )

    def test_model_dump_includes_all_fields(self) -> None:
        """model_dump should include all fields."""
        output = ExplainQueryOutput(
            nodes=[ExplainPlanNode(operator="SCAN")],
            total_cost=25.0,
            plan_type="HANA EXPLAIN PLAN",
            original_query="SELECT 1",
        )
        dumped = output.model_dump()
        assert "nodes" in dumped
        assert "total_cost" in dumped
        assert "plan_type" in dumped
        assert "original_query" in dumped
        assert len(dumped["nodes"]) == 1

    def test_json_serialization(self) -> None:
        """Should serialize to valid JSON for MCP transport."""
        output = ExplainQueryOutput(
            nodes=[
                ExplainPlanNode(operator="LIMIT", cost=1.0),
            ],
            total_cost=1.0,
            plan_type="HANA EXPLAIN PLAN",
            original_query="SELECT TOP 10 * FROM T",
        )
        json_str = output.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["plan_type"] == "HANA EXPLAIN PLAN"
        assert len(parsed["nodes"]) == 1

    def test_serialization_round_trip(self) -> None:
        """Should survive model_dump -> model_validate round trip."""
        output = ExplainQueryOutput(
            nodes=[
                ExplainPlanNode(
                    operator="INDEX SCAN",
                    table_name="T",
                    schema_name="S",
                    cost=10.0,
                    cardinality=50.0,
                    details={"key": "val"},
                ),
            ],
            total_cost=10.0,
            plan_type="HANA EXPLAIN PLAN",
            original_query="SELECT * FROM S.T",
        )
        dumped = output.model_dump()
        restored = ExplainQueryOutput.model_validate(dumped)
        assert restored == output

    def test_preserves_original_query(self) -> None:
        """original_query should be stored exactly as provided."""
        query = 'SELECT * FROM "MY_SCHEMA"."MY_TABLE" WHERE ID = ?'
        output = ExplainQueryOutput(
            nodes=[],
            plan_type="HANA EXPLAIN PLAN",
            original_query=query,
        )
        assert output.original_query == query


class TestModelsImportFromPackage:
    """Tests that models are properly exported from the models package."""

    def test_import_from_models_package(self) -> None:
        """All Layer 3 models should be importable from the models package."""
        from mamba_mcp_sap_hana.models import (
            ExecuteQueryInput,
            ExecuteQueryOutput,
            ExplainPlanNode,
            ExplainQueryInput,
            ExplainQueryOutput,
            QueryResult,
        )

        # Verify they are the correct classes
        assert ExecuteQueryInput.__name__ == "ExecuteQueryInput"
        assert ExecuteQueryOutput.__name__ == "ExecuteQueryOutput"
        assert QueryResult.__name__ == "QueryResult"
        assert ExplainQueryInput.__name__ == "ExplainQueryInput"
        assert ExplainQueryOutput.__name__ == "ExplainQueryOutput"
        assert ExplainPlanNode.__name__ == "ExplainPlanNode"
