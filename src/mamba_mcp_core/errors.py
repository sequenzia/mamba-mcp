"""Shared error model and factory for MCP server packages.

Provides a flat ToolError Pydantic model (HANA-style) and a factory function
that accepts a server-specific suggestions map, allowing each server to define
its own error codes and suggestions without the core depending on any
server's domain constants.
"""

from typing import Any

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    """Standard error response for tool failures.

    Flat structure with all fields at the top level. Each server's
    create_tool_error() wrapper can convert this to dict if needed
    for backward compatibility.
    """

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
    suggestions_map: dict[str, str] | None = None,
) -> ToolError:
    """Create a structured error response.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        tool_name: Name of the tool that generated the error.
        input_received: Input parameters that were received.
        context: Additional context for debugging.
        suggestion: Actionable suggestion (overrides suggestions_map lookup).
        suggestions_map: Server-specific mapping of error codes to suggestions.
            Each server passes its own ERROR_SUGGESTIONS dict here.

    Returns:
        ToolError model instance.
    """
    resolved_suggestion = suggestion
    if resolved_suggestion is None and suggestions_map is not None:
        resolved_suggestion = suggestions_map.get(code)

    return ToolError(
        code=code,
        message=message,
        suggestion=resolved_suggestion,
        context=context,
        tool_name=tool_name,
        input_received=input_received,
    )
