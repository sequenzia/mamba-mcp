"""Pydantic models for schema discovery tools (Layer 1).

Based on spec Section 5.1.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# === List Schemas ===


class ListSchemasInput(BaseModel):
    """Input for list_schemas tool."""

    include_system: bool = Field(
        default=False,
        description="Include system schemas (_SYS_*, SYS, SYSTEM)",
    )


class SchemaInfo(BaseModel):
    """Information about a database schema."""

    name: str = Field(description="Schema name")
    owner: str = Field(description="Schema owner")
    table_count: int = Field(description="Number of tables in schema")
    is_system: bool = Field(description="Whether this is a system schema")


class ListSchemasOutput(BaseModel):
    """Output for list_schemas tool."""

    schemas: list[SchemaInfo] = Field(description="List of schema information")
    count: int = Field(description="Number of schemas returned")


# === List Tables ===


class ListTablesInput(BaseModel):
    """Input for list_tables tool."""

    schema_name: str = Field(
        description="Schema to list tables from",
    )
    include_views: bool = Field(
        default=True,
        description="Include views in the listing",
    )
    name_pattern: str | None = Field(
        default=None,
        description="Optional SQL LIKE pattern to filter table names (e.g., 'USER%')",
    )


class TableInfo(BaseModel):
    """Information about a database table or view."""

    name: str = Field(description="Table or view name")
    type: Literal["TABLE", "VIEW"] = Field(description="Object type: TABLE or VIEW")
    record_count: int = Field(description="Number of records in the table")
    column_count: int = Field(description="Number of columns")
    store_type: Literal["COLUMN", "ROW"] | None = Field(
        default=None,
        description="Storage type: COLUMN or ROW (None for views)",
    )
    is_column_table: bool = Field(
        description="Whether this table uses column store (False for views and row store tables)",
    )


class ListTablesOutput(BaseModel):
    """Output for list_tables tool."""

    tables: list[TableInfo] = Field(description="List of table information")
    schema_name: str = Field(description="Schema these tables belong to")
    count: int = Field(description="Number of tables returned")


# === Describe Table ===


class DescribeTableInput(BaseModel):
    """Input for describe_table tool."""

    table_name: str = Field(description="Name of the table to describe")
    schema_name: str = Field(
        description="Schema containing the table",
    )
    include_indexes: bool = Field(
        default=True,
        description="Include index information",
    )
    include_constraints: bool = Field(
        default=True,
        description="Include constraint information",
    )


class ColumnInfo(BaseModel):
    """Detailed information about a table column."""

    name: str = Field(description="Column name")
    data_type: str = Field(description="SAP HANA data type")
    length: int | None = Field(default=None, description="Column length")
    scale: int | None = Field(default=None, description="Numeric scale")
    nullable: bool = Field(description="Whether column allows NULL")
    default_value: str | None = Field(default=None, description="Default value expression")
    position: int = Field(description="Ordinal position in table")
    comment: str | None = Field(default=None, description="Column comment")


class IndexInfo(BaseModel):
    """Information about a table index."""

    name: str = Field(description="Index name")
    columns: list[str] = Field(description="Indexed columns")
    is_unique: bool = Field(description="Whether index enforces uniqueness")
    index_type: str = Field(description="Index type (e.g., BTREE, CPBTREE, INVERTED HASH)")


class ConstraintInfo(BaseModel):
    """Information about a table constraint."""

    name: str = Field(description="Constraint name")
    constraint_type: Literal["PRIMARY KEY", "UNIQUE", "CHECK"] = Field(
        description="Constraint type",
    )
    columns: list[str] = Field(description="Columns involved in the constraint")


class DescribeTableOutput(BaseModel):
    """Output for describe_table tool."""

    table_name: str = Field(description="Name of the described table")
    schema_name: str = Field(description="Schema containing the table")
    columns: list[ColumnInfo] = Field(description="Column definitions")
    indexes: list[IndexInfo] = Field(
        default_factory=list,
        description="Index information (empty if not requested or for views)",
    )
    constraints: list[ConstraintInfo] = Field(
        default_factory=list,
        description="Constraint information (empty if not requested or for views)",
    )
    is_view: bool = Field(
        default=False,
        description="Whether this is a view rather than a table",
    )


# === Get Sample Rows ===


class GetSampleRowsInput(BaseModel):
    """Input for get_sample_rows tool."""

    table_name: str = Field(description="Name of the table to sample")
    schema_name: str = Field(
        description="Schema containing the table",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of sample rows to retrieve (1-100)",
    )
    columns: list[str] | None = Field(
        default=None,
        description="Specific columns to include (None for all columns)",
    )
    where_clause: str | None = Field(
        default=None,
        description="Optional WHERE clause to filter samples (without 'WHERE' keyword)",
    )
    randomize: bool = Field(
        default=False,
        description="Randomize row selection (slower on large tables)",
    )


class SampleRowsOutput(BaseModel):
    """Output for get_sample_rows tool."""

    table_name: str = Field(description="Name of the sampled table")
    schema_name: str = Field(description="Schema containing the table")
    columns: list[str] = Field(description="Column names in the result set")
    rows: list[dict[str, Any]] = Field(description="Sample row data")
    row_count: int = Field(description="Number of rows returned")
    total_count: int = Field(description="Total number of rows in the table")
