"""Structured error handling for MCP filesystem tools.

Based on spec Section 7.6. Follows the mamba-mcp-postgres error pattern
with error codes, suggestion mappings, structured responses, and custom exceptions.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """Error codes for filesystem MCP tools."""

    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    PATH_OUTSIDE_SANDBOX = "PATH_OUTSIDE_SANDBOX"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    BACKEND_NOT_CONFIGURED = "BACKEND_NOT_CONFIGURED"
    BACKEND_ERROR = "BACKEND_ERROR"
    INVALID_OPERATION = "INVALID_OPERATION"
    RATE_LIMITED = "RATE_LIMITED"
    SYMLINK_BLOCKED = "SYMLINK_BLOCKED"
    CONTENT_DECODE_ERROR = "CONTENT_DECODE_ERROR"


# Default suggestions for each error code
ERROR_SUGGESTIONS: dict[str, str] = {
    ErrorCode.PATH_NOT_FOUND: "Check the path exists with list_directory",
    ErrorCode.PATH_OUTSIDE_SANDBOX: "All paths must be within the configured base path",
    ErrorCode.PERMISSION_DENIED: "Server is in read-only mode or operation not allowed",
    ErrorCode.FILE_TOO_LARGE: ("Use offset/limit for chunked reading, or increase max_file_size"),
    ErrorCode.BACKEND_NOT_CONFIGURED: "Enable the backend in server configuration",
    ErrorCode.BACKEND_ERROR: "Check backend connectivity and credentials",
    ErrorCode.INVALID_OPERATION: "Review the operation parameters",
    ErrorCode.RATE_LIMITED: "Wait before retrying; reduce operation frequency",
    ErrorCode.SYMLINK_BLOCKED: "Symlinks are disabled; set follow_symlinks=true to allow",
    ErrorCode.CONTENT_DECODE_ERROR: "Try reading as binary (force_base64=true)",
}


def create_error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a structured MCP error response.

    Args:
        code: Machine-readable error code (from ErrorCode constants).
        message: Human-readable error message.
        details: Optional additional context for debugging.

    Returns:
        Dictionary with error_code, message, suggestion, and optional details.
    """
    response: dict[str, Any] = {
        "error_code": code,
        "message": message,
        "suggestion": ERROR_SUGGESTIONS.get(code, "An unexpected error occurred"),
    }
    if details is not None:
        response["details"] = details
    return response


# === Custom Exception Classes ===


class FSError(Exception):
    """Base exception for filesystem MCP errors.

    All filesystem-related exceptions inherit from this class,
    providing a consistent ``code`` and ``message`` interface.
    """

    code: str = "UNKNOWN_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PathNotFoundError(FSError):
    """File or directory does not exist."""

    code: str = ErrorCode.PATH_NOT_FOUND


class PathOutsideSandboxError(FSError):
    """Path resolves outside the configured sandbox."""

    code: str = ErrorCode.PATH_OUTSIDE_SANDBOX


class PermissionDeniedError(FSError):
    """Operation not permitted (read-only mode, overwrite blocked)."""

    code: str = ErrorCode.PERMISSION_DENIED


class FileTooLargeError(FSError):
    """File exceeds configured size limit."""

    code: str = ErrorCode.FILE_TOO_LARGE


class BackendNotConfiguredError(FSError):
    """Requested backend is not enabled."""

    code: str = ErrorCode.BACKEND_NOT_CONFIGURED


class BackendError(FSError):
    """Backend connectivity or operational error."""

    code: str = ErrorCode.BACKEND_ERROR


class InvalidOperationError(FSError):
    """Invalid operation parameters or unsupported action."""

    code: str = ErrorCode.INVALID_OPERATION


class RateLimitedError(FSError):
    """Rate limit exceeded."""

    code: str = ErrorCode.RATE_LIMITED


class SymlinkBlockedError(FSError):
    """Symlink access blocked by policy."""

    code: str = ErrorCode.SYMLINK_BLOCKED


class ContentDecodeError(FSError):
    """Text decoding failed."""

    code: str = ErrorCode.CONTENT_DECODE_ERROR
