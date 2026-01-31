"""Core data models for filesystem entries and metadata.

Based on spec Sections 5.1-5.3 and 7.3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field


def format_size(size_bytes: int | None) -> str:
    """Convert a byte count to a human-readable string.

    Args:
        size_bytes: Number of bytes, or None.

    Returns:
        Human-readable size string (e.g., "1.2 MB"). Returns "0 B" for 0 or None.
    """
    if size_bytes is None or size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        # Bytes are always whole numbers
        return f"{int(value)} B"

    # Use one decimal place for larger units, strip trailing zero
    formatted = f"{value:.1f}"
    if formatted.endswith(".0"):
        formatted = formatted[:-2]
    return f"{formatted} {units[unit_index]}"


class FileEntry(BaseModel):
    """A file or directory entry returned by list_directory.

    Represents basic metadata for both local and S3 filesystem entries.
    """

    name: str = Field(description="File or directory name")
    path: str = Field(description="Full path to the entry")
    type: Literal["file", "directory"] = Field(description="Entry type")
    size_bytes: int | None = Field(
        default=None,
        description="File size in bytes (None for directories without calculated size)",
    )
    modified_at: datetime | None = Field(
        default=None, description="Last modified timestamp (ISO 8601)"
    )
    is_hidden: bool = Field(default=False, description="Whether the entry is hidden/dotfile")


class FileInfo(BaseModel):
    """Detailed file metadata returned by get_file_info.

    Extends FileEntry fields with additional detail for both local and S3 backends.
    """

    name: str = Field(description="File or directory name")
    path: str = Field(description="Full path to the entry")
    type: Literal["file", "directory"] = Field(description="Entry type")
    size_bytes: int | None = Field(
        default=None, description="File size in bytes (None for directories)"
    )
    modified_at: datetime | None = Field(
        default=None, description="Last modified timestamp (ISO 8601)"
    )
    is_hidden: bool = Field(default=False, description="Whether the entry is hidden/dotfile")
    mime_type: str | None = Field(default=None, description="Detected MIME type")
    created_at: datetime | None = Field(
        default=None, description="Creation timestamp (ISO 8601, null if unavailable)"
    )
    is_symlink: bool = Field(default=False, description="Whether entry is a symbolic link (local)")
    permissions: str | None = Field(
        default=None, description="File permissions string (local, e.g., 'rw-r--r--')"
    )
    checksum: str | None = Field(default=None, description="SHA-256 checksum when requested")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def size_pretty(self) -> str:
        """Human-readable file size (e.g., '1.2 MB')."""
        return format_size(self.size_bytes)


class SearchResult(BaseModel):
    """A single search result returned by search_files."""

    path: str = Field(description="Full path to the matched entry")
    name: str = Field(description="File or directory name")
    type: Literal["file", "directory"] = Field(description="Entry type")
    size_bytes: int | None = Field(default=None, description="File size in bytes")
    modified_at: datetime | None = Field(
        default=None, description="Last modified timestamp (ISO 8601)"
    )
    match_context: str | None = Field(
        default=None, description="Surrounding lines for content matches"
    )


class BucketInfo(BaseModel):
    """S3 bucket information returned by list_buckets."""

    name: str = Field(description="Bucket name")
    creation_date: datetime | None = Field(default=None, description="Bucket creation date")
    region: str | None = Field(default=None, description="Bucket region")
