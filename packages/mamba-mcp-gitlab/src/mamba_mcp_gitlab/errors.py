"""Error codes, suggestions, and error handling for GitLab MCP Server.

Based on Spec Section 7.7 and 9.3. Uses mamba-mcp-core for shared error model
and fuzzy matching, with a thin wrapper to preserve dict return type.

Includes helper functions for fuzzy name suggestions, enhanced error context,
and pagination parameter clamping (Spec Section 9.3 - Error UX).
"""

from typing import Any

from mamba_mcp_core.errors import create_tool_error as _core_create_tool_error
from mamba_mcp_core.fuzzy import find_similar_names

# Pagination constants
PAGINATION_DEFAULT_PER_PAGE = 20
PAGINATION_MIN_PER_PAGE = 1
PAGINATION_MAX_PER_PAGE = 100


class ErrorCode:
    """Error codes for GitLab MCP tools (Spec Section 7.7)."""

    AUTH_FAILED = "AUTH_FAILED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    MERGE_REQUEST_NOT_FOUND = "MERGE_REQUEST_NOT_FOUND"
    ISSUE_NOT_FOUND = "ISSUE_NOT_FOUND"
    PIPELINE_NOT_FOUND = "PIPELINE_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    API_ERROR = "API_ERROR"
    BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
    READ_ONLY = "READ_ONLY"


# Default suggestions for each error code (from Spec Section 7.7)
ERROR_SUGGESTIONS: dict[str, str] = {
    ErrorCode.AUTH_FAILED: (
        "Check your GitLab token or OAuth credentials. Verify the token hasn't expired."
    ),
    ErrorCode.FORBIDDEN: (
        "Your token lacks required scopes. Required: `api` (or `read_api` for read-only)."
    ),
    ErrorCode.NOT_FOUND: "Resource not found. Check the project_id and resource IID.",
    ErrorCode.PROJECT_NOT_FOUND: "Project not found. Use `search` to find the correct project.",
    ErrorCode.MERGE_REQUEST_NOT_FOUND: (
        "Merge request not found. Use `list_mrs` to see available MRs."
    ),
    ErrorCode.ISSUE_NOT_FOUND: "Issue not found. Use `list_issues` to see available issues.",
    ErrorCode.PIPELINE_NOT_FOUND: (
        "Pipeline not found. Use `list_pipelines` to see available pipelines."
    ),
    ErrorCode.RATE_LIMITED: "GitLab API rate limit reached. Wait before retrying.",
    ErrorCode.VALIDATION_ERROR: (
        "Invalid input parameters. Check the tool's parameter requirements."
    ),
    ErrorCode.CONNECTION_ERROR: (
        "Cannot reach GitLab at the configured URL. Check network and URL settings."
    ),
    ErrorCode.API_ERROR: ("GitLab API returned an unexpected error. Check GitLab server status."),
    ErrorCode.BRANCH_NOT_FOUND: "Branch not found. Check branch name and project.",
    ErrorCode.READ_ONLY: (
        "This server is running in read-only mode. "
        "Set MAMBA_MCP_GITLAB_READ_ONLY=false to enable write operations."
    ),
}


# Names of write tools that are disabled in read-only mode
WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_mr",
        "update_mr",
        "create_issue",
        "update_issue",
        "add_issue_comment",
    }
)


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
    the PG-style return type contract (OutputModel | dict[str, Any]).

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


def check_read_only(read_only: bool, tool_name: str) -> dict[str, Any] | None:
    """Check if a write tool should be blocked by read-only mode.

    Intended to be called at the start of each write tool handler. Returns
    a structured error dict if read_only is True, or None if the tool may
    proceed.

    Args:
        read_only: The current read_only setting from ``settings.gitlab.read_only``.
        tool_name: Name of the write tool being invoked.

    Returns:
        Structured error dict if blocked, or None if allowed.
    """
    if not read_only:
        return None
    return create_tool_error(
        code=ErrorCode.READ_ONLY,
        message=f"Tool '{tool_name}' is disabled in read-only mode",
        tool_name=tool_name,
    )


def suggest_project_names(
    project_name: str,
    known_projects: list[str],
) -> str:
    """Build a suggestion string with fuzzy project name matches.

    Defensively wraps find_similar_names so fuzzy matching never propagates
    exceptions to the caller. If no similar names are found, returns the
    default PROJECT_NOT_FOUND suggestion.

    Args:
        project_name: The project name that was not found.
        known_projects: List of known project names to search.

    Returns:
        Suggestion string, either with similar names or the default message.
    """
    try:
        similar = find_similar_names(project_name, known_projects)
    except Exception:
        return ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    if similar:
        names_str = ", ".join(f"'{name}'" for name in similar)
        return f"Did you mean: {names_str}? Use `search` to find the correct project."
    return ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]


def suggest_branch_names(
    branch_name: str,
    known_branches: list[str],
) -> str:
    """Build a suggestion string with fuzzy branch name matches.

    Defensively wraps find_similar_names so fuzzy matching never propagates
    exceptions to the caller. If no similar names are found, returns the
    default BRANCH_NOT_FOUND suggestion.

    Args:
        branch_name: The branch name that was not found.
        known_branches: List of known branch names to search.

    Returns:
        Suggestion string, either with similar names or the default message.
    """
    try:
        similar = find_similar_names(branch_name, known_branches)
    except Exception:
        return ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    if similar:
        names_str = ", ".join(f"'{name}'" for name in similar)
        return f"Did you mean: {names_str}? Check branch name and project."
    return ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]


def build_error_context(
    *,
    elapsed_ms: float | None = None,
    endpoint: str | None = None,
    status_code: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an enhanced error context dict with request timing and API details.

    Intended to be passed as the ``context`` parameter to ``create_tool_error()``.
    Only includes keys that have non-None values, keeping error payloads clean.

    Args:
        elapsed_ms: Request duration in milliseconds.
        endpoint: The GitLab API endpoint that failed (e.g., "/projects/123/merge_requests").
        status_code: HTTP response status code from GitLab.
        extra: Additional context entries to merge in.

    Returns:
        Context dictionary with non-None values.
    """
    ctx: dict[str, Any] = {}
    if elapsed_ms is not None:
        ctx["elapsed_ms"] = round(elapsed_ms, 2)
    if endpoint is not None:
        ctx["endpoint"] = endpoint
    if status_code is not None:
        ctx["status_code"] = status_code
    if extra:
        ctx.update(extra)
    return ctx


def clamp_pagination(
    page: int | None = None,
    per_page: int | None = None,
) -> tuple[int, int]:
    """Clamp pagination parameters to valid GitLab API ranges.

    Ensures page >= 1 and per_page in [1, 100], applying the default
    of 20 items per page when not specified. This enforces consistent
    pagination behavior across all list tool handlers.

    Args:
        page: Requested page number (1-indexed). Defaults to 1.
        per_page: Requested items per page. Defaults to 20, clamped to [1, 100].

    Returns:
        Tuple of (page, per_page) with validated values.
    """
    if page is None or page < 1:
        page = 1
    if per_page is None:
        per_page = PAGINATION_DEFAULT_PER_PAGE
    per_page = max(PAGINATION_MIN_PER_PAGE, min(per_page, PAGINATION_MAX_PER_PAGE))
    return page, per_page


__all__ = [
    "ErrorCode",
    "ERROR_SUGGESTIONS",
    "PAGINATION_DEFAULT_PER_PAGE",
    "PAGINATION_MAX_PER_PAGE",
    "PAGINATION_MIN_PER_PAGE",
    "WRITE_TOOL_NAMES",
    "build_error_context",
    "check_read_only",
    "clamp_pagination",
    "create_tool_error",
    "find_similar_names",
    "suggest_branch_names",
    "suggest_project_names",
]
