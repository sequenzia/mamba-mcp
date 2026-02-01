"""Pydantic I/O models for Layer 3 query execution tools.

Based on Spec Sections 5.3 and 9.2.

Provides input validation and structured output models for execute_query
and explain_query tools. Input models enforce SQL constraints (non-empty,
max length). Output models capture query results, execution metadata,
and HANA-specific execution plan structure.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

# Maximum SQL query length (characters)
MAX_SQL_LENGTH = 100_000


# === Execute Query ===


class ExecuteQueryInput(BaseModel):
    """Input for execute_query tool.

    Validates SQL is non-empty and within length limits. Parameters use
    HANA's positional (?) or named (:param) placeholders.
    """

    sql: str = Field(
        description=(
            "SQL SELECT query to execute. Use ? for positional or :name for named parameters."
        ),
        min_length=1,
        max_length=MAX_SQL_LENGTH,
    )
    params: list[Any] | dict[str, Any] | None = Field(
        default=None,
        description="Bind parameter values (list for positional ?, dict for named :param)",
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum rows to return (applied if query lacks LIMIT)",
    )
    timeout_ms: int | None = Field(
        default=None,
        ge=1,
        description="Query timeout in milliseconds (uses server default if not specified)",
    )

    @field_validator("sql")
    @classmethod
    def sql_must_not_be_blank(cls, v: str) -> str:
        """Reject SQL that is only whitespace."""
        if not v.strip():
            msg = "SQL query must not be empty or whitespace-only"
            raise ValueError(msg)
        return v


class QueryResult(BaseModel):
    """Structured query result with metadata.

    Captures column names, typed rows, execution timing, and truncation
    status. The truncated flag indicates when the result set was capped
    by the configured row limit.
    """

    columns: list[str] = Field(description="Column names from the result set")
    rows: list[dict[str, Any]] = Field(description="Result rows as column-name-keyed dicts")
    row_count: int = Field(ge=0, description="Number of rows returned")
    execution_time_ms: float = Field(ge=0, description="Query execution time in milliseconds")
    truncated: bool = Field(
        default=False, description="Whether the result set was truncated by the row limit"
    )
    warning: str | None = Field(
        default=None, description="Optional warning message (e.g., truncation notice)"
    )


class ExecuteQueryOutput(BaseModel):
    """Output for execute_query tool.

    Wraps QueryResult with a query_hash for caching reference and
    deduplication.
    """

    result: QueryResult = Field(description="Query result data and metadata")
    query_hash: str = Field(description="Hash of executed query for caching reference")


# === Explain Query ===


class ExplainQueryInput(BaseModel):
    """Input for explain_query tool.

    HANA's EXPLAIN PLAN mechanism writes to EXPLAIN_PLAN_TABLE, so this
    tool transparently handles the write-read-cleanup cycle. Supports
    text and JSON output formats.
    """

    sql: str = Field(
        description="SQL query to explain",
        min_length=1,
        max_length=MAX_SQL_LENGTH,
    )
    params: list[Any] | dict[str, Any] | None = Field(
        default=None,
        description="Bind parameter values (for accurate cost estimates)",
    )
    format: str = Field(
        default="text",
        pattern="^(text|json)$",
        description="Output format for the plan (text or json)",
    )

    @field_validator("sql")
    @classmethod
    def sql_must_not_be_blank(cls, v: str) -> str:
        """Reject SQL that is only whitespace."""
        if not v.strip():
            msg = "SQL query must not be empty or whitespace-only"
            raise ValueError(msg)
        return v


class ExplainPlanNode(BaseModel):
    """A single node in HANA's execution plan.

    Models the structure returned from EXPLAIN_PLAN_TABLE, capturing
    the operator type, target table/schema, cost estimates, and
    additional operator-specific details.
    """

    operator: str = Field(description="Plan operator name (e.g., TABLE SCAN, INDEX SCAN)")
    table_name: str | None = Field(default=None, description="Target table name (if applicable)")
    schema_name: str | None = Field(default=None, description="Target schema name (if applicable)")
    cost: float | None = Field(default=None, ge=0, description="Estimated operator cost")
    cardinality: float | None = Field(
        default=None, ge=0, description="Estimated output cardinality (row count)"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional operator-specific details"
    )


class ExplainQueryOutput(BaseModel):
    """Output for explain_query tool.

    Contains the full execution plan as a list of nodes, aggregate cost,
    plan type classification, and the original query for reference.
    """

    nodes: list[ExplainPlanNode] = Field(description="Execution plan nodes")
    total_cost: float | None = Field(default=None, ge=0, description="Total estimated plan cost")
    plan_type: str = Field(description="Plan type classification (e.g., 'HANA EXPLAIN PLAN')")
    original_query: str = Field(description="The original SQL query that was explained")
