"""Pydantic models for schema discovery tools (Layer 1).

Based on PRD Section 6.1.
"""

from typing import Any

from pydantic import BaseModel, Field

# === List Schemas ===


class ListSchemasInput(BaseModel):
    """Input for list_schemas tool."""

    include_system: bool = Field(
        default=False,
        description="Include system schemas (pg_*, information_schema)",
    )


class SchemaInfo(BaseModel):
    """Information about a database schema."""

    name: str = Field(description="Schema name")
    owner: str = Field(description="Schema owner")
    description: str | None = Field(default=None, description="Schema comment/description")
    table_count: int = Field(description="Number of tables in schema")


class ListSchemasOutput(BaseModel):
    """Output for list_schemas tool."""

    schemas: list[SchemaInfo]
    total_count: int


# === List Tables ===


class ListTablesInput(BaseModel):
    """Input for list_tables tool."""

    schema_name: str = Field(
        default="public",
        description="Schema to list tables from",
    )
    include_views: bool = Field(
        default=True,
        description="Include views in the listing",
    )
    name_pattern: str | None = Field(
        default=None,
        description="Optional LIKE pattern to filter table names (e.g., 'user%')",
    )


class TableInfo(BaseModel):
    """Information about a database table."""

    name: str = Field(description="Table name")
    schema_name: str = Field(description="Schema containing the table")
    type: str = Field(description="Object type: 'table' or 'view'")
    description: str | None = Field(default=None, description="Table comment/description")
    estimated_row_count: int = Field(description="Estimated row count from pg_stat")
    size_bytes: int | None = Field(default=None, description="Table size in bytes (null for views)")
    size_pretty: str | None = Field(
        default=None, description="Human-readable size (e.g., '1.2 MB')"
    )
    has_primary_key: bool = Field(description="Whether table has a primary key")
    column_count: int = Field(description="Number of columns")


class ListTablesOutput(BaseModel):
    """Output for list_tables tool."""

    tables: list[TableInfo]
    schema_name: str
    total_count: int


# === Describe Table ===


class DescribeTableInput(BaseModel):
    """Input for describe_table tool."""

    table_name: str = Field(description="Name of the table to describe")
    schema_name: str = Field(
        default="public",
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


class ForeignKeyRef(BaseModel):
    """Foreign key reference information."""

    constraint_name: str
    referenced_schema: str
    referenced_table: str
    referenced_column: str
    on_update: str
    on_delete: str


class ColumnInfo(BaseModel):
    """Detailed information about a table column."""

    name: str = Field(description="Column name")
    data_type: str = Field(description="PostgreSQL data type")
    is_nullable: bool = Field(description="Whether column allows NULL")
    default_value: str | None = Field(default=None, description="Default value expression")
    description: str | None = Field(default=None, description="Column comment")
    is_primary_key: bool = Field(default=False, description="Part of primary key")
    is_unique: bool = Field(default=False, description="Has unique constraint")
    foreign_key: ForeignKeyRef | None = Field(
        default=None, description="FK reference if applicable"
    )
    character_maximum_length: int | None = Field(
        default=None, description="Max length for char types"
    )
    numeric_precision: int | None = Field(default=None, description="Precision for numeric types")
    numeric_scale: int | None = Field(default=None, description="Scale for numeric types")


class IndexInfo(BaseModel):
    """Information about a table index."""

    name: str = Field(description="Index name")
    columns: list[str] = Field(description="Indexed columns")
    is_unique: bool = Field(description="Whether index enforces uniqueness")
    is_primary: bool = Field(description="Whether this is the primary key index")
    index_type: str = Field(description="Index type (btree, hash, gin, etc.)")
    description: str | None = Field(default=None, description="Index comment")


class ConstraintInfo(BaseModel):
    """Information about a table constraint."""

    name: str = Field(description="Constraint name")
    type: str = Field(description="Constraint type (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK)")
    columns: list[str] = Field(description="Columns involved")
    definition: str | None = Field(default=None, description="Constraint definition (for CHECK)")
    referenced_table: str | None = Field(default=None, description="Referenced table (for FK)")


class DescribeTableOutput(BaseModel):
    """Output for describe_table tool."""

    table_name: str
    schema_name: str
    type: str  # 'table' or 'view'
    description: str | None = None
    columns: list[ColumnInfo]
    indexes: list[IndexInfo] | None = None
    constraints: list[ConstraintInfo] | None = None
    estimated_row_count: int
    size_pretty: str | None = None


# === Get Sample Rows ===


class GetSampleRowsInput(BaseModel):
    """Input for get_sample_rows tool."""

    table_name: str = Field(description="Name of the table to sample")
    schema_name: str = Field(
        default="public",
        description="Schema containing the table",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of sample rows to retrieve",
    )
    columns: list[str] | None = Field(
        default=None,
        description="Specific columns to include (null for all)",
    )
    where_clause: str | None = Field(
        default=None,
        description="Optional WHERE clause to filter samples (without 'WHERE' keyword)",
    )
    randomize: bool = Field(
        default=False,
        description="Randomize row selection (slower on large tables)",
    )


class GetSampleRowsOutput(BaseModel):
    """Output for get_sample_rows tool."""

    table_name: str
    schema_name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    total_table_rows: int
    note: str | None = Field(
        default=None,
        description="Additional context about the sample (e.g., 'randomized', 'filtered')",
    )
