"""Pydantic models for query execution tools (Layer 3) and errors.

Based on PRD Sections 6.3 and 7.
"""

from typing import Any

from pydantic import BaseModel, Field

# === Execute Query ===


class ExecuteQueryInput(BaseModel):
    """Input for execute_query tool."""

    sql: str = Field(description="SQL SELECT query to execute. Use $1, $2, etc. for parameters.")
    params: list[Any] | None = Field(
        default=None,
        description="Parameter values for the query (positional, matching $1, $2, etc.)",
    )
    limit: int | None = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum rows to return (applied if query lacks LIMIT)",
    )
    timeout_ms: int | None = Field(
        default=None,
        description="Query timeout in milliseconds (uses server default if not specified)",
    )


class QueryColumn(BaseModel):
    """Metadata about a result column."""

    name: str
    data_type: str


class ExecuteQueryOutput(BaseModel):
    """Output for execute_query tool."""

    columns: list[QueryColumn]
    rows: list[dict[str, Any]]
    row_count: int
    has_more: bool = Field(description="Whether results were truncated by limit")
    execution_time_ms: float
    query_hash: str = Field(description="Hash of executed query for reference")


# === Explain Query ===


class ExplainQueryInput(BaseModel):
    """Input for explain_query tool."""

    sql: str = Field(description="SQL query to explain")
    params: list[Any] | None = Field(
        default=None,
        description="Parameter values (for accurate estimates)",
    )
    analyze: bool = Field(
        default=False,
        description="Actually execute query to get real timings (slower but more accurate)",
    )
    format: str = Field(
        default="text",
        pattern="^(text|json|yaml)$",
        description="Output format for the plan",
    )
    verbose: bool = Field(
        default=False,
        description="Include additional detail in the plan",
    )
    buffers: bool = Field(
        default=False,
        description="Include buffer usage statistics (requires analyze=true)",
    )


class ExplainQueryOutput(BaseModel):
    """Output for explain_query tool."""

    plan: str | dict[str, Any] | list[Any] | None = Field(description="Query execution plan")
    format: str
    estimated_cost: float | None = Field(default=None, description="Total estimated cost")
    estimated_rows: int | None = Field(default=None, description="Estimated rows returned")
    actual_time_ms: float | None = Field(
        default=None, description="Actual execution time (if analyze=true)"
    )
    warnings: list[str] | None = Field(
        default=None, description="Potential performance issues detected"
    )


# === Error Models (PRD Section 7) ===


class ErrorDetail(BaseModel):
    """Detailed error information."""

    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error message")
    suggestion: str | None = Field(
        default=None, description="Actionable suggestion to resolve the error"
    )
    context: dict[str, Any] | None = Field(
        default=None, description="Additional context for debugging"
    )


class ToolError(BaseModel):
    """Standard error response for tool failures."""

    error: ErrorDetail
    tool_name: str
    input_received: dict[str, Any] | None = None
