"""Structured error handling for MCP tools with fuzzy matching.

Based on Spec Section 5.7.
"""

from typing import Any

from pydantic import BaseModel, Field


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


class ToolError(BaseModel):
    """Standard error response for tool failures."""

    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error message")
    suggestion: str | None = Field(
        default=None, description="Actionable suggestion to resolve the error"
    )
    context: dict[str, Any] | None = Field(
        default=None, description="Additional context for debugging"
    )
    tool_name: str = Field(description="Name of the tool that generated the error")
    input_received: dict[str, Any] | None = Field(
        default=None, description="Input parameters that were received"
    )


def create_tool_error(
    code: str,
    message: str,
    tool_name: str,
    input_received: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    suggestion: str | None = None,
) -> ToolError:
    """Create a structured error response.

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
    return ToolError(
        code=code,
        message=message,
        suggestion=suggestion or ERROR_SUGGESTIONS.get(code),
        context=context,
        tool_name=tool_name,
        input_received=input_received,
    )


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings.

    Uses the Wagner-Fischer dynamic programming algorithm with
    two-row optimization for O(min(m,n)) space complexity.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        Minimum number of single-character edits to transform s1 into s2.
    """
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
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


def suggest_similar(
    name: str,
    candidates: list[str],
    max_suggestions: int = 3,
) -> list[str]:
    """Find similar names using Levenshtein distance.

    Compares the input name against all candidates (case-insensitive)
    and returns the closest matches within an edit distance threshold.
    The threshold scales with the length of the input name.

    Args:
        name: The name to match against.
        candidates: List of candidate names to search.
        max_suggestions: Maximum number of suggestions to return.

    Returns:
        List of similar names sorted by edit distance (closest first).
        Returns empty list if no candidates are within the threshold.
    """
    if not candidates:
        return []

    # Threshold scales with name length: min 2, max 5
    threshold = max(2, min(len(name) // 2, 5))

    scored = [
        (candidate, _levenshtein_distance(name.lower(), candidate.lower()))
        for candidate in candidates
    ]
    scored.sort(key=lambda x: x[1])

    return [candidate for candidate, distance in scored[:max_suggestions] if distance <= threshold]
