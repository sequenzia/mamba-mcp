"""Tests for Layer 4 HANA-specific Pydantic models."""

import json

import pytest
from mamba_mcp_hana.models.hana import (
    CalcViewColumnInfo,
    CalcViewInfo,
    DescribeCalcViewInput,
    DescribeCalcViewOutput,
    DescribeProcedureInput,
    DescribeProcedureOutput,
    ListCalcViewsInput,
    ListCalcViewsOutput,
    ListProceduresInput,
    ListProceduresOutput,
    ProcedureInfo,
    ProcedureParameterInfo,
)
from pydantic import ValidationError

# === CalcViewColumnInfo ===


class TestCalcViewColumnInfo:
    """Tests for CalcViewColumnInfo model."""

    def test_valid_column(self) -> None:
        """CalcViewColumnInfo should accept valid column data."""
        col = CalcViewColumnInfo(
            name="REVENUE",
            data_type="DECIMAL",
            description="Total revenue",
            is_key=False,
            is_hidden=False,
        )
        assert col.name == "REVENUE"
        assert col.data_type == "DECIMAL"
        assert col.description == "Total revenue"
        assert col.is_key is False
        assert col.is_hidden is False

    def test_key_column(self) -> None:
        """CalcViewColumnInfo should represent key columns."""
        col = CalcViewColumnInfo(
            name="PRODUCT_ID",
            data_type="NVARCHAR",
            is_key=True,
        )
        assert col.is_key is True

    def test_hidden_column(self) -> None:
        """CalcViewColumnInfo should represent hidden columns."""
        col = CalcViewColumnInfo(
            name="INTERNAL_FLAG",
            data_type="TINYINT",
            is_hidden=True,
        )
        assert col.is_hidden is True

    def test_optional_fields_default_values(self) -> None:
        """CalcViewColumnInfo optional fields should have correct defaults."""
        col = CalcViewColumnInfo(name="COL1", data_type="INTEGER")
        assert col.description is None
        assert col.is_key is False
        assert col.is_hidden is False

    def test_description_none(self) -> None:
        """CalcViewColumnInfo should handle None description."""
        col = CalcViewColumnInfo(name="COL1", data_type="VARCHAR", description=None)
        assert col.description is None

    def test_serialization_to_dict(self) -> None:
        """CalcViewColumnInfo should serialize to dict for MCP transport."""
        col = CalcViewColumnInfo(
            name="AMOUNT",
            data_type="DECIMAL",
            description="Sales amount",
            is_key=False,
            is_hidden=False,
        )
        data = col.model_dump()
        assert data == {
            "name": "AMOUNT",
            "data_type": "DECIMAL",
            "description": "Sales amount",
            "is_key": False,
            "is_hidden": False,
        }

    def test_serialization_to_json(self) -> None:
        """CalcViewColumnInfo should serialize to valid JSON."""
        col = CalcViewColumnInfo(name="COL1", data_type="NVARCHAR", description=None)
        parsed = json.loads(col.model_dump_json())
        assert parsed["name"] == "COL1"
        assert parsed["description"] is None

    def test_missing_required_field_rejected(self) -> None:
        """CalcViewColumnInfo should reject missing required fields."""
        with pytest.raises(ValidationError):
            CalcViewColumnInfo(name="X")  # type: ignore[call-arg]


# === CalcViewInfo ===


class TestCalcViewInfo:
    """Tests for CalcViewInfo model."""

    def test_valid_calc_view(self) -> None:
        """CalcViewInfo should accept valid calculation view data."""
        view = CalcViewInfo(
            name="CV_SALES_ANALYSIS",
            schema_name="_SYS_BIC",
            type="CALC",
            description="Sales analysis calculation view",
            is_active=True,
            column_count=15,
        )
        assert view.name == "CV_SALES_ANALYSIS"
        assert view.schema_name == "_SYS_BIC"
        assert view.type == "CALC"
        assert view.description == "Sales analysis calculation view"
        assert view.is_active is True
        assert view.column_count == 15
        assert view.columns == []

    def test_inactive_view(self) -> None:
        """CalcViewInfo should represent an inactive calculation view."""
        view = CalcViewInfo(
            name="CV_OLD_REPORT",
            schema_name="_SYS_BIC",
            type="JOIN",
            is_active=False,
            column_count=5,
        )
        assert view.is_active is False

    def test_view_with_columns(self) -> None:
        """CalcViewInfo should hold column metadata when included."""
        columns = [
            CalcViewColumnInfo(name="PRODUCT_ID", data_type="NVARCHAR", is_key=True),
            CalcViewColumnInfo(name="REVENUE", data_type="DECIMAL"),
        ]
        view = CalcViewInfo(
            name="CV_PRODUCT",
            schema_name="_SYS_BIC",
            type="OLAP",
            is_active=True,
            column_count=2,
            columns=columns,
        )
        assert len(view.columns) == 2
        assert view.columns[0].name == "PRODUCT_ID"
        assert view.columns[0].is_key is True

    def test_description_none(self) -> None:
        """CalcViewInfo should handle None description."""
        view = CalcViewInfo(
            name="CV_NO_DESC",
            schema_name="_SYS_BIC",
            type="CALC",
            description=None,
            is_active=True,
            column_count=3,
        )
        assert view.description is None

    def test_columns_default_empty_list(self) -> None:
        """CalcViewInfo should default columns to empty list."""
        view = CalcViewInfo(
            name="CV_BASIC",
            schema_name="S",
            type="CALC",
            is_active=True,
            column_count=0,
        )
        assert view.columns == []

    def test_serialization_to_dict(self) -> None:
        """CalcViewInfo should serialize to dict for MCP transport."""
        view = CalcViewInfo(
            name="CV_TEST",
            schema_name="_SYS_BIC",
            type="CALC",
            description="Test view",
            is_active=True,
            column_count=2,
        )
        data = view.model_dump()
        assert data["name"] == "CV_TEST"
        assert data["is_active"] is True
        assert data["columns"] == []

    def test_serialization_to_json(self) -> None:
        """CalcViewInfo should serialize to valid JSON."""
        view = CalcViewInfo(
            name="CV_JSON",
            schema_name="S",
            type="JOIN",
            is_active=True,
            column_count=1,
        )
        parsed = json.loads(view.model_dump_json())
        assert parsed["type"] == "JOIN"
        assert parsed["is_active"] is True
        assert isinstance(parsed["columns"], list)

    def test_missing_required_field_rejected(self) -> None:
        """CalcViewInfo should reject missing required fields."""
        with pytest.raises(ValidationError):
            CalcViewInfo(name="X", schema_name="S")  # type: ignore[call-arg]


# === ListCalcViewsInput ===


class TestListCalcViewsInput:
    """Tests for ListCalcViewsInput model."""

    def test_required_schema_name(self) -> None:
        """ListCalcViewsInput should require schema_name."""
        inp = ListCalcViewsInput(schema_name="_SYS_BIC")
        assert inp.schema_name == "_SYS_BIC"

    def test_defaults(self) -> None:
        """ListCalcViewsInput should default include_columns=False and name_pattern=None."""
        inp = ListCalcViewsInput(schema_name="S")
        assert inp.include_columns is False
        assert inp.name_pattern is None

    def test_include_columns_true(self) -> None:
        """ListCalcViewsInput should accept include_columns=True."""
        inp = ListCalcViewsInput(schema_name="S", include_columns=True)
        assert inp.include_columns is True

    def test_name_pattern(self) -> None:
        """ListCalcViewsInput should accept a LIKE pattern."""
        inp = ListCalcViewsInput(schema_name="S", name_pattern="CV_SALES%")
        assert inp.name_pattern == "CV_SALES%"

    def test_missing_schema_name_rejected(self) -> None:
        """ListCalcViewsInput should reject missing schema_name."""
        with pytest.raises(ValidationError):
            ListCalcViewsInput()  # type: ignore[call-arg]

    def test_serialization_to_dict(self) -> None:
        """ListCalcViewsInput should serialize to dict."""
        inp = ListCalcViewsInput(schema_name="_SYS_BIC", include_columns=True, name_pattern="CV_%")
        data = inp.model_dump()
        assert data["schema_name"] == "_SYS_BIC"
        assert data["include_columns"] is True
        assert data["name_pattern"] == "CV_%"


# === ListCalcViewsOutput ===


class TestListCalcViewsOutput:
    """Tests for ListCalcViewsOutput model."""

    def test_valid_output(self) -> None:
        """ListCalcViewsOutput should accept valid view list."""
        views = [
            CalcViewInfo(
                name="CV_SALES",
                schema_name="_SYS_BIC",
                type="CALC",
                is_active=True,
                column_count=10,
            ),
        ]
        output = ListCalcViewsOutput(views=views, schema_name="_SYS_BIC", count=1)
        assert len(output.views) == 1
        assert output.schema_name == "_SYS_BIC"
        assert output.count == 1

    def test_empty_views(self) -> None:
        """ListCalcViewsOutput should handle empty view list."""
        output = ListCalcViewsOutput(views=[], schema_name="EMPTY", count=0)
        assert output.views == []
        assert output.count == 0

    def test_serialization_to_json(self) -> None:
        """ListCalcViewsOutput should serialize to valid JSON for MCP transport."""
        output = ListCalcViewsOutput(views=[], schema_name="S", count=0)
        parsed = json.loads(output.model_dump_json())
        assert isinstance(parsed["views"], list)
        assert parsed["schema_name"] == "S"
        assert parsed["count"] == 0

    def test_serialization_to_dict(self) -> None:
        """ListCalcViewsOutput should serialize views as list of dicts."""
        views = [
            CalcViewInfo(
                name="CV_TEST",
                schema_name="S",
                type="CALC",
                is_active=True,
                column_count=3,
            ),
        ]
        output = ListCalcViewsOutput(views=views, schema_name="S", count=1)
        data = output.model_dump()
        assert isinstance(data["views"], list)
        assert data["views"][0]["name"] == "CV_TEST"
        assert data["views"][0]["is_active"] is True


# === DescribeCalcViewInput ===


class TestDescribeCalcViewInput:
    """Tests for DescribeCalcViewInput model."""

    def test_required_fields(self) -> None:
        """DescribeCalcViewInput should require view_name and schema_name."""
        inp = DescribeCalcViewInput(view_name="CV_SALES", schema_name="_SYS_BIC")
        assert inp.view_name == "CV_SALES"
        assert inp.schema_name == "_SYS_BIC"

    def test_missing_view_name_rejected(self) -> None:
        """DescribeCalcViewInput should reject missing view_name."""
        with pytest.raises(ValidationError):
            DescribeCalcViewInput(schema_name="S")  # type: ignore[call-arg]

    def test_missing_schema_name_rejected(self) -> None:
        """DescribeCalcViewInput should reject missing schema_name."""
        with pytest.raises(ValidationError):
            DescribeCalcViewInput(view_name="V")  # type: ignore[call-arg]


# === DescribeCalcViewOutput ===


class TestDescribeCalcViewOutput:
    """Tests for DescribeCalcViewOutput model."""

    def test_full_description(self) -> None:
        """DescribeCalcViewOutput should hold complete view metadata."""
        columns = [
            CalcViewColumnInfo(name="PRODUCT_ID", data_type="NVARCHAR", is_key=True),
            CalcViewColumnInfo(name="REVENUE", data_type="DECIMAL", description="Total revenue"),
        ]
        params = [
            {"name": "IP_YEAR", "type": "INTEGER", "default": "2024", "mandatory": True},
        ]
        output = DescribeCalcViewOutput(
            name="CV_SALES_REPORT",
            schema_name="_SYS_BIC",
            columns=columns,
            parameters=params,
            description="Annual sales report view",
        )
        assert output.name == "CV_SALES_REPORT"
        assert len(output.columns) == 2
        assert len(output.parameters) == 1
        assert output.parameters[0]["name"] == "IP_YEAR"
        assert output.description == "Annual sales report view"

    def test_no_parameters(self) -> None:
        """DescribeCalcViewOutput should handle views with no parameters."""
        output = DescribeCalcViewOutput(
            name="CV_SIMPLE",
            schema_name="S",
            columns=[CalcViewColumnInfo(name="ID", data_type="INT")],
        )
        assert output.parameters == []
        assert output.description is None

    def test_empty_parameters_list(self) -> None:
        """DescribeCalcViewOutput should serialize empty parameters list correctly."""
        output = DescribeCalcViewOutput(
            name="CV_NO_PARAMS",
            schema_name="S",
            columns=[CalcViewColumnInfo(name="X", data_type="INT")],
            parameters=[],
        )
        data = output.model_dump()
        assert data["parameters"] == []

    def test_description_none(self) -> None:
        """DescribeCalcViewOutput should handle None description."""
        output = DescribeCalcViewOutput(
            name="CV_NODESC",
            schema_name="S",
            columns=[CalcViewColumnInfo(name="X", data_type="INT")],
            description=None,
        )
        assert output.description is None

    def test_serialization_to_json(self) -> None:
        """DescribeCalcViewOutput should serialize to valid JSON for MCP transport."""
        output = DescribeCalcViewOutput(
            name="CV_TEST",
            schema_name="S",
            columns=[
                CalcViewColumnInfo(name="A", data_type="NVARCHAR", is_key=True),
            ],
            parameters=[{"name": "IP_1", "type": "INT"}],
            description="Test",
        )
        parsed = json.loads(output.model_dump_json())
        assert parsed["name"] == "CV_TEST"
        assert isinstance(parsed["columns"], list)
        assert isinstance(parsed["parameters"], list)
        assert parsed["parameters"][0]["name"] == "IP_1"
        assert parsed["description"] == "Test"

    def test_serialization_to_dict(self) -> None:
        """DescribeCalcViewOutput should serialize correctly to dict."""
        output = DescribeCalcViewOutput(
            name="CV_DICT",
            schema_name="S",
            columns=[CalcViewColumnInfo(name="X", data_type="INT")],
        )
        data = output.model_dump()
        assert data["name"] == "CV_DICT"
        assert data["parameters"] == []
        assert data["description"] is None


# === ProcedureParameterInfo ===


class TestProcedureParameterInfo:
    """Tests for ProcedureParameterInfo model."""

    def test_in_parameter(self) -> None:
        """ProcedureParameterInfo should accept IN direction."""
        param = ProcedureParameterInfo(
            name="P_CUSTOMER_ID",
            data_type="INTEGER",
            direction="IN",
            position=1,
        )
        assert param.name == "P_CUSTOMER_ID"
        assert param.data_type == "INTEGER"
        assert param.direction == "IN"
        assert param.position == 1
        assert param.default_value is None

    def test_out_parameter(self) -> None:
        """ProcedureParameterInfo should accept OUT direction."""
        param = ProcedureParameterInfo(
            name="P_RESULT",
            data_type="TABLE",
            direction="OUT",
            position=2,
        )
        assert param.direction == "OUT"

    def test_inout_parameter(self) -> None:
        """ProcedureParameterInfo should accept INOUT direction."""
        param = ProcedureParameterInfo(
            name="P_COUNTER",
            data_type="INTEGER",
            direction="INOUT",
            position=1,
        )
        assert param.direction == "INOUT"

    def test_parameter_with_default_value(self) -> None:
        """ProcedureParameterInfo should store default value expressions."""
        param = ProcedureParameterInfo(
            name="P_YEAR",
            data_type="INTEGER",
            direction="IN",
            position=1,
            default_value="2024",
        )
        assert param.default_value == "2024"

    def test_default_value_none(self) -> None:
        """ProcedureParameterInfo should handle None default value."""
        param = ProcedureParameterInfo(
            name="P_NAME",
            data_type="NVARCHAR",
            direction="IN",
            position=1,
            default_value=None,
        )
        assert param.default_value is None

    def test_invalid_direction_rejected(self) -> None:
        """ProcedureParameterInfo should reject invalid direction values."""
        with pytest.raises(ValidationError):
            ProcedureParameterInfo(
                name="P_BAD",
                data_type="INT",
                direction="RETURN",  # type: ignore[arg-type]
                position=1,
            )

    def test_position_below_minimum_rejected(self) -> None:
        """ProcedureParameterInfo should reject position < 1."""
        with pytest.raises(ValidationError):
            ProcedureParameterInfo(
                name="P_ZERO",
                data_type="INT",
                direction="IN",
                position=0,
            )

    def test_serialization_to_dict(self) -> None:
        """ProcedureParameterInfo should serialize to dict for MCP transport."""
        param = ProcedureParameterInfo(
            name="P_ID",
            data_type="INTEGER",
            direction="IN",
            position=1,
            default_value="100",
        )
        data = param.model_dump()
        assert data == {
            "name": "P_ID",
            "data_type": "INTEGER",
            "direction": "IN",
            "position": 1,
            "default_value": "100",
        }

    def test_serialization_to_json(self) -> None:
        """ProcedureParameterInfo should serialize to valid JSON."""
        param = ProcedureParameterInfo(
            name="P_OUT",
            data_type="TABLE",
            direction="OUT",
            position=2,
        )
        parsed = json.loads(param.model_dump_json())
        assert parsed["direction"] == "OUT"
        assert parsed["default_value"] is None

    def test_missing_required_field_rejected(self) -> None:
        """ProcedureParameterInfo should reject missing required fields."""
        with pytest.raises(ValidationError):
            ProcedureParameterInfo(name="P", data_type="INT")  # type: ignore[call-arg]


# === ProcedureInfo ===


class TestProcedureInfo:
    """Tests for ProcedureInfo model."""

    def test_valid_procedure(self) -> None:
        """ProcedureInfo should accept valid procedure data."""
        proc = ProcedureInfo(
            name="PROC_GET_CUSTOMERS",
            schema_name="MY_SCHEMA",
            type="SQLSCRIPT",
            parameter_count=3,
            is_read_only=True,
        )
        assert proc.name == "PROC_GET_CUSTOMERS"
        assert proc.schema_name == "MY_SCHEMA"
        assert proc.type == "SQLSCRIPT"
        assert proc.parameter_count == 3
        assert proc.is_read_only is True
        assert proc.parameters == []

    def test_r_procedure(self) -> None:
        """ProcedureInfo should represent R language procedures."""
        proc = ProcedureInfo(
            name="PROC_R_ANALYSIS",
            schema_name="ANALYTICS",
            type="R",
            parameter_count=2,
            is_read_only=True,
        )
        assert proc.type == "R"

    def test_l_procedure(self) -> None:
        """ProcedureInfo should represent L language procedures."""
        proc = ProcedureInfo(
            name="PROC_NATIVE",
            schema_name="SYS",
            type="L",
            parameter_count=0,
            is_read_only=False,
        )
        assert proc.type == "L"
        assert proc.is_read_only is False

    def test_procedure_with_parameters(self) -> None:
        """ProcedureInfo should hold parameter details when included."""
        params = [
            ProcedureParameterInfo(
                name="P_INPUT", data_type="NVARCHAR", direction="IN", position=1
            ),
            ProcedureParameterInfo(name="P_OUTPUT", data_type="TABLE", direction="OUT", position=2),
        ]
        proc = ProcedureInfo(
            name="PROC_WITH_PARAMS",
            schema_name="S",
            type="SQLSCRIPT",
            parameter_count=2,
            is_read_only=True,
            parameters=params,
        )
        assert len(proc.parameters) == 2
        assert proc.parameters[0].direction == "IN"
        assert proc.parameters[1].direction == "OUT"

    def test_parameters_default_empty_list(self) -> None:
        """ProcedureInfo should default parameters to empty list."""
        proc = ProcedureInfo(
            name="PROC_BASIC",
            schema_name="S",
            type="SQLSCRIPT",
            parameter_count=0,
            is_read_only=True,
        )
        assert proc.parameters == []

    def test_zero_parameter_count(self) -> None:
        """ProcedureInfo should accept zero parameter count."""
        proc = ProcedureInfo(
            name="PROC_NO_PARAMS",
            schema_name="S",
            type="SQLSCRIPT",
            parameter_count=0,
            is_read_only=False,
        )
        assert proc.parameter_count == 0

    def test_negative_parameter_count_rejected(self) -> None:
        """ProcedureInfo should reject negative parameter count."""
        with pytest.raises(ValidationError):
            ProcedureInfo(
                name="PROC_BAD",
                schema_name="S",
                type="SQLSCRIPT",
                parameter_count=-1,
                is_read_only=True,
            )

    def test_serialization_to_dict(self) -> None:
        """ProcedureInfo should serialize to dict for MCP transport."""
        proc = ProcedureInfo(
            name="PROC_TEST",
            schema_name="MY_SCHEMA",
            type="SQLSCRIPT",
            parameter_count=1,
            is_read_only=True,
        )
        data = proc.model_dump()
        assert data["name"] == "PROC_TEST"
        assert data["is_read_only"] is True
        assert data["parameters"] == []

    def test_serialization_to_json(self) -> None:
        """ProcedureInfo should serialize to valid JSON."""
        proc = ProcedureInfo(
            name="PROC_JSON",
            schema_name="S",
            type="SQLSCRIPT",
            parameter_count=0,
            is_read_only=False,
        )
        parsed = json.loads(proc.model_dump_json())
        assert parsed["type"] == "SQLSCRIPT"
        assert parsed["is_read_only"] is False
        assert isinstance(parsed["parameters"], list)

    def test_missing_required_field_rejected(self) -> None:
        """ProcedureInfo should reject missing required fields."""
        with pytest.raises(ValidationError):
            ProcedureInfo(name="P", schema_name="S")  # type: ignore[call-arg]


# === ListProceduresInput ===


class TestListProceduresInput:
    """Tests for ListProceduresInput model."""

    def test_required_schema_name(self) -> None:
        """ListProceduresInput should require schema_name."""
        inp = ListProceduresInput(schema_name="MY_SCHEMA")
        assert inp.schema_name == "MY_SCHEMA"

    def test_defaults(self) -> None:
        """ListProceduresInput should default include_parameters=False and name_pattern=None."""
        inp = ListProceduresInput(schema_name="S")
        assert inp.include_parameters is False
        assert inp.name_pattern is None

    def test_include_parameters_true(self) -> None:
        """ListProceduresInput should accept include_parameters=True."""
        inp = ListProceduresInput(schema_name="S", include_parameters=True)
        assert inp.include_parameters is True

    def test_name_pattern(self) -> None:
        """ListProceduresInput should accept a LIKE pattern."""
        inp = ListProceduresInput(schema_name="S", name_pattern="PROC_%")
        assert inp.name_pattern == "PROC_%"

    def test_missing_schema_name_rejected(self) -> None:
        """ListProceduresInput should reject missing schema_name."""
        with pytest.raises(ValidationError):
            ListProceduresInput()  # type: ignore[call-arg]

    def test_serialization_to_dict(self) -> None:
        """ListProceduresInput should serialize to dict."""
        inp = ListProceduresInput(schema_name="S", include_parameters=True, name_pattern="P%")
        data = inp.model_dump()
        assert data["schema_name"] == "S"
        assert data["include_parameters"] is True
        assert data["name_pattern"] == "P%"


# === ListProceduresOutput ===


class TestListProceduresOutput:
    """Tests for ListProceduresOutput model."""

    def test_valid_output(self) -> None:
        """ListProceduresOutput should accept valid procedure list."""
        procedures = [
            ProcedureInfo(
                name="PROC_A",
                schema_name="S",
                type="SQLSCRIPT",
                parameter_count=2,
                is_read_only=True,
            ),
        ]
        output = ListProceduresOutput(procedures=procedures, schema_name="S", count=1)
        assert len(output.procedures) == 1
        assert output.schema_name == "S"
        assert output.count == 1

    def test_empty_procedures(self) -> None:
        """ListProceduresOutput should handle empty procedure list."""
        output = ListProceduresOutput(procedures=[], schema_name="EMPTY", count=0)
        assert output.procedures == []
        assert output.count == 0

    def test_serialization_to_json(self) -> None:
        """ListProceduresOutput should serialize to valid JSON for MCP transport."""
        output = ListProceduresOutput(procedures=[], schema_name="S", count=0)
        parsed = json.loads(output.model_dump_json())
        assert isinstance(parsed["procedures"], list)
        assert parsed["schema_name"] == "S"
        assert parsed["count"] == 0

    def test_serialization_to_dict(self) -> None:
        """ListProceduresOutput should serialize procedures as list of dicts."""
        procedures = [
            ProcedureInfo(
                name="PROC_TEST",
                schema_name="S",
                type="SQLSCRIPT",
                parameter_count=0,
                is_read_only=False,
            ),
        ]
        output = ListProceduresOutput(procedures=procedures, schema_name="S", count=1)
        data = output.model_dump()
        assert isinstance(data["procedures"], list)
        assert data["procedures"][0]["name"] == "PROC_TEST"
        assert data["procedures"][0]["is_read_only"] is False


# === DescribeProcedureInput ===


class TestDescribeProcedureInput:
    """Tests for DescribeProcedureInput model."""

    def test_required_fields(self) -> None:
        """DescribeProcedureInput should require procedure_name and schema_name."""
        inp = DescribeProcedureInput(procedure_name="PROC_GET_DATA", schema_name="MY_SCHEMA")
        assert inp.procedure_name == "PROC_GET_DATA"
        assert inp.schema_name == "MY_SCHEMA"

    def test_missing_procedure_name_rejected(self) -> None:
        """DescribeProcedureInput should reject missing procedure_name."""
        with pytest.raises(ValidationError):
            DescribeProcedureInput(schema_name="S")  # type: ignore[call-arg]

    def test_missing_schema_name_rejected(self) -> None:
        """DescribeProcedureInput should reject missing schema_name."""
        with pytest.raises(ValidationError):
            DescribeProcedureInput(procedure_name="P")  # type: ignore[call-arg]


# === DescribeProcedureOutput ===


class TestDescribeProcedureOutput:
    """Tests for DescribeProcedureOutput model."""

    def test_full_description(self) -> None:
        """DescribeProcedureOutput should hold complete procedure metadata."""
        params = [
            ProcedureParameterInfo(
                name="P_CUSTOMER_ID",
                data_type="INTEGER",
                direction="IN",
                position=1,
            ),
            ProcedureParameterInfo(
                name="P_RESULT",
                data_type="TABLE",
                direction="OUT",
                position=2,
            ),
            ProcedureParameterInfo(
                name="P_STATUS",
                data_type="NVARCHAR",
                direction="INOUT",
                position=3,
                default_value="'PENDING'",
            ),
        ]
        output = DescribeProcedureOutput(
            name="PROC_GET_CUSTOMER_DATA",
            schema_name="MY_SCHEMA",
            parameters=params,
            definition_preview="CREATE PROCEDURE PROC_GET_CUSTOMER_DATA...",
            is_read_only=True,
        )
        assert output.name == "PROC_GET_CUSTOMER_DATA"
        assert len(output.parameters) == 3
        assert output.parameters[0].direction == "IN"
        assert output.parameters[1].direction == "OUT"
        assert output.parameters[2].direction == "INOUT"
        assert output.parameters[2].default_value == "'PENDING'"
        assert output.definition_preview is not None
        assert output.is_read_only is True

    def test_no_parameters(self) -> None:
        """DescribeProcedureOutput should handle procedures with no parameters."""
        output = DescribeProcedureOutput(
            name="PROC_SIMPLE",
            schema_name="S",
            is_read_only=False,
        )
        assert output.parameters == []
        assert output.definition_preview is None

    def test_empty_parameters_list(self) -> None:
        """DescribeProcedureOutput should serialize empty parameters list correctly."""
        output = DescribeProcedureOutput(
            name="PROC_EMPTY",
            schema_name="S",
            parameters=[],
            is_read_only=True,
        )
        data = output.model_dump()
        assert data["parameters"] == []

    def test_definition_preview_none(self) -> None:
        """DescribeProcedureOutput should handle None definition preview."""
        output = DescribeProcedureOutput(
            name="PROC_NO_DEF",
            schema_name="S",
            is_read_only=True,
            definition_preview=None,
        )
        assert output.definition_preview is None

    def test_serialization_to_json(self) -> None:
        """DescribeProcedureOutput should serialize to valid JSON for MCP transport."""
        output = DescribeProcedureOutput(
            name="PROC_JSON",
            schema_name="S",
            parameters=[
                ProcedureParameterInfo(
                    name="P_IN",
                    data_type="NVARCHAR",
                    direction="IN",
                    position=1,
                    default_value="'test'",
                ),
            ],
            definition_preview="CREATE PROCEDURE...",
            is_read_only=True,
        )
        parsed = json.loads(output.model_dump_json())
        assert parsed["name"] == "PROC_JSON"
        assert isinstance(parsed["parameters"], list)
        assert parsed["parameters"][0]["direction"] == "IN"
        assert parsed["parameters"][0]["default_value"] == "'test'"
        assert parsed["definition_preview"] == "CREATE PROCEDURE..."
        assert parsed["is_read_only"] is True

    def test_serialization_to_dict(self) -> None:
        """DescribeProcedureOutput should serialize correctly to dict."""
        output = DescribeProcedureOutput(
            name="PROC_DICT",
            schema_name="S",
            is_read_only=False,
        )
        data = output.model_dump()
        assert data["name"] == "PROC_DICT"
        assert data["parameters"] == []
        assert data["definition_preview"] is None
        assert data["is_read_only"] is False

    def test_missing_required_field_rejected(self) -> None:
        """DescribeProcedureOutput should reject missing required fields."""
        with pytest.raises(ValidationError):
            DescribeProcedureOutput(name="P", schema_name="S")  # type: ignore[call-arg]


# === Cross-Model Integration ===


class TestHanaModelImports:
    """Tests that all HANA-specific models are importable from the models package."""

    def test_hana_models_importable_from_package(self) -> None:
        """All Layer 4 models should be importable from models package."""
        from mamba_mcp_hana.models import (  # noqa: F401
            CalcViewColumnInfo,
            CalcViewInfo,
            DescribeCalcViewInput,
            DescribeCalcViewOutput,
            DescribeProcedureInput,
            DescribeProcedureOutput,
            ListCalcViewsInput,
            ListCalcViewsOutput,
            ListProceduresInput,
            ListProceduresOutput,
            ProcedureInfo,
            ProcedureParameterInfo,
        )

    def test_all_exports_in_package(self) -> None:
        """All Layer 4 models should be in the models __all__."""
        from mamba_mcp_hana import models

        expected = [
            "CalcViewColumnInfo",
            "CalcViewInfo",
            "ListCalcViewsInput",
            "ListCalcViewsOutput",
            "DescribeCalcViewInput",
            "DescribeCalcViewOutput",
            "ProcedureParameterInfo",
            "ProcedureInfo",
            "ListProceduresInput",
            "ListProceduresOutput",
            "DescribeProcedureInput",
            "DescribeProcedureOutput",
        ]
        for name in expected:
            assert name in models.__all__, f"{name} not in models.__all__"
