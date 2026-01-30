"""Pydantic models for MCP tool inputs and outputs."""

from mamba_mcp_postgres.models.relationships import (
    FindJoinPathInput,
    FindJoinPathOutput,
    ForeignKeyRelation,
    GetForeignKeysInput,
    GetForeignKeysOutput,
    JoinPath,
    JoinStep,
)
from mamba_mcp_postgres.models.results import (
    ErrorDetail,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    ExplainQueryInput,
    ExplainQueryOutput,
    QueryColumn,
    ToolError,
)
from mamba_mcp_postgres.models.schema import (
    ColumnInfo,
    ConstraintInfo,
    DescribeTableInput,
    DescribeTableOutput,
    ForeignKeyRef,
    GetSampleRowsInput,
    GetSampleRowsOutput,
    IndexInfo,
    ListSchemasInput,
    ListSchemasOutput,
    ListTablesInput,
    ListTablesOutput,
    SchemaInfo,
    TableInfo,
)

__all__ = [
    # Schema models
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
    "ForeignKeyRef",
    "GetSampleRowsInput",
    "GetSampleRowsOutput",
    # Relationship models
    "GetForeignKeysInput",
    "GetForeignKeysOutput",
    "ForeignKeyRelation",
    "FindJoinPathInput",
    "FindJoinPathOutput",
    "JoinStep",
    "JoinPath",
    # Result models
    "ExecuteQueryInput",
    "ExecuteQueryOutput",
    "QueryColumn",
    "ExplainQueryInput",
    "ExplainQueryOutput",
    "ErrorDetail",
    "ToolError",
]
