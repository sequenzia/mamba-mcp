"""Local filesystem backend implementation.

Wraps fsspec's LocalFileSystem with security validation and metadata enrichment.
All operations delegate to fsspec after validating paths through the SecurityValidator.

Based on spec Sections 7.1 and 9.2.
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsspec.implementations.local import LocalFileSystem

from mamba_mcp_fs.config import LocalSettings
from mamba_mcp_fs.content import detect_mime_type
from mamba_mcp_fs.errors import (
    BackendError,
    InvalidOperationError,
    PathNotFoundError,
    PermissionDeniedError,
)
from mamba_mcp_fs.security import SecurityValidator


class LocalBackend:
    """Local filesystem backend backed by fsspec LocalFileSystem.

    Every public method validates its path arguments through the SecurityValidator
    before delegating to the underlying fsspec filesystem. Hidden file filtering
    and symlink policy checks are applied as appropriate.

    Args:
        fs: An fsspec LocalFileSystem instance.
        security: The SecurityValidator for path and policy checks.
        settings: Local backend configuration (base_path, show_hidden, etc.).
    """

    def __init__(
        self,
        fs: LocalFileSystem,
        security: SecurityValidator,
        settings: LocalSettings,
    ) -> None:
        self._fs = fs
        self._security = security
        self._settings = settings
        self._base_path = Path(settings.base_path).resolve()

    # ------------------------------------------------------------------
    # Path resolution helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> str:
        """Validate and resolve a path through the security layer.

        Checks symlink policy on the pre-resolved path before returning
        the fully resolved path. This ensures symlinks are detected even
        though validate_local_path resolves them.

        Args:
            path: Raw user-supplied path (absolute or relative to base_path).

        Returns:
            Absolute path string validated to be within the sandbox.
        """
        # Build the pre-resolved path to check symlink policy
        pre_resolved = self._make_pre_resolved_path(path)
        self._security.check_symlink(pre_resolved)

        validated = self._security.validate_local_path(path)
        return str(validated)

    def _make_pre_resolved_path(self, path: str) -> Path:
        """Construct the absolute path WITHOUT resolving symlinks.

        This is used to check symlink policy before validate_local_path
        resolves the path through Path.resolve().
        """
        p = Path(path)
        if not p.is_absolute():
            return self._base_path / path
        return p

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        """List directory entries with optional metadata.

        Args:
            path: Directory path to list.
            detail: If True, return dicts with metadata; if False, return name-only dicts.

        Returns:
            List of entry dicts. When detail=True, each dict includes standardized
            keys: name, type, size, created, modified, islink, mode.

        Raises:
            PathNotFoundError: If the directory does not exist.
            BackendError: For other OS-level failures.
        """
        resolved = self._resolve_path(path)

        try:
            entries: list[dict[str, Any]] = self._fs.ls(resolved, detail=True)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"Directory not found: {path}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied: {path}") from exc
        except OSError as exc:
            raise BackendError(f"Filesystem error listing '{path}': {exc}") from exc

        # Filter hidden files based on config
        filtered = self._filter_hidden_entries(entries)

        # Check symlink policy for each entry
        filtered = self._filter_symlink_entries(filtered)

        if not detail:
            return [{"name": entry["name"]} for entry in filtered]

        return [self._standardize_entry(entry) for entry in filtered]

    def _filter_hidden_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove hidden entries from listing based on config.

        Uses SecurityValidator.filter_hidden to decide which entries to keep.
        """
        names = [os.path.basename(e["name"]) for e in entries]
        visible_names = set(self._security.filter_hidden(names))
        return [e for e in entries if os.path.basename(e["name"]) in visible_names]

    def _filter_symlink_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter entries based on symlink policy.

        When follow_symlinks is False, symlink entries are excluded.
        When follow_symlinks is True, symlinks are kept but their targets
        must be within the sandbox (validated by check_symlink).
        """
        result = []
        for entry in entries:
            entry_path = Path(entry["name"])
            if entry_path.is_symlink():
                if not self._settings.follow_symlinks:
                    continue
                # When following symlinks, validate the target is in sandbox
                try:
                    self._security.check_symlink(entry_path)
                except Exception:
                    continue
            result.append(entry)
        return result

    def _standardize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Map an fsspec ls entry to a standardized format.

        Adds human-readable fields and normalizes key names.
        """
        return {
            "name": entry.get("name", ""),
            "type": entry.get("type", "unknown"),
            "size": entry.get("size", 0),
            "created": entry.get("created"),
            "modified": entry.get("mtime"),
            "islink": entry.get("islink", False),
            "mode": entry.get("mode"),
        }

    # ------------------------------------------------------------------
    # File/directory info
    # ------------------------------------------------------------------

    def info(self, path: str) -> dict[str, Any]:
        """Get file or directory metadata with enriched information.

        Adds MIME type detection, permissions string, symlink detection,
        and creation timestamp beyond what fsspec provides.

        Args:
            path: Path to the file or directory.

        Returns:
            Dict with metadata keys: name, type, size, created, modified,
            islink, mode, permissions, mime_type, created_at.

        Raises:
            PathNotFoundError: If the path does not exist.
            BackendError: For other OS-level failures.
        """
        # Capture pre-resolved path for symlink detection
        pre_resolved = self._make_pre_resolved_path(path)
        resolved = self._resolve_path(path)

        try:
            raw_info: dict[str, Any] = self._fs.info(resolved)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"Path not found: {path}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied: {path}") from exc
        except OSError as exc:
            raise BackendError(f"Filesystem error getting info for '{path}': {exc}") from exc

        result = self._standardize_entry(raw_info)

        # Add MIME type for files
        if raw_info.get("type") == "file":
            result["mime_type"] = detect_mime_type(resolved)
        else:
            result["mime_type"] = "inode/directory"

        # Add permissions string from mode
        mode = raw_info.get("mode")
        if mode is not None:
            result["permissions"] = stat.filemode(mode)
        else:
            result["permissions"] = None

        # Detect symlink status on the pre-resolved path (before resolve() follows it)
        result["islink"] = pre_resolved.is_symlink()

        # Add created_at timestamp from os.stat if available
        try:
            st = os.stat(resolved)
            # Use st_birthtime on macOS, fall back to st_ctime
            birth = getattr(st, "st_birthtime", None)
            if birth is not None:
                result["created_at"] = datetime.fromtimestamp(birth, tz=UTC).isoformat()
            elif st.st_ctime:
                result["created_at"] = datetime.fromtimestamp(st.st_ctime, tz=UTC).isoformat()
            else:
                result["created_at"] = None
        except OSError:
            result["created_at"] = None

        return result

    # ------------------------------------------------------------------
    # File reading
    # ------------------------------------------------------------------

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        """Read file content as bytes.

        For full reads (no start/end), validates file size against the
        configured limit. Chunked reads bypass the size check.

        Args:
            path: Path to the file.
            start: Optional byte offset to start reading from.
            end: Optional byte offset to stop reading at.

        Returns:
            File content as bytes.

        Raises:
            PathNotFoundError: If the file does not exist.
            BackendError: For other OS-level failures.
        """
        resolved = self._resolve_path(path)

        # Check file size limit for full reads
        if start is None and end is None:
            try:
                file_info = self._fs.info(resolved)
                self._security.check_file_size(file_info.get("size", 0), "local")
            except FileNotFoundError as exc:
                raise PathNotFoundError(f"File not found: {path}") from exc

        try:
            return self._fs.cat_file(resolved, start=start, end=end)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"File not found: {path}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied: {path}") from exc
        except OSError as exc:
            raise BackendError(f"Filesystem error reading '{path}': {exc}") from exc

    # ------------------------------------------------------------------
    # File writing
    # ------------------------------------------------------------------

    def pipe_file(self, path: str, data: bytes) -> None:
        """Write data to a file.

        Validates the data size against the configured limit and checks
        the file extension against the security policy.

        Args:
            path: Path to the file.
            data: Bytes to write.

        Raises:
            PathNotFoundError: If the parent directory does not exist.
            BackendError: For other OS-level failures.
        """
        resolved = self._resolve_path(path)

        # Check size and extension restrictions
        self._security.check_file_size(len(data), "local")
        self._security.check_extension(path)

        try:
            self._fs.pipe_file(resolved, data)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"Parent directory not found for: {path}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied writing: {path}") from exc
        except OSError as exc:
            raise BackendError(f"Filesystem error writing '{path}': {exc}") from exc

    # ------------------------------------------------------------------
    # File deletion
    # ------------------------------------------------------------------

    def rm(self, path: str) -> None:
        """Delete a file (not directories).

        Validates the path is a file before attempting deletion.

        Args:
            path: Path to the file to delete.

        Raises:
            PathNotFoundError: If the file does not exist.
            InvalidOperationError: If the path is a directory.
            BackendError: For other OS-level failures.
        """
        resolved = self._resolve_path(path)

        # Validate target is a file, not a directory
        try:
            if self._fs.isdir(resolved):
                raise InvalidOperationError(f"Cannot remove directory with rm, use rmdir: {path}")
            if not self._fs.exists(resolved):
                raise PathNotFoundError(f"File not found: {path}")
        except (InvalidOperationError, PathNotFoundError):
            raise
        except OSError as exc:
            raise BackendError(f"Filesystem error checking '{path}': {exc}") from exc

        try:
            self._fs.rm(resolved)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"File not found: {path}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied deleting: {path}") from exc
        except OSError as exc:
            raise BackendError(f"Filesystem error deleting '{path}': {exc}") from exc

    # ------------------------------------------------------------------
    # File copy
    # ------------------------------------------------------------------

    def cp_file(self, source: str, destination: str) -> None:
        """Copy a file from source to destination.

        Both paths are validated through the security layer.

        Args:
            source: Source file path.
            destination: Destination file path.

        Raises:
            PathNotFoundError: If the source file does not exist.
            BackendError: For other OS-level failures.
        """
        resolved_src = self._resolve_path(source)
        resolved_dst = self._resolve_path(destination)

        try:
            self._fs.cp_file(resolved_src, resolved_dst)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"Source file not found: {source}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied copying: {source}") from exc
        except OSError as exc:
            raise BackendError(
                f"Filesystem error copying '{source}' to '{destination}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # File move
    # ------------------------------------------------------------------

    def mv(self, source: str, destination: str) -> None:
        """Move a file from source to destination.

        Both paths are validated through the security layer.

        Args:
            source: Source file path.
            destination: Destination file path.

        Raises:
            PathNotFoundError: If the source file does not exist.
            BackendError: For other OS-level failures.
        """
        resolved_src = self._resolve_path(source)
        resolved_dst = self._resolve_path(destination)

        try:
            self._fs.mv(resolved_src, resolved_dst)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"Source not found: {source}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied moving: {source}") from exc
        except OSError as exc:
            raise BackendError(
                f"Filesystem error moving '{source}' to '{destination}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Directory creation
    # ------------------------------------------------------------------

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        """Create a directory.

        Args:
            path: Directory path to create.
            create_parents: If True, create parent directories as needed.

        Raises:
            BackendError: For OS-level failures.
        """
        resolved = self._resolve_path(path)

        try:
            if create_parents:
                self._fs.makedirs(resolved, exist_ok=True)
            else:
                self._fs.mkdir(resolved)
        except FileNotFoundError as exc:
            raise PathNotFoundError(f"Parent directory not found for: {path}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied creating directory: {path}") from exc
        except OSError as exc:
            raise BackendError(f"Filesystem error creating directory '{path}': {exc}") from exc

    # ------------------------------------------------------------------
    # Existence checks
    # ------------------------------------------------------------------

    def exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check.

        Returns:
            True if the path exists.
        """
        resolved = self._resolve_path(path)
        try:
            return self._fs.exists(resolved)
        except OSError:
            return False

    def isdir(self, path: str) -> bool:
        """Check if a path is a directory.

        Args:
            path: Path to check.

        Returns:
            True if the path is a directory.
        """
        resolved = self._resolve_path(path)
        try:
            return self._fs.isdir(resolved)
        except OSError:
            return False

    def isfile(self, path: str) -> bool:
        """Check if a path is a file.

        Args:
            path: Path to check.

        Returns:
            True if the path is a file.
        """
        resolved = self._resolve_path(path)
        try:
            return self._fs.isfile(resolved)
        except OSError:
            return False
