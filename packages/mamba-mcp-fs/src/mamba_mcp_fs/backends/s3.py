"""Amazon S3 backend implementation via s3fs.

Wraps an s3fs.S3FileSystem instance with security integration and
maps S3 operations to the BackendProtocol interface. Handles S3's
flat namespace (prefix-based "directories"), path parsing, and
error mapping from botocore ClientError to structured BackendError.

Based on spec Section 7.1 and 9.3.
"""

from __future__ import annotations

import logging
from typing import Any

import s3fs
from botocore.exceptions import ClientError, NoCredentialsError

from mamba_mcp_fs.config import S3Settings
from mamba_mcp_fs.errors import BackendError, FSError, PathNotFoundError

logger = logging.getLogger(__name__)

# S3 path prefix
S3_SCHEME = "s3://"

# Placeholder suffix for S3 "directory" objects
_DIR_PLACEHOLDER_SUFFIX = "/"


def _parse_s3_path(path: str) -> tuple[str, str]:
    """Parse an S3 path into bucket and key components.

    Handles both ``s3://bucket/key`` and ``bucket/key`` formats.
    Returns an empty key string for bucket-only paths.

    Args:
        path: S3 path string.

    Returns:
        Tuple of (bucket, key). Key may be empty for bucket root.
    """
    # Strip the s3:// prefix if present
    raw = path[len(S3_SCHEME) :] if path.startswith(S3_SCHEME) else path

    # Strip leading/trailing slashes from the raw path
    raw = raw.strip("/")

    if not raw:
        return "", ""

    if "/" in raw:
        bucket, key = raw.split("/", 1)
        return bucket, key
    return raw, ""


def _to_s3_path(bucket: str, key: str) -> str:
    """Construct an S3 path from bucket and key.

    Args:
        bucket: S3 bucket name.
        key: S3 object key (may be empty for bucket root).

    Returns:
        Path in ``bucket/key`` format suitable for s3fs.
    """
    if key:
        return f"{bucket}/{key}"
    return bucket


def _map_s3_error(exc: ClientError, path: str) -> FSError:
    """Map an S3 ClientError to the appropriate FSError subclass.

    Args:
        exc: The botocore ClientError from an S3 operation.
        path: The S3 path that caused the error (for context in messages).

    Returns:
        A BackendError or PathNotFoundError with a descriptive message.
    """
    error_code = exc.response.get("Error", {}).get("Code", "Unknown")
    error_message = exc.response.get("Error", {}).get("Message", str(exc))

    if error_code in ("404", "NoSuchKey", "NoSuchBucket"):
        return PathNotFoundError(f"S3 path not found: '{path}' ({error_code}: {error_message})")

    if error_code in ("403", "AccessDenied"):
        return BackendError(
            f"S3 access denied for '{path}': {error_message}. "
            "Check IAM permissions and bucket policy."
        )

    return BackendError(f"S3 error for '{path}': {error_code} - {error_message}")


class S3Backend:
    """S3 filesystem backend wrapping s3fs.S3FileSystem.

    Provides the BackendProtocol interface over S3 using s3fs. Paths
    are expected to be in ``bucket/key`` format (the ``s3://`` prefix
    is stripped by BackendManager before reaching this backend).

    Args:
        settings: S3 backend configuration with region, endpoint, bucket, and prefix.
    """

    def __init__(self, settings: S3Settings) -> None:
        self._settings = settings

        # Build client_kwargs for s3fs
        client_kwargs: dict[str, Any] = {}
        if settings.region:
            client_kwargs["region_name"] = settings.region
        if settings.endpoint_url:
            client_kwargs["endpoint_url"] = settings.endpoint_url

        self._fs = s3fs.S3FileSystem(
            anon=False,
            client_kwargs=client_kwargs if client_kwargs else None,
        )

    @property
    def fs(self) -> s3fs.S3FileSystem:
        """Access the underlying s3fs filesystem instance."""
        return self._fs

    @property
    def settings(self) -> S3Settings:
        """Access the S3 settings."""
        return self._settings

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        """List objects and prefixes at the given S3 path.

        Maps S3's flat namespace into a directory-like listing. Common
        prefixes (virtual directories) are included alongside objects.

        Args:
            path: S3 path in ``bucket/key`` format.
            detail: If True, return dicts with metadata; if False, return name-only dicts.

        Returns:
            List of entry dicts with keys like name, type, size.

        Raises:
            BackendError: If the S3 operation fails.
            PathNotFoundError: If the bucket or prefix does not exist.
        """
        try:
            s3_path = path.strip("/") if path else ""
            if not s3_path:
                # Bucket root or empty path -- list top-level
                entries = self._fs.ls("", detail=detail)
            else:
                entries = self._fs.ls(s3_path, detail=detail)

            if detail:
                return [self._normalize_entry(e) for e in entries]

            # When detail=False, s3fs returns a list of path strings
            return [{"name": name} for name in entries]

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError(
                "S3 credentials not found. Configure AWS credentials via environment "
                "variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY), IAM role, "
                "or AWS CLI profile."
            ) from exc
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"S3 path not found: '{path}'") from exc
        except OSError as exc:
            raise BackendError(f"S3 operation failed for '{path}': {exc}") from exc

    def info(self, path: str) -> dict[str, Any]:
        """Get metadata for an S3 object or prefix.

        Args:
            path: S3 path in ``bucket/key`` format.

        Returns:
            Dict with metadata (name, type, size, mime_type, etc.).

        Raises:
            BackendError: If the S3 operation fails.
            PathNotFoundError: If the object does not exist.
        """
        try:
            s3_path = path.strip("/") if path else ""
            raw_info = self._fs.info(s3_path)
            return self._normalize_entry(raw_info)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError(
                "S3 credentials not found. Configure AWS credentials via environment "
                "variables, IAM role, or AWS CLI profile."
            ) from exc
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"S3 path not found: '{path}'") from exc
        except OSError as exc:
            raise BackendError(f"S3 operation failed for '{path}': {exc}") from exc

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        """Read S3 object content as bytes, with optional byte range.

        S3 supports Range requests natively, so byte-range reads are
        efficient and do not require downloading the full object.

        Args:
            path: S3 path in ``bucket/key`` format.
            start: Optional byte offset to start reading from.
            end: Optional byte offset to stop reading at.

        Returns:
            Object content as bytes.

        Raises:
            BackendError: If the S3 operation fails.
            PathNotFoundError: If the object does not exist.
        """
        try:
            s3_path = path.strip("/") if path else ""
            return self._fs.cat_file(s3_path, start=start, end=end)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError(
                "S3 credentials not found. Configure AWS credentials via environment "
                "variables, IAM role, or AWS CLI profile."
            ) from exc
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"S3 path not found: '{path}'") from exc
        except OSError as exc:
            raise BackendError(f"S3 operation failed for '{path}': {exc}") from exc

    def pipe_file(self, path: str, data: bytes) -> None:
        """Upload data to an S3 object.

        Args:
            path: S3 path in ``bucket/key`` format.
            data: Bytes to upload.

        Raises:
            BackendError: If the S3 operation fails.
        """
        try:
            s3_path = path.strip("/") if path else ""
            self._fs.pipe_file(s3_path, data)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except OSError as exc:
            raise BackendError(f"S3 upload failed for '{path}': {exc}") from exc

    def rm(self, path: str) -> None:
        """Delete an S3 object.

        Args:
            path: S3 path in ``bucket/key`` format.

        Raises:
            BackendError: If the S3 operation fails.
            PathNotFoundError: If the object does not exist.
        """
        try:
            s3_path = path.strip("/") if path else ""
            self._fs.rm(s3_path)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"S3 path not found: '{path}'") from exc
        except OSError as exc:
            raise BackendError(f"S3 delete failed for '{path}': {exc}") from exc

    def cp_file(self, source: str, destination: str) -> None:
        """Copy an S3 object to another S3 location.

        Uses S3's server-side copy when both source and destination
        are in the same region.

        Args:
            source: Source S3 path in ``bucket/key`` format.
            destination: Destination S3 path in ``bucket/key`` format.

        Raises:
            BackendError: If the S3 operation fails.
            PathNotFoundError: If the source object does not exist.
        """
        try:
            src = source.strip("/") if source else ""
            dst = destination.strip("/") if destination else ""
            self._fs.cp_file(src, dst)

        except ClientError as exc:
            raise _map_s3_error(exc, source) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"S3 path not found: '{source}'") from exc
        except OSError as exc:
            raise BackendError(f"S3 copy failed from '{source}' to '{destination}': {exc}") from exc

    def mv(self, source: str, destination: str) -> None:
        """Move an S3 object by copying then deleting the source.

        S3 does not have a native move/rename operation, so this is
        implemented as a copy followed by a delete of the source.

        Args:
            source: Source S3 path in ``bucket/key`` format.
            destination: Destination S3 path in ``bucket/key`` format.

        Raises:
            BackendError: If the S3 operation fails.
            PathNotFoundError: If the source object does not exist.
        """
        self.cp_file(source, destination)
        self.rm(source)

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        """Create an S3 prefix placeholder object.

        S3 does not have real directories. This method creates an empty
        object with a trailing ``/`` suffix to represent a directory
        placeholder, which is the standard convention used by AWS Console
        and other S3 tools.

        Args:
            path: S3 path in ``bucket/key`` format.
            create_parents: Ignored for S3 (parent prefixes are implicit).

        Raises:
            BackendError: If the S3 operation fails.
        """
        try:
            s3_path = path.strip("/") if path else ""
            if not s3_path:
                # Cannot create a "directory" at empty path
                return

            # Create an empty object with trailing / to act as directory placeholder
            placeholder_path = s3_path + _DIR_PLACEHOLDER_SUFFIX
            self._fs.pipe_file(placeholder_path, b"")

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except OSError as exc:
            raise BackendError(f"S3 mkdir failed for '{path}': {exc}") from exc

    def exists(self, path: str) -> bool:
        """Check if an S3 object or prefix exists.

        Args:
            path: S3 path in ``bucket/key`` format.

        Returns:
            True if the path exists as an object or prefix.

        Raises:
            BackendError: If the S3 operation fails unexpectedly.
        """
        try:
            s3_path = path.strip("/") if path else ""
            return self._fs.exists(s3_path)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except OSError as exc:
            raise BackendError(f"S3 exists check failed for '{path}': {exc}") from exc

    def isdir(self, path: str) -> bool:
        """Check if an S3 path is a virtual directory (prefix).

        S3 "directories" are virtual -- they exist when there are objects
        with the given prefix, or when a placeholder object with trailing
        ``/`` exists.

        Args:
            path: S3 path in ``bucket/key`` format.

        Returns:
            True if the path is a directory (prefix).

        Raises:
            BackendError: If the S3 operation fails unexpectedly.
        """
        try:
            s3_path = path.strip("/") if path else ""
            if not s3_path:
                return True
            return self._fs.isdir(s3_path)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except OSError as exc:
            raise BackendError(f"S3 isdir check failed for '{path}': {exc}") from exc

    def isfile(self, path: str) -> bool:
        """Check if an S3 path is an object (file).

        Args:
            path: S3 path in ``bucket/key`` format.

        Returns:
            True if the path is an object (not a prefix/directory).

        Raises:
            BackendError: If the S3 operation fails unexpectedly.
        """
        try:
            s3_path = path.strip("/") if path else ""
            if not s3_path:
                return False
            return self._fs.isfile(s3_path)

        except ClientError as exc:
            raise _map_s3_error(exc, path) from exc
        except NoCredentialsError as exc:
            raise BackendError("S3 credentials not found. Configure AWS credentials.") from exc
        except OSError as exc:
            raise BackendError(f"S3 isfile check failed for '{path}': {exc}") from exc

    def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Normalize an s3fs entry dict to the standard BackendProtocol format.

        Maps S3 metadata fields to a consistent format used by the tool layer.
        S3 "directories" (common prefixes) have type="directory" and size=0.

        Args:
            entry: Raw entry dict from s3fs (ls with detail=True or info).

        Returns:
            Normalized dict with standard keys (name, type, size, etc.).
        """
        entry_type = entry.get("type", "file")
        name = entry.get("name", entry.get("Key", ""))
        size = entry.get("size", entry.get("Size", 0)) or 0

        normalized: dict[str, Any] = {
            "name": name,
            "type": entry_type,
            "size": size,
        }

        # Map S3-specific metadata to standard format
        if "ContentType" in entry:
            normalized["mime_type"] = entry["ContentType"]

        if "LastModified" in entry:
            normalized["last_modified"] = entry["LastModified"]

        if "ETag" in entry:
            normalized["etag"] = entry["ETag"]

        if "StorageClass" in entry:
            normalized["storage_class"] = entry["StorageClass"]

        if "VersionId" in entry:
            normalized["version_id"] = entry["VersionId"]

        return normalized
