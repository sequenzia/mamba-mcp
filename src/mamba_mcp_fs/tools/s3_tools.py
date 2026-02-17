"""S3-specific MCP tools.

Layer 2 tools provide S3-specific operations beyond the standard
filesystem discovery tools. They are registered only when the S3
backend is enabled.

Based on spec Section 5.2 (REQ-005 through REQ-007).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_fs.errors import (
    ErrorCode,
    FSError,
    create_error_response,
)
from mamba_mcp_fs.models.files import BucketInfo
from mamba_mcp_fs.models.responses import (
    ListBucketsResponse,
    ObjectMetadataResponse,
    PresignedUrlResponse,
)
from mamba_mcp_fs.server import AppContext, mcp

# Presigned URL expiration bounds (in seconds)
MIN_EXPIRES_IN = 60  # 1 minute
MAX_EXPIRES_IN = 604800  # 7 days

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_buckets(
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListBucketsResponse | dict[str, Any]:
    """List all accessible S3 buckets.

    Returns bucket names, creation dates, and regions for all S3 buckets
    accessible with the configured credentials. No parameters required --
    uses the server's S3 configuration.

    Returns:
        List of buckets with metadata and total count.

    Example:
        list_buckets() -> {"buckets": [{"name": "my-bucket", ...}], "total_count": 1}
    """
    start_time = time.perf_counter()
    logger.debug("list_buckets called")

    if ctx is None:
        logger.error("list_buckets: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Check that S3 backend is enabled
    if not app_ctx.settings.s3.enabled:
        return create_error_response(
            ErrorCode.BACKEND_NOT_CONFIGURED,
            "S3 backend is not enabled. Enable it in server configuration.",
        )

    try:
        # Get the S3 backend instance from the backend manager
        s3_backend = app_ctx.backend_manager._backends.get("s3")
        if s3_backend is None:
            return create_error_response(
                ErrorCode.BACKEND_NOT_CONFIGURED,
                "S3 backend is enabled but no instance is configured.",
            )

        # Access the underlying botocore client to list buckets.
        # s3fs wraps botocore and exposes it via .s3 attribute on the
        # S3FileSystem instance. The S3Backend exposes this via .fs property.
        raw_response = s3_backend.fs.s3.list_buckets()  # type: ignore[attr-defined]

        raw_buckets = raw_response.get("Buckets", [])
        region = app_ctx.settings.s3.region

        buckets: list[BucketInfo] = []
        for raw_bucket in raw_buckets:
            name = raw_bucket.get("Name", "")
            creation_date = raw_bucket.get("CreationDate")

            # CreationDate from botocore is already a datetime object
            if creation_date is not None and not isinstance(creation_date, datetime):
                creation_date = None

            buckets.append(
                BucketInfo(
                    name=name,
                    creation_date=creation_date,
                    region=region,
                )
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_buckets completed in %.2fms, returned %d buckets",
            elapsed_ms,
            len(buckets),
        )

        return ListBucketsResponse(
            buckets=buckets,
            total_count=len(buckets),
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_buckets failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(error_code, error_message)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_buckets unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_presigned_url(
    path: str,
    operation: Literal["download", "upload"] = "download",
    expires_in: int = 3600,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> PresignedUrlResponse | dict[str, Any]:
    """Generate a presigned URL for downloading or uploading an S3 object.

    Creates a time-limited URL that allows direct access to an S3 object
    without requiring AWS credentials. For download operations, the object
    must exist. For upload operations, the server must not be in read-only mode.

    Args:
        path: S3 object path (e.g., s3://bucket/key).
        operation: "download" or "upload". Default: "download".
        expires_in: URL expiration in seconds. Default: 3600 (1 hour).
            Minimum: 60 seconds. Maximum: 604800 (7 days).
        ctx: MCP context with lifespan AppContext.

    Returns:
        PresignedUrlResponse with url, path, operation, and expires_at.

    Example:
        get_presigned_url("s3://bucket/file.txt")
        -> {"url": "https://...", "path": "s3://bucket/file.txt", ...}
    """
    start_time = time.perf_counter()
    logger.debug("get_presigned_url called: path=%s, operation=%s", path, operation)

    if ctx is None:
        logger.error("get_presigned_url: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Check that S3 backend is enabled
    if not app_ctx.settings.s3.enabled:
        return create_error_response(
            ErrorCode.BACKEND_NOT_CONFIGURED,
            "S3 backend is not enabled. Enable it in server configuration.",
        )

    # For upload operations, check read-only mode
    if operation == "upload" and app_ctx.settings.server.read_only:
        return create_error_response(
            ErrorCode.PERMISSION_DENIED,
            "Cannot generate upload URL: server is in read-only mode.",
        )

    # Clamp expires_in to valid range
    expires_in = max(MIN_EXPIRES_IN, min(expires_in, MAX_EXPIRES_IN))

    try:
        # Get the S3 backend instance from the backend manager
        s3_backend = app_ctx.backend_manager._backends.get("s3")
        if s3_backend is None:
            return create_error_response(
                ErrorCode.BACKEND_NOT_CONFIGURED,
                "S3 backend is enabled but no instance is configured.",
            )

        # Parse the S3 path to extract bucket and key
        s3_prefix = "s3://"
        if path.startswith(s3_prefix):
            raw_path = path[len(s3_prefix) :]
        else:
            raw_path = path

        parts = raw_path.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        if not bucket:
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"S3 path '{path}' has an empty bucket name. "
                "Provide a valid bucket name: s3://bucket-name/key",
            )

        if not key:
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"S3 path '{path}' has no object key. "
                "Provide a valid object key: s3://bucket-name/key",
            )

        # For download, validate the object exists
        if operation == "download":
            if not s3_backend.exists(path):
                return create_error_response(
                    ErrorCode.PATH_NOT_FOUND,
                    f"Object does not exist: {path}",
                )

        # Generate the presigned URL via the botocore client
        # s3fs exposes the botocore client via .s3 attribute
        botocore_client = s3_backend.fs.s3  # type: ignore[attr-defined]

        if operation == "download":
            client_method = "get_object"
        else:
            client_method = "put_object"

        url = botocore_client.generate_presigned_url(
            ClientMethod=client_method,
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

        # Calculate expires_at timestamp
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_presigned_url completed in %.2fms: operation=%s, expires_in=%d",
            elapsed_ms,
            operation,
            expires_in,
        )

        return PresignedUrlResponse(
            url=url,
            path=path,
            operation=operation,
            expires_at=expires_at,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_presigned_url failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(error_code, error_message)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_presigned_url unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
        )


def _parse_s3_path(path: str) -> tuple[str, str]:
    """Parse an S3 path into (bucket, key).

    Strips the ``s3://`` prefix if present and splits on the first ``/``.

    Args:
        path: Raw S3 path (e.g. ``s3://bucket/key``).

    Returns:
        Tuple of (bucket, key). Either may be empty if the path is malformed.
    """
    s3_prefix = "s3://"
    if path.startswith(s3_prefix):
        raw_path = path[len(s3_prefix) :]
    else:
        raw_path = path

    parts = raw_path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_object_metadata(
    path: str,
    include_tags: bool = True,
    include_versions: bool = False,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ObjectMetadataResponse | dict[str, Any]:
    """Retrieve S3-specific metadata for an object.

    Returns storage class, ETag, encryption, content type, last modified,
    and optionally object tags and version history. Goes beyond what
    get_file_info provides by exposing S3-native metadata.

    Args:
        path: S3 object path (e.g., s3://bucket/key).
        include_tags: Include object tags in the response. Default: true.
        include_versions: Include version history if versioning is enabled.
            Default: false.
        ctx: MCP context with lifespan AppContext.

    Returns:
        ObjectMetadataResponse with S3-specific metadata, or error dict.

    Example:
        get_object_metadata("s3://bucket/file.txt")
        -> {"path": "s3://bucket/file.txt", "storage_class": "STANDARD", ...}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_object_metadata called: path=%s, include_tags=%s, include_versions=%s",
        path,
        include_tags,
        include_versions,
    )

    if ctx is None:
        logger.error("get_object_metadata: No context available")
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            "No context available",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Check that S3 backend is enabled
    if not app_ctx.settings.s3.enabled:
        return create_error_response(
            ErrorCode.BACKEND_NOT_CONFIGURED,
            "S3 backend is not enabled. Enable it in server configuration.",
        )

    try:
        # Get the S3 backend instance from the backend manager
        s3_backend = app_ctx.backend_manager._backends.get("s3")
        if s3_backend is None:
            return create_error_response(
                ErrorCode.BACKEND_NOT_CONFIGURED,
                "S3 backend is enabled but no instance is configured.",
            )

        # Parse the S3 path to extract bucket and key
        bucket, key = _parse_s3_path(path)

        if not bucket:
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"S3 path '{path}' has an empty bucket name. "
                "Provide a valid bucket name: s3://bucket-name/key",
            )

        if not key:
            return create_error_response(
                ErrorCode.INVALID_OPERATION,
                f"S3 path '{path}' has no object key. "
                "Provide a valid object key: s3://bucket-name/key",
            )

        # Access the botocore client via s3fs
        botocore_client = s3_backend.fs.s3  # type: ignore[attr-defined]

        # 1. HeadObject for core metadata
        try:
            head = botocore_client.head_object(Bucket=bucket, Key=key)
        except Exception as head_exc:
            # Map common S3 errors to our error codes
            exc_str = str(head_exc).lower()
            if "not found" in exc_str or "404" in exc_str or "nosuchkey" in exc_str:
                return create_error_response(
                    ErrorCode.PATH_NOT_FOUND,
                    f"Object does not exist: {path}",
                )
            raise

        storage_class = head.get("StorageClass", "STANDARD")
        etag = head.get("ETag", "")
        version_id = head.get("VersionId")
        server_side_encryption = head.get("ServerSideEncryption")
        content_type = head.get("ContentType", "application/octet-stream")
        last_modified = head.get("LastModified")

        # Ensure last_modified is a datetime
        if last_modified is not None and not isinstance(last_modified, datetime):
            last_modified = datetime.now(UTC)
        elif last_modified is None:
            last_modified = datetime.now(UTC)

        # 2. GetObjectTagging (if requested)
        tags: dict[str, str] | None = None
        if include_tags:
            try:
                tag_response = botocore_client.get_object_tagging(Bucket=bucket, Key=key)
                tag_set = tag_response.get("TagSet", [])
                tags = {tag["Key"]: tag["Value"] for tag in tag_set}
            except Exception:
                # If tagging fails (e.g., permissions), return empty tags
                logger.warning("get_object_metadata: failed to retrieve tags for %s", path)
                tags = {}

        # 3. ListObjectVersions (if requested)
        versions: list[dict[str, Any]] | None = None
        if include_versions:
            try:
                versions_response = botocore_client.list_object_versions(Bucket=bucket, Prefix=key)
                raw_versions = versions_response.get("Versions", [])
                versions = []
                for ver in raw_versions:
                    # Only include versions matching the exact key
                    if ver.get("Key") != key:
                        continue
                    version_entry: dict[str, Any] = {
                        "version_id": ver.get("VersionId"),
                        "is_latest": ver.get("IsLatest", False),
                        "last_modified": ver.get("LastModified"),
                        "size": ver.get("Size"),
                        "storage_class": ver.get("StorageClass"),
                        "etag": ver.get("ETag"),
                    }
                    versions.append(version_entry)
            except Exception:
                # If version listing fails, return empty list
                logger.warning("get_object_metadata: failed to list versions for %s", path)
                versions = []

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_object_metadata completed in %.2fms: path=%s",
            elapsed_ms,
            path,
        )

        return ObjectMetadataResponse(
            path=path,
            storage_class=storage_class,
            etag=etag,
            version_id=version_id,
            tags=tags,
            versions=versions,
            server_side_encryption=server_side_encryption,
            content_type=content_type,
            last_modified=last_modified,
        )

    except FSError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_object_metadata failed after %.2fms: %s", elapsed_ms, str(exc))
        # Unwrap BackendError to surface the original FSError code
        error_code = exc.code
        error_message = exc.message
        cause = exc.__cause__
        if isinstance(cause, FSError):
            error_code = cause.code
            error_message = cause.message
        return create_error_response(error_code, error_message)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_object_metadata unexpected error after %.2fms: %s", elapsed_ms, str(exc))
        return create_error_response(
            ErrorCode.BACKEND_ERROR,
            str(exc),
        )
