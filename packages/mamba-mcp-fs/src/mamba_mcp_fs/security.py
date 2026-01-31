"""Security controls for the Filesystem MCP Server.

Provides path validation, sandbox enforcement, symlink policy, hidden file filtering,
extension filtering, and size limit enforcement. This is the most security-critical
component -- all file operations must pass through the SecurityValidator before
any backend operation.

Based on spec Section 6.2 (REQ-SEC-001 through REQ-SEC-005).
"""

from __future__ import annotations

import posixpath
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from mamba_mcp_fs.config import LocalSettings, S3Settings, ServerSettings
from mamba_mcp_fs.errors import (
    FileTooLargeError,
    PathOutsideSandboxError,
    PermissionDeniedError,
    SymlinkBlockedError,
)


def _decode_url_encoding(path: str) -> str:
    """Decode URL-encoded path components, handling double encoding.

    Repeatedly decodes until the path no longer changes, preventing
    double-encoding bypass attacks like ``%252e%252e%252f``.

    Args:
        path: The raw path string that may contain URL-encoded characters.

    Returns:
        The fully decoded path string.
    """
    previous = path
    decoded = unquote(previous)
    while decoded != previous:
        previous = decoded
        decoded = unquote(previous)
    return decoded


def _strip_null_bytes(path: str) -> str:
    """Remove null bytes from a path string.

    Null bytes can be used in path injection attacks to truncate
    paths at the C string level while Python sees the full string.

    Args:
        path: Path string that may contain null bytes.

    Returns:
        Path string with all null bytes removed.
    """
    return path.replace("\x00", "")


def _normalize_unicode(path: str) -> str:
    """Normalize unicode characters to NFC form.

    Prevents unicode normalization attacks where visually identical
    characters (e.g. combining dot sequences) resolve to different
    byte sequences. NFC is the canonical composed form.

    Args:
        path: Path string that may contain non-normalized unicode.

    Returns:
        NFC-normalized path string.
    """
    return unicodedata.normalize("NFC", path)


def _sanitize_path(raw_path: str) -> str:
    """Apply all path sanitization steps in the correct order.

    Order matters: decode URL encoding first (to reveal hidden traversal),
    strip null bytes, then normalize unicode.

    Args:
        raw_path: The raw user-supplied path string.

    Returns:
        Sanitized path string ready for resolution and validation.
    """
    step1 = _decode_url_encoding(raw_path)
    step2 = _strip_null_bytes(step1)
    step3 = _normalize_unicode(step2)
    return step3


def _is_hidden(name: str) -> bool:
    """Check if a filename is a hidden file (dotfile).

    A name is considered hidden if it starts with a dot character.
    Empty strings and the special entries '.' and '..' are not hidden.

    Args:
        name: The filename (not full path) to check.

    Returns:
        True if the name represents a hidden file.
    """
    return name.startswith(".") and name not in (".", "..")


class SecurityValidator:
    """Validates file paths and enforces security policies.

    This class is the central security gate for all file operations.
    It takes configuration from ServerSettings, LocalSettings, and S3Settings
    and provides methods to validate paths, check extensions, enforce size
    limits, filter hidden files, and check symlink policies.

    Args:
        server_settings: Server-level configuration (extensions, read_only).
        local_settings: Local filesystem backend configuration (base_path, symlinks, hidden).
        s3_settings: S3 backend configuration (bucket, prefix, max_file_size).
    """

    def __init__(
        self,
        server_settings: ServerSettings,
        local_settings: LocalSettings | None = None,
        s3_settings: S3Settings | None = None,
    ) -> None:
        self._server = server_settings
        self._local = local_settings
        self._s3 = s3_settings

        # Pre-compute the resolved base path for local backend
        if local_settings is not None and local_settings.base_path:
            self._resolved_base = Path(local_settings.base_path).resolve()
        else:
            self._resolved_base = None

        # Pre-parse extension sets from server settings
        self._allowed_extensions = server_settings.parsed_allowed_extensions
        self._denied_extensions = server_settings.parsed_denied_extensions

    def validate_local_path(self, path: str) -> Path:
        """Resolve and validate a local filesystem path against the sandbox.

        Applies all sanitization steps (URL decoding, null byte removal,
        unicode normalization), resolves the path to an absolute path,
        and verifies it falls within the configured base_path sandbox.

        Args:
            path: Raw user-supplied path string.

        Returns:
            The resolved absolute Path within the sandbox.

        Raises:
            PathOutsideSandboxError: If the resolved path is outside the sandbox.
        """
        if self._resolved_base is None:
            raise PathOutsideSandboxError("No base path configured for local backend")

        sanitized = _sanitize_path(path)

        # Resolve the path relative to the sandbox base
        if not Path(sanitized).is_absolute():
            resolved = (self._resolved_base / sanitized).resolve()
        else:
            resolved = Path(sanitized).resolve()

        # Validate that the resolved path is within the sandbox
        # Use string comparison with trailing separator to avoid prefix-match attacks
        # e.g., /sandbox-other should not match /sandbox
        base_str = str(self._resolved_base)
        resolved_str = str(resolved)

        if resolved_str != base_str and not resolved_str.startswith(base_str + "/"):
            raise PathOutsideSandboxError(
                f"Path '{path}' resolves to '{resolved}' which is outside "
                f"the sandbox '{self._resolved_base}'"
            )

        return resolved

    def validate_s3_path(self, path: str) -> str:
        """Validate an S3 object path against the configured bucket and prefix.

        Sanitizes the path, validates it starts with the configured prefix
        (if any), and blocks path traversal attempts within the S3 key space.

        Args:
            path: Raw S3 object key or path.

        Returns:
            The sanitized S3 object key.

        Raises:
            PathOutsideSandboxError: If the path escapes the configured prefix.
        """
        sanitized = _sanitize_path(path)

        # S3 keys should not contain path traversal sequences after sanitization.
        # Use posixpath.normpath to collapse .. and . components, then strip the
        # leading slash. normpath("/../../foo") -> "/foo" -> "foo"
        joined = posixpath.normpath("/" + sanitized)
        normalized = joined.lstrip("/")

        # Check that the normalized key starts with the configured prefix
        if self._s3 is not None and self._s3.prefix:
            prefix = self._s3.prefix.strip("/")
            if prefix and not normalized.startswith(prefix + "/") and normalized != prefix:
                raise PathOutsideSandboxError(
                    f"S3 path '{path}' is outside the configured prefix '{self._s3.prefix}'"
                )

        return normalized

    def check_extension(self, path: str) -> None:
        """Validate that a file's extension is allowed by the configured policy.

        If an allowlist is configured, only those extensions are permitted
        (allowlist takes precedence). Otherwise, if a denylist is configured,
        those extensions are blocked. If neither is configured, all extensions
        are allowed.

        Args:
            path: File path to check the extension of.

        Raises:
            PermissionDeniedError: If the file extension is blocked.
        """
        # Extract the extension, lowercased
        ext = PurePosixPath(path).suffix.lower()

        # No extension means no restriction can apply
        if not ext:
            return

        # Allowlist takes precedence if configured
        if self._allowed_extensions is not None:
            if ext not in self._allowed_extensions:
                raise PermissionDeniedError(
                    f"Extension '{ext}' is not in the allowed list: "
                    f"{sorted(self._allowed_extensions)}"
                )
            return

        # Denylist check
        if self._denied_extensions is not None:
            if ext in self._denied_extensions:
                raise PermissionDeniedError(
                    f"Extension '{ext}' is in the denied list: "
                    f"{sorted(self._denied_extensions)}"
                )

    def check_file_size(self, size: int, backend: str) -> None:
        """Check that a file size is within the configured limit for the backend.

        Args:
            size: File size in bytes.
            backend: Backend identifier ('local' or 's3').

        Raises:
            FileTooLargeError: If the size exceeds the backend's max_file_size.
        """
        if backend == "local" and self._local is not None:
            max_size = self._local.max_file_size
        elif backend == "s3" and self._s3 is not None:
            max_size = self._s3.max_file_size
        else:
            # No limit configured for this backend
            return

        if size > max_size:
            raise FileTooLargeError(
                f"File size {size} bytes exceeds maximum {max_size} bytes for {backend} backend"
            )

    def filter_hidden(
        self, entries: list[str], include_hidden: bool | None = None
    ) -> list[str]:
        """Filter hidden files from a list of file/directory names.

        Uses the local backend's ``show_hidden`` setting as the default.
        The ``include_hidden`` parameter allows per-call override.

        Args:
            entries: List of filenames or paths to filter.
            include_hidden: If not None, overrides the config-level show_hidden setting.

        Returns:
            Filtered list with hidden entries removed (if policy says to exclude them).
        """
        # Determine whether to show hidden files
        if include_hidden is not None:
            show = include_hidden
        elif self._local is not None:
            show = self._local.show_hidden
        else:
            show = False

        if show:
            return entries

        return [entry for entry in entries if not _is_hidden(_get_basename(entry))]

    def check_symlink(self, path: Path) -> None:
        """Check a path against the symlink policy.

        When ``follow_symlinks`` is False, any symlink causes a
        SymlinkBlockedError. When True, the symlink target is resolved
        and validated to be within the sandbox. Handles nested symlink chains.

        Args:
            path: The filesystem path to check.

        Raises:
            SymlinkBlockedError: If the symlink policy blocks access.
            PathOutsideSandboxError: If a followed symlink points outside the sandbox.
        """
        if self._local is None:
            return

        if not path.is_symlink():
            return

        if not self._local.follow_symlinks:
            raise SymlinkBlockedError(
                f"Symlink access blocked: '{path}'. "
                "Set follow_symlinks=true to allow symlink access."
            )

        # follow_symlinks is True: resolve the symlink and verify it stays in sandbox
        if self._resolved_base is None:
            raise PathOutsideSandboxError("No base path configured for local backend")

        resolved_target = path.resolve()
        base_str = str(self._resolved_base)
        target_str = str(resolved_target)

        if target_str != base_str and not target_str.startswith(base_str + "/"):
            raise PathOutsideSandboxError(
                f"Symlink '{path}' resolves to '{resolved_target}' which is "
                f"outside the sandbox '{self._resolved_base}'"
            )


def _get_basename(entry: str) -> str:
    """Extract the basename from a path or return the entry if it has no separators.

    Args:
        entry: A filename or path string.

    Returns:
        The basename (last component) of the path.
    """
    # Handle both forward and backslash separators
    name = entry.rstrip("/").rstrip("\\")
    if "/" in name:
        return name.rsplit("/", 1)[-1]
    if "\\" in name:
        return name.rsplit("\\", 1)[-1]
    return name
