"""Structured error handling for MCP tools.

Based on PRD Section 7.
"""

from typing import Any

from mamba_mcp_pg.models.results import ErrorDetail, ToolError


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
    error = ToolError(
        error=ErrorDetail(
            code=code,
            message=message,
            suggestion=suggestion or ERROR_SUGGESTIONS.get(code),
            context=context,
        ),
        tool_name=tool_name,
        input_received=input_received,
    )
    return error.model_dump()


def find_similar_names(name: str, candidates: list[str], max_results: int = 3) -> list[str]:
    """Find similar names using Levenshtein distance.

    Args:
        name: The name to match against.
        candidates: List of candidate names.
        max_results: Maximum number of results to return.

    Returns:
        List of similar names sorted by similarity.
    """

    def levenshtein_distance(s1: str, s2: str) -> int:
        """Calculate Levenshtein distance between two strings."""
        if len(s1) < len(s2):
            return levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]

    # Calculate distances and filter by threshold
    scored = [(c, levenshtein_distance(name.lower(), c.lower())) for c in candidates]
    scored.sort(key=lambda x: x[1])

    # Return names within edit distance of 3
    return [c for c, d in scored[:max_results] if d <= 3]
