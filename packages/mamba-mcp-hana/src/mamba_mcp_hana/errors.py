"""Structured error handling for MCP tools with fuzzy matching.

Based on Spec Section 5.7. Uses mamba-mcp-core for shared error model
and fuzzy matching, with a thin wrapper to preserve ToolError return type.
"""

from typing import Any

from mamba_mcp_core.errors import ToolError
from mamba_mcp_core.errors import create_tool_error as _core_create_tool_error
from mamba_mcp_core.fuzzy import find_similar_names


def suggest_similar(
    name: str,
    candidates: list[str],
    max_suggestions: int = 3,
) -> list[str]:
    """Find similar names using Levenshtein distance.

    Backward-compatible wrapper around core's find_similar_names.
    Maps the legacy `max_suggestions` parameter to core's `max_results`.

    Args:
        name: The name to match against.
        candidates: List of candidate names to search.
        max_suggestions: Maximum number of suggestions to return.

    Returns:
        List of similar names sorted by edit distance (closest first).
    """
    return find_similar_names(name, candidates, max_results=max_suggestions)


class ErrorCode:
    """Error codes for SAP HANA MCP tools."""

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
    VIEW_NOT_FOUND = "VIEW_NOT_FOUND"
    PROCEDURE_NOT_FOUND = "PROCEDURE_NOT_FOUND"


# Default suggestions for each error code
ERROR_SUGGESTIONS: dict[str, str] = {
    ErrorCode.SCHEMA_NOT_FOUND: "List available schemas with list_schemas",
    ErrorCode.TABLE_NOT_FOUND: "List tables in schema with list_tables",
    ErrorCode.COLUMN_NOT_FOUND: "Describe table to see available columns with describe_table",
    ErrorCode.INVALID_SQL: "Review query syntax; only SELECT and WITH statements are allowed",
    ErrorCode.WRITE_OPERATION_DENIED: "This server only supports read operations",
    ErrorCode.QUERY_TIMEOUT: "Simplify query or increase statement_timeout",
    ErrorCode.CONNECTION_ERROR: "Check database connectivity and credentials",
    ErrorCode.PERMISSION_DENIED: "Contact database administrator to grant required privileges",
    ErrorCode.PARAMETER_ERROR: "Review parameter constraints and types",
    ErrorCode.PATH_NOT_FOUND: "Tables may not be related via foreign keys",
    ErrorCode.VIEW_NOT_FOUND: "List calculation views with list_calculation_views",
    ErrorCode.PROCEDURE_NOT_FOUND: "List procedures with list_procedures",
}


def create_tool_error(
    code: str,
    message: str,
    tool_name: str,
    input_received: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    suggestion: str | None = None,
) -> ToolError:
    """Create a structured error response.

    Wraps core create_tool_error to preserve existing HANA tool return
    type contract (ToolError model instance).

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        tool_name: Name of the tool that generated the error.
        input_received: Input parameters that were received.
        context: Additional context for debugging.
        suggestion: Actionable suggestion (uses default if not provided).

    Returns:
        ToolError model instance.
    """
    return _core_create_tool_error(
        code=code,
        message=message,
        tool_name=tool_name,
        input_received=input_received,
        context=context,
        suggestion=suggestion,
        suggestions_map=ERROR_SUGGESTIONS,
    )


__all__ = [
    "ErrorCode",
    "ERROR_SUGGESTIONS",
    "ToolError",
    "create_tool_error",
    "suggest_similar",
    "find_similar_names",
]
