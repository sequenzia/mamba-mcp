"""Mutation tools for filesystem write operations.

Layer 3 tools require write mode (read_only=False) to be enabled.
They are conditionally registered based on server configuration.

Based on spec Section 5.3 (REQ-008 through REQ-012).
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_fs.errors import (
    ErrorCode,
    FSError,
    create_error_response,
)
from mamba_mcp_fs.models.responses import (
    CopyFileResponse,
    CreateDirectoryResponse,
    DeleteFileResponse,
    MoveFileResponse,
    WriteFileResponse,
)
from mamba_mcp_fs.server import AppContext, mcp

logger = logging.getLogger(__name__)


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


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def write_file(
    path: str,
    content: str,
    encoding: str = "text",
    backend: str | None = None,
    create_parents: bool = True,
    overwrite: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> WriteFileResponse | dict[str, Any]:
    """Create a new file or overwrite an existing file with provided content.

    Writes text or base64-encoded binary content to a file. Supports
    automatic parent directory creation and overwrite protection.

    Args:
        path: Destination file path. Supports local paths and s3:// paths.
        content: File content as text string or base64-encoded string.
        encoding: Content encoding -- 'text' or 'base64'. Default: 'text'.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.
        create_parents: Create parent directories if they don't exist. Default: true.
        overwrite: Allow overwriting existing files. Default: true.

    Returns:
        Write result with path, backend, size, and whether a new file was created.

    Example:
        write_file(path="/data/output.txt", content="Hello, world!")
    """
    start_time = time.perf_counter()
    logger.debug(
        "write_file called with path=%s, encoding=%s, backend=%s, create_parents=%s, overwrite=%s",
        path,
        encoding,
        backend,
        create_parents,
        overwrite,
    )

    if ctx is None:
        logger.error("write_file: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Step 1: Check server is NOT in read-only mode
    if app_ctx.settings.server.read_only:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning("write_file rejected: server is in read-only mode (%.2fms)", elapsed_ms)
        return create_error_response(
            ErrorCode.PERMISSION_DENIED,
            "Server is in read-only mode. Mutation tools are disabled.",
            {"path": path},
        )

    try:
        # Step 2: Get backend and validate path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        # Step 3: Check extension against security policy
        app_ctx.security.check_extension(path)

        # Step 4: Decode content based on encoding parameter
        if encoding == "base64":
            try:
                data = base64.b64decode(content)
            except Exception as exc:
                return create_error_response(
                    ErrorCode.INVALID_OPERATION,
                    f"Invalid base64 content: {exc}",
                    {"path": path, "encoding": encoding},
                )
        else:
            data = content.encode("utf-8")

        # Step 5: Check content size against size limit
        size_limit = _get_size_limit(app_ctx, backend_name)
        if len(data) > size_limit:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "write_file rejected: content size %d exceeds limit %d (%.2fms)",
                len(data),
                size_limit,
                elapsed_ms,
            )
            return create_error_response(
                ErrorCode.FILE_TOO_LARGE,
                f"Content size ({len(data)} bytes) exceeds limit ({size_limit} bytes).",
                {"path": path, "size_bytes": len(data), "limit": size_limit},
            )

        # Step 6: Check overwrite protection
        file_existed = False
        try:
            file_existed = backend_instance.exists(path)
        except Exception:
            # If we can't check existence, treat as new file
            file_existed = False

        if not overwrite and file_existed:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "write_file rejected: file exists and overwrite=false (%.2fms)", elapsed_ms
            )
            return create_error_response(
                ErrorCode.PERMISSION_DENIED,
                f"File already exists and overwrite is disabled: {path}",
                {"path": path, "overwrite": overwrite},
            )

        # Step 7: Create parent directories if requested
        if create_parents:
            parent_dir = os.path.dirname(path)
            if parent_dir:
                try:
                    backend_instance.mkdir(parent_dir, create_parents=True)
                except Exception:
                    # Parent creation failures will surface in the write step
                    logger.debug(
                        "write_file: parent directory creation for %s may have failed; "
                        "proceeding with write attempt",
                        parent_dir,
                    )

        # Step 8: Write content via backend
        backend_instance.pipe_file(path, data)

        # Step 9: Return response
        created = not file_existed

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "write_file completed in %.2fms for %s (%d bytes, created=%s)",
            elapsed_ms,
            path,
            len(data),
            created,
        )

        return WriteFileResponse(
            path=path,
            backend=backend_name,
            size_bytes=len(data),
            created=created,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("write_file failed after %.2fms: %s", elapsed_ms, str(exc))
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
        logger.error("write_file unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def delete_file(
    path: str,
    backend: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> DeleteFileResponse | dict[str, Any]:
    """Delete a file at the specified path.

    Removes a single file from the local filesystem or S3 backend.
    Does not support directory deletion -- use with file paths only.

    Args:
        path: Path of the file to delete. Supports local paths and s3:// paths.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.

    Returns:
        Deletion result with path, backend, and deleted confirmation flag.

    Example:
        delete_file(path="/data/temp/output.txt")
    """
    start_time = time.perf_counter()
    logger.debug("delete_file called with path=%s, backend=%s", path, backend)

    if ctx is None:
        logger.error("delete_file: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Step 1: Check server is NOT in read-only mode
    if app_ctx.settings.server.read_only:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning("delete_file rejected: server is in read-only mode (%.2fms)", elapsed_ms)
        return create_error_response(
            ErrorCode.PERMISSION_DENIED,
            "Server is in read-only mode. Mutation tools are disabled.",
            {"path": path},
        )

    try:
        # Step 2: Get backend and validate path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        # Step 3: Verify path is a file (not directory)
        if backend_instance.isdir(path):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "delete_file rejected: path is a directory (%.2fms): %s", elapsed_ms, path
            )
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"Cannot delete a directory. Only file deletion is supported: {path}",
                {"path": path, "backend": backend_name},
            )

        # Step 4: Verify file exists
        if not backend_instance.exists(path):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("delete_file: file not found after %.2fms: %s", elapsed_ms, path)
            return create_error_response(
                ErrorCode.PATH_NOT_FOUND,
                f"File not found: {path}",
                {"path": path, "backend": backend_name},
            )

        # Step 5: Delete via backend.rm(path)
        backend_instance.rm(path)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("delete_file completed in %.2fms for %s", elapsed_ms, path)

        # Step 6: Return DeleteFileResponse
        return DeleteFileResponse(
            path=path,
            backend=backend_name,
            deleted=True,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("delete_file failed after %.2fms: %s", elapsed_ms, str(exc))
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
        logger.error("delete_file unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def move_file(
    source: str,
    destination: str,
    backend: str | None = None,
    overwrite: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> MoveFileResponse | dict[str, Any]:
    """Move or rename a file from one path to another within the same backend.

    Supports local filesystem moves (native rename) and S3 moves (copy + delete).
    Cross-backend moves are not supported; use copy_file + delete_file instead.

    Args:
        source: Source file path to move from.
        destination: Destination file path to move to.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from source.
        overwrite: Allow overwriting an existing file at the destination. Default: false.

    Returns:
        Move result with source, destination, backend, and overwritten flag.

    Example:
        move_file(source="/data/old.txt", destination="/data/new.txt")
    """
    start_time = time.perf_counter()
    logger.debug(
        "move_file called with source=%s, destination=%s, backend=%s, overwrite=%s",
        source,
        destination,
        backend,
        overwrite,
    )

    if ctx is None:
        logger.error("move_file: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Step 1: Check server is NOT in read-only mode
    if app_ctx.settings.server.read_only:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning("move_file rejected (read-only mode) after %.2fms", elapsed_ms)
        return create_error_response(
            ErrorCode.PERMISSION_DENIED,
            "Server is in read-only mode. Mutation operations are disabled.",
            {"source": source, "destination": destination},
        )

    try:
        # Step 2: Determine backends for both source and destination
        source_backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(source)
        )
        dest_backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(destination)
        )

        # Step 3: Verify both paths are on the SAME backend
        if source_backend_name != dest_backend_name:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "move_file rejected (cross-backend) after %.2fms: %s -> %s",
                elapsed_ms,
                source_backend_name,
                dest_backend_name,
            )
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"Cross-backend moves are not supported. "
                f"Source backend '{source_backend_name}' differs from "
                f"destination backend '{dest_backend_name}'. "
                f"Use copy_file + delete_file instead.",
                {
                    "source": source,
                    "destination": destination,
                    "source_backend": source_backend_name,
                    "dest_backend": dest_backend_name,
                },
            )

        # Step 4: Validate both paths against security (sandbox, extensions)
        #    get_backend performs security validation on the path
        backend_instance, _resolved_source = app_ctx.backend_manager.get_backend(
            source, source_backend_name
        )
        _, _resolved_dest = app_ctx.backend_manager.get_backend(destination, dest_backend_name)

        # Step 5: Verify source exists
        if not backend_instance.exists(source):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("move_file: source not found after %.2fms: %s", elapsed_ms, source)
            return create_error_response(
                ErrorCode.PATH_NOT_FOUND,
                f"Source file not found: {source}",
                {"source": source, "backend": source_backend_name},
            )

        # Step 6: Check destination existence for overwrite protection
        dest_existed = backend_instance.exists(destination)
        if dest_existed and not overwrite:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "move_file rejected (destination exists, overwrite=false) after %.2fms: %s",
                elapsed_ms,
                destination,
            )
            return create_error_response(
                ErrorCode.PERMISSION_DENIED,
                f"Destination already exists: {destination}. Set overwrite=true to replace.",
                {
                    "source": source,
                    "destination": destination,
                    "backend": source_backend_name,
                },
            )

        # Step 7: Move via backend.mv(source, destination)
        #    For local: native filesystem rename/move
        #    For S3: implemented as copy + delete in the backend layer
        backend_instance.mv(source, destination)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "move_file completed in %.2fms: %s -> %s (overwritten=%s)",
            elapsed_ms,
            source,
            destination,
            dest_existed,
        )

        # Step 8: Return MoveFileResponse
        return MoveFileResponse(
            source=source,
            destination=destination,
            backend=source_backend_name,
            overwritten=dest_existed and overwrite,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("move_file failed after %.2fms: %s", elapsed_ms, str(exc))
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
            {"source": source, "destination": destination, "backend": backend},
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("move_file unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"source": source, "destination": destination, "backend": backend},
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def copy_file(
    source: str,
    destination: str,
    source_backend: str | None = None,
    dest_backend: str | None = None,
    overwrite: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> CopyFileResponse | dict[str, Any]:
    """Copy a file from source to destination, with cross-backend support.

    Supports same-backend copies (local-to-local, S3-to-S3) via the backend's
    native cp_file method, and cross-backend copies (local-to-S3, S3-to-local)
    by reading the source content and writing it to the destination.

    Args:
        source: Source file path. Supports local paths and s3:// paths.
        destination: Destination file path. Supports local paths and s3:// paths.
        source_backend: Force source backend ('local' or 's3'). Default: auto-detect.
        dest_backend: Force destination backend ('local' or 's3'). Default: auto-detect.
        overwrite: Allow overwriting an existing file at the destination. Default: false.

    Returns:
        Copy result with source, destination, backends, size, and cross_backend flag.

    Example:
        copy_file(source="/data/report.txt", destination="/backup/report.txt")
    """
    start_time = time.perf_counter()
    logger.debug(
        "copy_file called with source=%s, destination=%s, "
        "source_backend=%s, dest_backend=%s, overwrite=%s",
        source,
        destination,
        source_backend,
        dest_backend,
        overwrite,
    )

    if ctx is None:
        logger.error("copy_file: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Step 1: Check server is NOT in read-only mode
    if app_ctx.settings.server.read_only:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning("copy_file rejected (read-only mode) after %.2fms", elapsed_ms)
        return create_error_response(
            ErrorCode.PERMISSION_DENIED,
            "Server is in read-only mode. Mutation operations are disabled.",
            {"source": source, "destination": destination},
        )

    try:
        # Step 2: Determine backends for source and destination (may be different)
        src_backend_name = (
            source_backend
            if source_backend is not None
            else app_ctx.backend_manager.detect_backend(source)
        )
        dst_backend_name = (
            dest_backend
            if dest_backend is not None
            else app_ctx.backend_manager.detect_backend(destination)
        )
        is_cross_backend = src_backend_name != dst_backend_name

        # Step 3: Validate both paths against respective backend security
        src_backend_instance, _resolved_source = app_ctx.backend_manager.get_backend(
            source, src_backend_name
        )
        dst_backend_instance, _resolved_dest = app_ctx.backend_manager.get_backend(
            destination, dst_backend_name
        )

        # Step 4: Verify source exists
        if not src_backend_instance.exists(source):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error("copy_file: source not found after %.2fms: %s", elapsed_ms, source)
            return create_error_response(
                ErrorCode.PATH_NOT_FOUND,
                f"Source file not found: {source}",
                {"source": source, "source_backend": src_backend_name},
            )

        # Step 5: If not overwrite, check destination does not exist
        dest_existed = dst_backend_instance.exists(destination)
        if dest_existed and not overwrite:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "copy_file rejected (destination exists, overwrite=false) after %.2fms: %s",
                elapsed_ms,
                destination,
            )
            return create_error_response(
                ErrorCode.PERMISSION_DENIED,
                f"Destination already exists: {destination}. Set overwrite=true to replace.",
                {
                    "source": source,
                    "destination": destination,
                    "source_backend": src_backend_name,
                    "dest_backend": dst_backend_name,
                },
            )

        # Step 6: Check file size against destination backend's size limit
        source_info = src_backend_instance.info(source)
        source_size = source_info.get("size", 0) or 0
        dest_size_limit = _get_size_limit(app_ctx, dst_backend_name)
        if source_size > dest_size_limit:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "copy_file rejected: source size %d exceeds destination limit %d (%.2fms)",
                source_size,
                dest_size_limit,
                elapsed_ms,
            )
            return create_error_response(
                ErrorCode.FILE_TOO_LARGE,
                f"Source file size ({source_size} bytes) exceeds destination "
                f"backend size limit ({dest_size_limit} bytes).",
                {
                    "source": source,
                    "destination": destination,
                    "size_bytes": source_size,
                    "limit": dest_size_limit,
                    "dest_backend": dst_backend_name,
                },
            )

        # Step 7/8: Perform the copy
        if is_cross_backend:
            # Cross-backend: read from source, write to destination
            content = src_backend_instance.cat_file(source)
            dst_backend_instance.pipe_file(destination, content)
            copied_size = len(content)
        else:
            # Same backend: use native cp_file
            src_backend_instance.cp_file(source, destination)
            copied_size = source_size

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "copy_file completed in %.2fms: %s -> %s (cross_backend=%s, %d bytes)",
            elapsed_ms,
            source,
            destination,
            is_cross_backend,
            copied_size,
        )

        # Step 9: Return CopyFileResponse
        return CopyFileResponse(
            source=source,
            destination=destination,
            source_backend=src_backend_name,
            dest_backend=dst_backend_name,
            size_bytes=copied_size,
            cross_backend=is_cross_backend,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("copy_file failed after %.2fms: %s", elapsed_ms, str(exc))
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
            {
                "source": source,
                "destination": destination,
                "source_backend": source_backend,
                "dest_backend": dest_backend,
            },
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("copy_file unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {
                "source": source,
                "destination": destination,
                "source_backend": source_backend,
                "dest_backend": dest_backend,
            },
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def create_directory(
    path: str,
    backend: str | None = None,
    parents: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> CreateDirectoryResponse | dict[str, Any]:
    """Create a directory at the specified path.

    Creates a new directory on the local filesystem or an S3 prefix placeholder.
    Idempotent: does not error if the directory already exists, returning
    created=false in that case.

    Args:
        path: Directory path to create. Supports local paths and s3:// paths.
        backend: Force a specific backend ('local' or 's3'). Default: auto-detect from path.
        parents: Create parent directories if they don't exist. Default: true.

    Returns:
        Directory creation result with path, backend, and whether it was newly created.

    Example:
        create_directory(path="/data/reports/2024")
    """
    start_time = time.perf_counter()
    logger.debug(
        "create_directory called with path=%s, backend=%s, parents=%s",
        path,
        backend,
        parents,
    )

    if ctx is None:
        logger.error("create_directory: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Step 1: Check server is NOT in read-only mode
    if app_ctx.settings.server.read_only:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            "create_directory rejected: server is in read-only mode (%.2fms)", elapsed_ms
        )
        return create_error_response(
            ErrorCode.PERMISSION_DENIED,
            "Server is in read-only mode. Mutation tools are disabled.",
            {"path": path},
        )

    try:
        # Step 2: Get backend and validate path
        backend_instance, resolved_path = app_ctx.backend_manager.get_backend(path, backend)
        backend_name = (
            backend if backend is not None else app_ctx.backend_manager.detect_backend(path)
        )

        # Step 3: Check if directory already exists (idempotent)
        already_exists = False
        try:
            already_exists = backend_instance.isdir(path)
        except Exception:
            # If we can't check, proceed with creation attempt
            already_exists = False

        if already_exists:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                "create_directory: directory already exists at %s (%.2fms)", path, elapsed_ms
            )
            return CreateDirectoryResponse(
                path=path,
                backend=backend_name,
                created=False,
            )

        # Step 4: Create directory
        if backend_name == "s3":
            # S3: create empty object with trailing `/` as prefix placeholder
            placeholder_key = path.rstrip("/") + "/"
            backend_instance.pipe_file(placeholder_key, b"")
        else:
            # Local: use backend.mkdir with create_parents parameter
            backend_instance.mkdir(path, create_parents=parents)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "create_directory completed in %.2fms for %s (backend=%s)",
            elapsed_ms,
            path,
            backend_name,
        )

        return CreateDirectoryResponse(
            path=path,
            backend=backend_name,
            created=True,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("create_directory failed after %.2fms: %s", elapsed_ms, str(exc))
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
        logger.error("create_directory unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
            {"path": path, "backend": backend},
        )
