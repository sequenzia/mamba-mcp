"""Base backend abstraction for filesystem operations.

Defines the BackendProtocol that all filesystem backends must implement,
and the BackendManager that routes operations to the appropriate backend
based on path prefix and configuration.

Based on spec Section 7.1. The backend manager wraps fsspec filesystems
with security validation and configuration.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from mamba_mcp_fs.config import Settings
from mamba_mcp_fs.errors import (
    BackendError,
    BackendNotConfiguredError,
    InvalidOperationError,
    find_similar_names,
)
from mamba_mcp_fs.security import SecurityValidator

# S3 path prefix for auto-detection
S3_PREFIX = "s3://"

# Valid backend names
BACKEND_LOCAL = "local"
BACKEND_S3 = "s3"
VALID_BACKENDS = {BACKEND_LOCAL, BACKEND_S3}


@runtime_checkable
class BackendProtocol(Protocol):
    """Protocol defining the interface that all filesystem backends must implement.

    Each method mirrors a subset of the fsspec AbstractFileSystem interface,
    providing a unified API for local and remote filesystem operations.
    """

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        """List directory entries.

        Args:
            path: Directory path to list.
            detail: If True, return dicts with metadata; if False, return names only.

        Returns:
            List of entry dicts (with keys like name, type, size) when detail=True,
            or list of path strings wrapped in dicts when detail=False.
        """
        ...

    def info(self, path: str) -> dict[str, Any]:
        """Get file or directory metadata.

        Args:
            path: Path to the file or directory.

        Returns:
            Dict with metadata keys (name, type, size, etc.).
        """
        ...

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        """Read file content as bytes.

        Args:
            path: Path to the file.
            start: Optional byte offset to start reading from.
            end: Optional byte offset to stop reading at.

        Returns:
            File content as bytes.
        """
        ...

    def pipe_file(self, path: str, data: bytes) -> None:
        """Write data to a file.

        Args:
            path: Path to the file.
            data: Bytes to write.
        """
        ...

    def rm(self, path: str) -> None:
        """Delete a file.

        Args:
            path: Path to the file to delete.
        """
        ...

    def cp_file(self, source: str, destination: str) -> None:
        """Copy a file from source to destination.

        Args:
            source: Source file path.
            destination: Destination file path.
        """
        ...

    def mv(self, source: str, destination: str) -> None:
        """Move a file from source to destination.

        Args:
            source: Source file path.
            destination: Destination file path.
        """
        ...

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        """Create a directory.

        Args:
            path: Directory path to create.
            create_parents: If True, create parent directories as needed.
        """
        ...

    def exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check.

        Returns:
            True if the path exists.
        """
        ...

    def isdir(self, path: str) -> bool:
        """Check if a path is a directory.

        Args:
            path: Path to check.

        Returns:
            True if the path is a directory.
        """
        ...

    def isfile(self, path: str) -> bool:
        """Check if a path is a file.

        Args:
            path: Path to check.

        Returns:
            True if the path is a file.
        """
        ...


class BackendManager:
    """Routes filesystem operations to the appropriate backend.

    Holds references to configured backends (local, s3), auto-detects
    which backend to use based on path prefix, validates that the
    requested backend is enabled, and ensures security validation
    runs before every operation.

    Args:
        settings: The root Settings instance with local and s3 configuration.
        security: The SecurityValidator for path validation before operations.
        local_backend: Optional local filesystem backend instance.
        s3_backend: Optional S3 backend instance.
    """

    def __init__(
        self,
        settings: Settings,
        security: SecurityValidator,
        local_backend: BackendProtocol | None = None,
        s3_backend: BackendProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._security = security
        self._backends: dict[str, BackendProtocol] = {}

        if local_backend is not None:
            self._backends[BACKEND_LOCAL] = local_backend
        if s3_backend is not None:
            self._backends[BACKEND_S3] = s3_backend

    @property
    def security(self) -> SecurityValidator:
        """Access the security validator for pre-operation checks."""
        return self._security

    @property
    def settings(self) -> Settings:
        """Access the root settings."""
        return self._settings

    def detect_backend(self, path: str) -> str:
        """Detect which backend to use based on path prefix.

        Args:
            path: The file path to analyze.

        Returns:
            Backend name: "s3" for s3:// paths, "local" for everything else.
        """
        if path.startswith(S3_PREFIX):
            return BACKEND_S3
        return BACKEND_LOCAL

    def is_backend_enabled(self, backend: str) -> bool:
        """Check whether a backend is enabled in the configuration.

        Args:
            backend: Backend name ("local" or "s3").

        Returns:
            True if the backend is enabled in settings.
        """
        if backend == BACKEND_LOCAL:
            return self._settings.local.enabled
        if backend == BACKEND_S3:
            return self._settings.s3.enabled
        return False

    def get_backend(self, path: str, backend: str | None = None) -> tuple[BackendProtocol, str]:
        """Get the appropriate backend and resolved path for an operation.

        Determines the backend either from an explicit parameter or via
        auto-detection from the path prefix. Validates that the backend
        is enabled and configured before returning it.

        Security validation is performed on the path before returning,
        ensuring all callers benefit from centralized path checking.

        Args:
            path: The file path to operate on.
            backend: Optional explicit backend name. Overrides auto-detection.

        Returns:
            Tuple of (backend_instance, resolved_path) where resolved_path
            has any protocol prefix stripped for the backend's use.

        Raises:
            BackendNotConfiguredError: If the target backend is not enabled
                or not configured.
            BackendError: If an unexpected error occurs during path resolution.
        """
        # Determine which backend to use
        backend_name = backend if backend is not None else self.detect_backend(path)

        # Validate the backend name
        if backend_name not in VALID_BACKENDS:
            similar = find_similar_names(backend_name, sorted(VALID_BACKENDS))
            hint = f" Did you mean '{similar[0]}'?" if similar else ""
            raise BackendNotConfiguredError(
                f"Unknown backend '{backend_name}'. Valid backends: {sorted(VALID_BACKENDS)}.{hint}"
            )

        # Check for conflicting backend/path combinations
        if backend is not None:
            self._validate_backend_path_compatibility(backend_name, path)

        # Check that the backend is enabled in config
        if not self.is_backend_enabled(backend_name):
            enabled = [b for b in sorted(VALID_BACKENDS) if self.is_backend_enabled(b)]
            hint = f" Enabled backends: {enabled}." if enabled else ""
            raise BackendNotConfiguredError(
                f"Backend '{backend_name}' is not enabled. Enable it in server configuration.{hint}"
            )

        # Check that the backend instance is registered
        if backend_name not in self._backends:
            raise BackendNotConfiguredError(
                f"Backend '{backend_name}' is enabled but no instance is configured."
            )

        # Resolve the path for the backend and run security validation
        try:
            resolved_path = self._resolve_and_validate_path(path, backend_name)
        except (BackendNotConfiguredError, BackendError, InvalidOperationError):
            raise
        except Exception as exc:
            raise BackendError(
                f"Error resolving path '{path}' for backend '{backend_name}': {exc}"
            ) from exc

        return self._backends[backend_name], resolved_path

    def _validate_backend_path_compatibility(self, backend_name: str, path: str) -> None:
        """Validate that the explicit backend is compatible with the path format.

        Raises InvalidOperationError for conflicting combinations:
        - Explicit backend="local" with an s3:// path

        Note: Explicit backend="s3" with a non-s3:// path is valid --
        the path is treated as an S3 key within the default bucket.

        Args:
            backend_name: The explicitly requested backend name.
            path: The file path to check.

        Raises:
            InvalidOperationError: If the backend/path combination is invalid.
        """
        if backend_name == BACKEND_LOCAL and path.startswith(S3_PREFIX):
            raise InvalidOperationError(
                f"Cannot use local backend with S3 path '{path}'. "
                "Use backend='s3' or remove the s3:// prefix."
            )

    def _resolve_and_validate_path(self, path: str, backend_name: str) -> str:
        """Resolve a path for the target backend and validate it with security.

        For local paths: validates against sandbox via SecurityValidator.
        For S3 paths: strips the s3:// prefix, validates the bucket name
        is not empty, and runs SecurityValidator.

        Args:
            path: Raw path string.
            backend_name: The backend this path targets.

        Returns:
            Resolved path string suitable for the backend.

        Raises:
            InvalidOperationError: If an S3 path has an empty bucket name.
        """
        if backend_name == BACKEND_S3:
            # Strip the s3:// prefix if present
            raw_key = path[len(S3_PREFIX) :] if path.startswith(S3_PREFIX) else path

            # Validate S3 bucket name is not empty for s3:// prefixed paths
            if path.startswith(S3_PREFIX) and (not raw_key or raw_key.startswith("/")):
                raise InvalidOperationError(
                    f"S3 path '{path}' has an empty bucket name. "
                    "Provide a valid bucket name: s3://bucket-name/key"
                )

            # Validate through security layer
            validated = self._security.validate_s3_path(raw_key)
            return validated

        # Local backend: validate through security layer
        validated_path = self._security.validate_local_path(path)
        return str(validated_path)
