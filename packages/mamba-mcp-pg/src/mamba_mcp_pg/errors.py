"""Structured error handling for MCP tools.

Based on PRD Section 7. Uses mamba-mcp-core for shared error model
and fuzzy matching, with a thin wrapper to preserve dict return type.
"""

from typing import Any

from mamba_mcp_core.errors import create_tool_error as _core_create_tool_error
from mamba_mcp_core.fuzzy import find_similar_names


class ErrorCode:
    """Error codes from PRD Section 7.2."""

    SCHEMA_NOT_FOUND = "SCHEMA_NOT_FOUND"
    TABLE_NOT_FOUND = "TABLE_NOT_FOUND"
    COLUMN_NOT_FOUND = "COLUMN_NOT_FOUND"
    INVALID_SQL = "INVALID_SQL"
    WRITE_OPERATION_DENIED = "WRITE_OPERATION_DENIED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PARAMETER_ERROR = "PARAMETER_ERROR"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"


# Default suggestions for each error code
ERROR_SUGGESTIONS: dict[str, str] = {
    ErrorCode.SCHEMA_NOT_FOUND: "List available schemas with list_schemas",
    ErrorCode.TABLE_NOT_FOUND: "List tables in schema with list_tables",
    ErrorCode.COLUMN_NOT_FOUND: "Describe table to see available columns",
    ErrorCode.INVALID_SQL: "Review query syntax",
    ErrorCode.WRITE_OPERATION_DENIED: "This server only supports read operations",
    ErrorCode.QUERY_TIMEOUT: "Simplify query or increase timeout",
    ErrorCode.CONNECTION_ERROR: "Check database connectivity",
    ErrorCode.PERMISSION_DENIED: "Contact database administrator",
    ErrorCode.PARAMETER_ERROR: "Review parameter constraints",
    ErrorCode.PATH_NOT_FOUND: "Tables may not be related via foreign keys",
}


def create_tool_error(
    code: str,
    message: str,
    tool_name: str,
    input_received: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    suggestion: str | None = None,
) -> dict[str, Any]:
    """Create a structured error response.

    Wraps core create_tool_error and converts to dict to preserve
    existing PG tool return type contract (OutputModel | dict[str, Any]).

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        tool_name: Name of the tool that generated the error.
        input_received: Input parameters that were received.
        context: Additional context for debugging.
        suggestion: Actionable suggestion (uses default if not provided).

    Returns:
        Dictionary representation of ToolError.
    """
    error = _core_create_tool_error(
        code=code,
        message=message,
        tool_name=tool_name,
        input_received=input_received,
        context=context,
        suggestion=suggestion,
        suggestions_map=ERROR_SUGGESTIONS,
    )
    return error.model_dump()


__all__ = ["ErrorCode", "ERROR_SUGGESTIONS", "create_tool_error", "find_similar_names"]
