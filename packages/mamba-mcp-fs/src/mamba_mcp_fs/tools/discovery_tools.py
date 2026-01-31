"""Discovery tools for filesystem browsing and reading.

Layer 1 tools are read-only and always available. They help AI assistants
discover and understand filesystem structure.

Based on spec Section 5.1 (REQ-001 through REQ-004).
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_fs.content import detect_mime_type, is_text_content
from mamba_mcp_fs.errors import (
    ErrorCode,
    FSError,
    create_error_response,
)
from mamba_mcp_fs.models.files import FileEntry, SearchResult
from mamba_mcp_fs.models.responses import (
    FileInfoResponse,
    ListDirectoryResponse,
    ReadFileResponse,
    SearchResponse,
)
from mamba_mcp_fs.server import AppContext, mcp

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_directory(
    path: str,
    backend: str | None = None,
    include_hidden: bool | None = None,
    pattern: str | None = None,
    max_entries: int = 1000,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListDirectoryResponse | dict[str, Any]:
    """List files and directories at a given path.

    Returns metadata for each entry including name, size, type, and
    last modified date. Use this as a starting point to explore filesystem
    structure and navigate to relevant files.

    Args:
        path: Directory path to list. Supports local paths and s3://bucket/prefix paths.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.
        include_hidden: Include hidden files/dotfiles. Default: per server config.
        pattern: Glob pattern to filter entries (e.g., '*.py'). Default: None (all files).
        max_entries: Maximum entries to return (1-10000). Default: 1000.

    Returns:
        Directory listing with file/directory entries and metadata.

    Example:
        list_directory(path="/data") -> {"path": "/data", "entries": [...], "total_count": 5}
    """
    start_time = time.perf_counter()
    logger.debug(
        "list_directory called with path=%s, backend=%s, include_hidden=%s, "
        "pattern=%s, max_entries=%d",
        path,
        backend,
        include_hidden,
        pattern,
        max_entries,
    )

    if ctx is None:
        logger.error("list_directory: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Clamp max_entries to valid range
    max_entries = max(1, min(10000, max_entries))

    try:
        # Get the appropriate backend and resolved path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        # Get directory listing from the backend
        raw_entries: list[dict[str, Any]] = backend_instance.ls(resolved_path, detail=True)

        # Apply hidden file filtering via security validator
        # Pass include_hidden to override config default
        filtered_entries = _filter_hidden(raw_entries, app_ctx, include_hidden)

        # Apply glob pattern filtering if provided
        if pattern is not None:
            filtered_entries = _filter_by_pattern(filtered_entries, pattern)

        # Count total before truncation
        total_count = len(filtered_entries)
        has_more = total_count > max_entries

        # Truncate at max_entries
        truncated = filtered_entries[:max_entries]

        # Map to FileEntry models
        entries = [_to_file_entry(entry) for entry in truncated]

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_directory completed in %.2fms, returned %d/%d entries",
            elapsed_ms,
            len(entries),
            total_count,
        )

        return ListDirectoryResponse(
            path=path,
            backend=backend_name,
            entries=entries,
            total_count=len(entries),
            has_more=has_more,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_directory failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        # BackendManager wraps FSError subclasses (e.g. PathOutsideSandboxError)
        # in BackendError, but the original code is more informative.
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(
            error_code,
            error_message,
            {"path": path, "backend": backend},
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_directory unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )


# SHA-256 chunk size for large file hashing (64 KB)
_CHECKSUM_CHUNK_SIZE = 65536


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def read_file(
    path: str,
    backend: str | None = None,
    encoding: str = "utf-8",
    offset: int = 0,
    limit: int | None = None,
    force_text: bool = False,
    force_base64: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ReadFileResponse | dict[str, Any]:
    """Read the contents of a file with smart content type detection.

    Text files are returned as text, binary files as base64-encoded content.
    Supports chunked reading for large files via offset/limit parameters.

    Args:
        path: Path to the file to read. Supports local paths and s3:// paths.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.
        encoding: Text encoding to use for decoding. Default: 'utf-8'.
        offset: Byte offset to start reading from. Default: 0.
        limit: Maximum bytes to read. Default: entire file up to size limit.
        force_text: Force text interpretation even for binary-detected files. Default: false.
        force_base64: Force base64 encoding for all content. Default: false.

    Returns:
        File content with metadata including encoding type, MIME type, and chunk info.

    Example:
        read_file(path="/data/report.csv") -> {"content": "col1,col2\\n...", "encoding": "text"}
    """
    start_time = time.perf_counter()
    logger.debug(
        "read_file called with path=%s, backend=%s, encoding=%s, "
        "offset=%d, limit=%s, force_text=%s, force_base64=%s",
        path,
        backend,
        encoding,
        offset,
        limit,
        force_text,
        force_base64,
    )

    if ctx is None:
        logger.error("read_file: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        # Get the appropriate backend and resolved path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        # Get file info to determine size and check limits
        raw_info: dict[str, Any] = backend_instance.info(path)
        total_size = int(raw_info.get("size", 0) or 0)

        # Determine the applicable size limit from config
        size_limit = _get_size_limit(app_ctx, backend_name)

        # Check if this is a chunked read (offset or limit specified)
        is_chunked = offset > 0 or limit is not None

        # Enforce size limit for full reads (no offset/limit)
        if not is_chunked and total_size > size_limit:
            return create_error_response(
                ErrorCode.FILE_TOO_LARGE,
                f"File size ({total_size} bytes) exceeds limit ({size_limit} bytes). "
                "Use offset/limit for chunked reading.",
                {"path": path, "size_bytes": total_size, "limit": size_limit},
            )

        # Calculate read boundaries
        read_start = offset
        if limit is not None:
            read_end = offset + limit
        else:
            read_end = None  # Read to end of file

        # Read content from backend -- only the requested chunk is loaded
        if read_end is not None:
            raw_content = backend_instance.cat_file(path, start=read_start, end=read_end)
        elif read_start > 0:
            raw_content = backend_instance.cat_file(path, start=read_start, end=None)
        else:
            raw_content = backend_instance.cat_file(path)

        bytes_read = len(raw_content)

        # Determine has_more: whether there's content beyond what we read
        if read_end is not None:
            has_more = read_end < total_size
        else:
            has_more = False

        # is_truncated: file exceeded size limit but we served a chunk
        is_truncated = is_chunked and total_size > size_limit

        # Detect MIME type from path and content
        mime_type = detect_mime_type(resolved_path, raw_content if raw_content else None)

        # Smart content detection and encoding
        content_str, content_encoding = _encode_content(
            raw_content=raw_content,
            mime_type=mime_type,
            text_encoding=encoding,
            force_text=force_text,
            force_base64=force_base64,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "read_file completed in %.2fms for %s (%d bytes, %s)",
            elapsed_ms,
            path,
            bytes_read,
            content_encoding,
        )

        return ReadFileResponse(
            path=path,
            backend=backend_name,
            content=content_str,
            encoding=content_encoding,
            mime_type=mime_type,
            size_bytes=total_size,
            bytes_read=bytes_read,
            offset=offset,
            has_more=has_more,
            is_truncated=is_truncated,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("read_file failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(
            error_code,
            error_message,
            {"path": path, "backend": backend},
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("read_file unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )


def _get_size_limit(app_ctx: AppContext, backend_name: str) -> int:
    """Get the file size limit for the given backend.

    Args:
        app_ctx: Application context with settings.
        backend_name: Backend name ('local' or 's3').

    Returns:
        Max file size in bytes.
    """
    if backend_name == "s3":
        return app_ctx.settings.s3.max_file_size
    return app_ctx.settings.local.max_file_size


def _encode_content(
    raw_content: bytes,
    mime_type: str,
    text_encoding: str,
    force_text: bool,
    force_base64: bool,
) -> tuple[str, str]:
    """Encode raw file content based on smart content detection.

    Smart detection flow:
    1. force_base64 overrides everything -> always base64
    2. Detect if content is text via MIME type and heuristics
    3. If text (or force_text): try decoding with specified encoding
    4. If decode fails and force_text: raise ContentDecodeError
    5. If decode fails and not force_text: fall back to base64
    6. If binary: encode as base64

    Args:
        raw_content: Raw bytes from the file.
        mime_type: Detected MIME type.
        text_encoding: Text encoding to use for decoding.
        force_text: Force text interpretation.
        force_base64: Force base64 encoding.

    Returns:
        Tuple of (content_string, encoding_label) where encoding_label
        is either "text" or "base64".

    Raises:
        FSError: With CONTENT_DECODE_ERROR code when force_text is True
            but decoding fails.
    """
    from mamba_mcp_fs.errors import ContentDecodeError

    # force_base64 overrides everything
    if force_base64:
        return base64.b64encode(raw_content).decode("ascii"), "base64"

    # Determine if content is text
    content_is_text = is_text_content(mime_type, raw_content)

    if content_is_text or force_text:
        # Try decoding as text
        try:
            text_content = raw_content.decode(text_encoding)
            return text_content, "text"
        except (UnicodeDecodeError, LookupError):
            if force_text:
                raise ContentDecodeError(
                    f"Failed to decode content as '{text_encoding}'. "
                    "Try a different encoding or use force_base64=true."
                )
            # Not force_text: fall back to base64
            return base64.b64encode(raw_content).decode("ascii"), "base64"

    # Binary content: encode as base64
    return base64.b64encode(raw_content).decode("ascii"), "base64"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_file_info(
    path: str,
    backend: str | None = None,
    include_checksum: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> FileInfoResponse | dict[str, Any]:
    """Get detailed metadata for a single file or directory.

    Returns name, size, type, MIME type, timestamps, symlink status,
    permissions, and optional SHA-256 checksum. Use this to inspect a
    file before reading it (e.g., to check size and type).

    Args:
        path: Path to the file or directory. Supports local paths and s3:// paths.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.
        include_checksum: Calculate and include SHA-256 checksum. Default: false.

    Returns:
        Detailed file metadata with all available fields.

    Example:
        get_file_info(path="/data/report.csv") -> {"name": "report.csv", "size_bytes": 1024, ...}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_file_info called with path=%s, backend=%s, include_checksum=%s",
        path,
        backend,
        include_checksum,
    )

    if ctx is None:
        logger.error("get_file_info: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        # Get the appropriate backend and resolved path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        # Get file/directory metadata from the backend.
        # Pass the original user path (not the pre-resolved path from get_backend)
        # so that the LocalBackend can detect symlinks via _make_pre_resolved_path
        # before resolve() follows them.
        raw_info: dict[str, Any] = backend_instance.info(path)

        # Extract and normalize metadata fields.
        # Use the original user path for the name, not the backend's resolved name,
        # because symlink resolution may change the name (link.txt -> target.txt).
        basename = os.path.basename(path)

        entry_type = raw_info.get("type", "file")
        if entry_type not in ("file", "directory"):
            entry_type = "file"

        # Parse size
        size_bytes = raw_info.get("size")
        if size_bytes is not None:
            size_bytes = int(size_bytes)

        # Parse timestamps
        # S3 backend uses "last_modified" key (from _normalize_entry), while local uses "modified"
        modified_at = _parse_timestamp(
            raw_info.get("modified") or raw_info.get("mtime") or raw_info.get("last_modified")
        )
        created_at = _parse_timestamp(raw_info.get("created_at") or raw_info.get("created"))

        # MIME type: backend may provide it, otherwise detect from path
        mime_type = raw_info.get("mime_type")
        if mime_type is None:
            if entry_type == "directory":
                mime_type = "inode/directory"
            else:
                mime_type = detect_mime_type(resolved_path)

        # Hidden status
        is_hidden = basename.startswith(".") and basename not in (".", "..")

        # Symlink status (from backend info, local only)
        is_symlink = bool(raw_info.get("islink", False))

        # Permissions string (from backend info, local only)
        permissions = raw_info.get("permissions")

        # Compute SHA-256 checksum if requested and target is a file.
        # Use resolved_path for cat_file since it bypasses the backend's
        # own resolution (for mock backends) or is fine with double resolution.
        checksum = None
        if include_checksum and entry_type == "file":
            checksum = _compute_checksum(backend_instance, path)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_file_info completed in %.2fms for %s (%s)",
            elapsed_ms,
            path,
            entry_type,
        )

        return FileInfoResponse(
            path=path,
            backend=backend_name,
            name=basename,
            type=entry_type,
            size_bytes=size_bytes,
            mime_type=mime_type,
            modified_at=modified_at,
            created_at=created_at,
            is_hidden=is_hidden,
            is_symlink=is_symlink,
            permissions=permissions,
            checksum=checksum,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_file_info failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(
            error_code,
            error_message,
            {"path": path, "backend": backend},
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_file_info unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )


def _compute_checksum(backend_instance: Any, path: str) -> str:
    """Compute SHA-256 checksum of a file using chunked hashing.

    Reads the file in chunks to handle large files without excessive memory usage.

    Args:
        backend_instance: The backend to read from.
        path: Resolved path to the file.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    sha256 = hashlib.sha256()
    offset = 0

    while True:
        chunk = backend_instance.cat_file(path, start=offset, end=offset + _CHECKSUM_CHUNK_SIZE)
        if not chunk:
            break
        sha256.update(chunk)
        offset += len(chunk)
        if len(chunk) < _CHECKSUM_CHUNK_SIZE:
            break

    return sha256.hexdigest()


def _filter_hidden(
    entries: list[dict[str, Any]],
    app_ctx: AppContext,
    include_hidden: bool | None,
) -> list[dict[str, Any]]:
    """Filter hidden files from entries based on config and override.

    Uses SecurityValidator.filter_hidden to apply the hidden file policy.
    The include_hidden parameter overrides the server default when provided.

    Args:
        entries: Raw entries from the backend.
        app_ctx: Application context with security validator.
        include_hidden: Per-call override for hidden file visibility.

    Returns:
        Filtered list of entries.
    """
    # Extract basenames for the security filter
    names = [os.path.basename(entry.get("name", "")) for entry in entries]
    visible_names = set(app_ctx.security.filter_hidden(names, include_hidden=include_hidden))
    return [entry for entry in entries if os.path.basename(entry.get("name", "")) in visible_names]


def _filter_by_pattern(entries: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    """Filter entries by glob pattern matching on the basename.

    Args:
        entries: Entries to filter.
        pattern: Glob pattern (e.g., '*.py', 'README*').

    Returns:
        Entries whose basename matches the glob pattern.
    """
    return [
        entry
        for entry in entries
        if fnmatch.fnmatch(os.path.basename(entry.get("name", "")), pattern)
    ]


def _to_file_entry(entry: dict[str, Any]) -> FileEntry:
    """Convert a backend entry dict to a FileEntry model.

    Maps the standardized backend dict format to the FileEntry Pydantic model.
    Handles differences between local and S3 backend dict keys.

    Args:
        entry: Dict from backend.ls() with standardized keys.

    Returns:
        A FileEntry model instance.
    """
    name_raw = entry.get("name", "")
    basename = os.path.basename(name_raw)

    # Parse entry type: fsspec uses "file" and "directory"
    entry_type = entry.get("type", "file")
    if entry_type not in ("file", "directory"):
        entry_type = "file"

    # Parse size: directories may have None or 0
    size_bytes = entry.get("size")
    if size_bytes is not None:
        size_bytes = int(size_bytes)

    # Parse modified timestamp
    # S3 backend uses "last_modified" key (from _normalize_entry), while local uses "modified"
    modified_at = _parse_timestamp(
        entry.get("modified") or entry.get("mtime") or entry.get("last_modified")
    )

    # Determine hidden status
    is_hidden = basename.startswith(".") and basename not in (".", "..")

    return FileEntry(
        name=basename,
        path=name_raw,
        type=entry_type,
        size_bytes=size_bytes,
        modified_at=modified_at,
        is_hidden=is_hidden,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp value from various formats to datetime.

    Handles float (UNIX timestamp), datetime objects, and ISO format strings.

    Args:
        value: Timestamp value from the backend.

    Returns:
        A datetime object, or None if parsing fails.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    return None


# Number of context lines before/after a content match
_MATCH_CONTEXT_LINES = 2


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def search_files(
    path: str,
    backend: str | None = None,
    name_pattern: str | None = None,
    content_pattern: str | None = None,
    max_depth: int = 10,
    max_results: int = 100,
    include_hidden: bool | None = None,
    file_types: list[str] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> SearchResponse | dict[str, Any]:
    """Search for files by name pattern and/or content regex.

    Recursively searches a directory tree and returns matching files. Supports
    glob-based name matching, regex content search, MIME type filtering, and
    depth control.

    Args:
        path: Root directory to search from.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.
        name_pattern: Glob pattern for file names (e.g., '*.py'). Default: None (all files).
        content_pattern: Regex pattern to search file contents. Default: None (name-only search).
        max_depth: Max recursion depth (0 = current dir only). Default: 10.
        max_results: Max results to return (1-10000). Default: 100.
        include_hidden: Include hidden files/dotfiles. Default: per server config.
        file_types: Filter by MIME type prefixes (e.g., ['text/']). Default: None (all types).

    Returns:
        Search results with matching entries, match context, and search metadata.

    Example:
        search_files(path="/src", name_pattern="*.py", content_pattern="def main")
    """
    start_time = time.perf_counter()
    logger.debug(
        "search_files called with path=%s, backend=%s, name_pattern=%s, "
        "content_pattern=%s, max_depth=%d, max_results=%d",
        path,
        backend,
        name_pattern,
        content_pattern,
        max_depth,
        max_results,
    )

    if ctx is None:
        logger.error("search_files: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Clamp max_results to valid range
    max_results = max(1, min(10000, max_results))
    max_depth = max(0, max_depth)

    # Validate regex pattern early so we fail fast on syntax errors
    compiled_regex: re.Pattern[str] | None = None
    if content_pattern is not None:
        try:
            compiled_regex = re.compile(content_pattern)
        except re.error as exc:
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"Invalid regex pattern: {exc}",
                {
                    "pattern": content_pattern,
                    "suggestion": "Check regex syntax. Common issues: unescaped "
                    "special characters, unmatched parentheses.",
                },
            )

    try:
        # Get the appropriate backend and resolved path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        results: list[SearchResult] = []
        directories_searched = 0
        total_matches = 0

        # Walk the directory tree recursively
        dirs_to_visit: list[tuple[str, int]] = [(resolved_path, 0)]

        while dirs_to_visit:
            current_dir, current_depth = dirs_to_visit.pop(0)
            directories_searched += 1

            # List directory entries, skip on error (unreadable directories)
            try:
                raw_entries: list[dict[str, Any]] = backend_instance.ls(current_dir, detail=True)
            except Exception:
                logger.debug("search_files: skipping unreadable directory %s", current_dir)
                continue

            # Apply hidden file filtering
            filtered_entries = _filter_hidden(raw_entries, app_ctx, include_hidden)

            for entry in filtered_entries:
                entry_name_raw = entry.get("name", "")
                entry_basename = os.path.basename(entry_name_raw)
                entry_type = entry.get("type", "file")
                if entry_type not in ("file", "directory"):
                    entry_type = "file"

                # Queue subdirectories for deeper search
                if entry_type == "directory":
                    if current_depth < max_depth:
                        dirs_to_visit.append((entry_name_raw, current_depth + 1))
                    continue

                # Apply name pattern filter
                if name_pattern is not None:
                    if not fnmatch.fnmatch(entry_basename, name_pattern):
                        continue

                # Apply MIME type filter
                if file_types is not None:
                    mime = detect_mime_type(entry_name_raw)
                    if not any(mime.startswith(prefix) for prefix in file_types):
                        continue

                # Content pattern search (only for text files)
                match_context: str | None = None
                if compiled_regex is not None:
                    # Detect MIME to check if it is text
                    mime = detect_mime_type(entry_name_raw)
                    if not is_text_content(mime):
                        continue

                    # Read file content, skip on error
                    try:
                        raw_content = backend_instance.cat_file(entry_name_raw)
                    except Exception:
                        logger.debug("search_files: skipping unreadable file %s", entry_name_raw)
                        continue

                    # Decode as text, skip if not decodable
                    try:
                        text_content = raw_content.decode("utf-8")
                    except UnicodeDecodeError:
                        continue

                    # Search for the pattern -- stop at first match per file
                    match = compiled_regex.search(text_content)
                    if match is None:
                        continue

                    # Extract context around the match
                    match_context = _extract_match_context(text_content, match)

                # We have a match -- collect it
                total_matches += 1

                # Parse entry metadata
                size_bytes = entry.get("size")
                if size_bytes is not None:
                    size_bytes = int(size_bytes)

                # S3 backend uses "last_modified" key, local uses "modified"
                modified_at = _parse_timestamp(
                    entry.get("modified") or entry.get("mtime") or entry.get("last_modified")
                )

                results.append(
                    SearchResult(
                        path=entry_name_raw,
                        name=entry_basename,
                        type=entry_type,
                        size_bytes=size_bytes,
                        modified_at=modified_at,
                        match_context=match_context,
                    )
                )

                # Check if we have enough results
                if total_matches >= max_results:
                    break

            # Break outer loop too if we hit max_results
            if total_matches >= max_results:
                break

        # Sort results by path
        results.sort(key=lambda r: r.path)

        search_truncated = total_matches >= max_results and bool(dirs_to_visit)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "search_files completed in %.2fms, %d matches in %d directories",
            elapsed_ms,
            total_matches,
            directories_searched,
        )

        return SearchResponse(
            path=path,
            backend=backend_name,
            results=results,
            total_matches=total_matches,
            search_truncated=search_truncated,
            directories_searched=directories_searched,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("search_files failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(
            error_code,
            error_message,
            {"path": path, "backend": backend},
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("search_files unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )


def _extract_match_context(text: str, match: re.Match[str]) -> str:
    """Extract surrounding lines around a regex match for context display.

    Includes up to 2 lines before and after the line containing the match.

    Args:
        text: Full file text content.
        match: The regex match object.

    Returns:
        A context string with line numbers and surrounding lines.
    """
    lines = text.splitlines()
    if not lines:
        return ""

    # Find the line number of the match start
    match_start = match.start()
    char_count = 0
    match_line = 0
    for i, line in enumerate(lines):
        char_count += len(line) + 1  # +1 for newline
        if char_count > match_start:
            match_line = i
            break

    # Calculate context range
    start_line = max(0, match_line - _MATCH_CONTEXT_LINES)
    end_line = min(len(lines), match_line + _MATCH_CONTEXT_LINES + 1)

    # Build context string with line numbers
    context_parts = []
    for i in range(start_line, end_line):
        marker = ">" if i == match_line else " "
        context_parts.append(f"{marker} {i + 1}: {lines[i]}")

    return "\n".join(context_parts)
