"""Pydantic models for HANA-specific tools (Layer 4).

Based on spec Sections 5.4 and 9.3.

Provides input validation and structured output models for HANA-specific
database objects that don't exist in standard PostgreSQL: calculation views
(_SYS_BIC schema objects), table store type information (column vs row store),
and stored procedures with IN/OUT/INOUT parameters.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# === List Calculation Views ===


class ListCalcViewsInput(BaseModel):
    """Input for list_calculation_views tool."""

    schema_name: str = Field(
        description="Schema to list calculation views from",
    )
    include_columns: bool = Field(
        default=False,
        description="Include column metadata (names, types) for each view",
    )
    name_pattern: str | None = Field(
        default=None,
        description="Optional SQL LIKE pattern to filter view names (e.g., 'SALES%')",
    )


class CalcViewColumnInfo(BaseModel):
    """Column metadata for a calculation view."""

    name: str = Field(description="Column name")
    data_type: str = Field(description="SAP HANA data type")
    description: str | None = Field(default=None, description="Column description")
    is_key: bool = Field(default=False, description="Whether this column is a key column")
    is_hidden: bool = Field(
        default=False, description="Whether this column is hidden from default output"
    )


class CalcViewInfo(BaseModel):
    """Information about a HANA calculation view."""

    name: str = Field(description="Calculation view name")
    schema_name: str = Field(description="Schema containing the view")
    type: str = Field(description="Calculation view type (e.g., CALC, JOIN, OLAP)")
    description: str | None = Field(default=None, description="View description")
    is_active: bool = Field(
        description="Whether the calculation view is active and valid",
    )
    column_count: int = Field(
        description="Number of columns in the view",
    )
    columns: list[CalcViewColumnInfo] = Field(
        default_factory=list,
        description="Column metadata (populated when include_columns=True)",
    )


class ListCalcViewsOutput(BaseModel):
    """Output for list_calculation_views tool."""

    views: list[CalcViewInfo] = Field(
        description="List of calculation view information",
    )
    schema_name: str = Field(description="Schema these views belong to")
    count: int = Field(description="Number of calculation views returned")


# === Get Table Store Type ===


class GetTableStoreTypeInput(BaseModel):
    """Input for get_table_store_type tool."""

    table_name: str = Field(description="Name of the table to check store type")
    schema_name: str = Field(
        description="Schema containing the table",
    )


class StoreTypeInfo(BaseModel):
    """Store type information for a HANA table."""

    table_name: str = Field(description="Table name")
    schema_name: str = Field(description="Schema containing the table")
    store_type: Literal["COLUMN", "ROW"] = Field(
        description="Storage type: COLUMN (columnar) or ROW (row-based)",
    )
    is_column_table: bool = Field(
        description="Whether the table uses column store",
    )
    has_partitions: bool = Field(
        default=False,
        description="Whether the table is partitioned",
    )
    partition_count: int = Field(
        default=0,
        ge=0,
        description="Number of partitions (0 if not partitioned)",
    )
    is_compressed: bool = Field(
        default=False,
        description="Whether compression is enabled",
    )
    implications: str = Field(
        description=(
            "Text explaining the implications of the store type "
            "for query optimization and feature support"
        ),
    )
    note: str | None = Field(
        default=None,
        description="Additional informational note",
    )


class GetTableStoreTypeOutput(BaseModel):
    """Output for get_table_store_type tool."""

    store_info: StoreTypeInfo = Field(
        description="Store type information for the table",
    )


# === Describe Calculation View ===


class DescribeCalcViewInput(BaseModel):
    """Input for describe_calculation_view tool."""

    view_name: str = Field(description="Name of the calculation view to describe")
    schema_name: str = Field(
        description="Schema containing the calculation view",
    )


class DescribeCalcViewOutput(BaseModel):
    """Output for describe_calculation_view tool."""

    name: str = Field(description="Calculation view name")
    schema_name: str = Field(description="Schema containing the view")
    columns: list[CalcViewColumnInfo] = Field(
        description="Column definitions",
    )
    parameters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="View input parameters (name, type, default, mandatory)",
    )
    description: str | None = Field(default=None, description="View description")


# === List Procedures ===


class ListProceduresInput(BaseModel):
    """Input for list_procedures tool."""

    schema_name: str = Field(
        description="Schema to list procedures from",
    )
    include_parameters: bool = Field(
        default=False,
        description="Include parameter details for each procedure",
    )
    name_pattern: str | None = Field(
        default=None,
        description="Optional SQL LIKE pattern to filter procedure names (e.g., 'PROC_%')",
    )


class ProcedureParameterInfo(BaseModel):
    """Parameter metadata for a stored procedure."""

    name: str = Field(description="Parameter name")
    data_type: str = Field(description="SAP HANA data type")
    direction: Literal["IN", "OUT", "INOUT"] = Field(
        description="Parameter direction: IN, OUT, or INOUT",
    )
    position: int = Field(
        ge=1,
        description="Ordinal position of the parameter",
    )
    default_value: str | None = Field(default=None, description="Default value expression")


class ProcedureInfo(BaseModel):
    """Information about a stored procedure."""

    name: str = Field(description="Procedure name")
    schema_name: str = Field(description="Schema containing the procedure")
    type: str = Field(
        description="Procedure language type (e.g., SQLSCRIPT, R, L)",
    )
    parameter_count: int = Field(ge=0, description="Number of parameters")
    is_read_only: bool = Field(
        description="Whether the procedure is marked as read-only",
    )
    parameters: list[ProcedureParameterInfo] = Field(
        default_factory=list,
        description="Parameter details (populated when include_parameters=True)",
    )


class ListProceduresOutput(BaseModel):
    """Output for list_procedures tool."""

    procedures: list[ProcedureInfo] = Field(
        description="List of procedure information",
    )
    schema_name: str = Field(description="Schema these procedures belong to")
    count: int = Field(description="Number of procedures returned")


# === Describe Procedure ===


class DescribeProcedureInput(BaseModel):
    """Input for describe_procedure tool."""

    procedure_name: str = Field(
        description="Name of the procedure to describe",
    )
    schema_name: str = Field(
        description="Schema containing the procedure",
    )


class DescribeProcedureOutput(BaseModel):
    """Output for describe_procedure tool."""

    name: str = Field(description="Procedure name")
    schema_name: str = Field(description="Schema containing the procedure")
    parameters: list[ProcedureParameterInfo] = Field(
        default_factory=list,
        description="Procedure parameters with direction and type details",
    )
    definition_preview: str | None = Field(
        default=None,
        description="First portion of the procedure's SQL definition (if available)",
    )
    is_read_only: bool = Field(
        description="Whether the procedure is marked as read-only",
    )
