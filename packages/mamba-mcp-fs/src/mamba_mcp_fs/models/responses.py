"""Tool response models for the Filesystem MCP Server.

Based on spec Sections 5.1-5.3 (REQ-001 through REQ-012) and 7.3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from mamba_mcp_fs.models.files import (
    BucketInfo,
    FileEntry,
    SearchResult,
    format_size,
)

# === Layer 1: Discovery Tool Responses ===


class ListDirectoryResponse(BaseModel):
    """Response for list_directory tool (REQ-001)."""

    path: str = Field(description="The listed directory path")
    backend: str = Field(description="Which backend served this request (local or s3)")
    entries: list[FileEntry] = Field(description="List of file/directory entries")
    total_count: int = Field(description="Number of entries returned")
    has_more: bool = Field(description="Whether more entries exist beyond max_entries")


class FileInfoResponse(BaseModel):
    """Response for get_file_info tool (REQ-002).

    Contains all FileInfo fields plus path and backend context.
    """

    path: str = Field(description="Full path to the file")
    backend: str = Field(description="Which backend served this request")
    name: str = Field(description="File name")
    type: Literal["file", "directory"] = Field(description="Entry type")
    size_bytes: int | None = Field(default=None, description="File size in bytes")
    mime_type: str | None = Field(default=None, description="Detected MIME type")
    modified_at: datetime | None = Field(
        default=None, description="Last modified timestamp (ISO 8601)"
    )
    created_at: datetime | None = Field(
        default=None, description="Creation timestamp (ISO 8601, null if unavailable)"
    )
    is_hidden: bool = Field(default=False, description="Whether file is hidden/dotfile")
    is_symlink: bool = Field(
        default=False, description="Whether file is a symbolic link (local only)"
    )
    permissions: str | None = Field(
        default=None, description="File permissions string (local only, e.g., 'rw-r--r--')"
    )
    checksum: str | None = Field(default=None, description="SHA-256 checksum if requested")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def size_pretty(self) -> str:
        """Human-readable file size (e.g., '1.2 MB')."""
        return format_size(self.size_bytes)


class ReadFileResponse(BaseModel):
    """Response for read_file tool (REQ-003)."""

    path: str = Field(description="Path to the file read")
    backend: str = Field(description="Which backend served this request")
    content: str = Field(description="File content (text or base64-encoded)")
    encoding: Literal["text", "base64"] = Field(description="The encoding used")
    mime_type: str | None = Field(default=None, description="Detected MIME type")
    size_bytes: int = Field(description="Total file size")
    bytes_read: int = Field(description="Number of bytes actually read")
    offset: int = Field(default=0, description="Byte offset this chunk starts at")
    has_more: bool = Field(description="Whether more content exists beyond what was read")
    is_truncated: bool = Field(description="Whether content was truncated due to size limit")


class SearchResponse(BaseModel):
    """Response for search_files tool (REQ-004)."""

    path: str = Field(description="The root search path")
    backend: str = Field(description="Which backend served this request")
    results: list[SearchResult] = Field(description="List of matching entries")
    total_matches: int = Field(description="Number of results returned")
    search_truncated: bool = Field(description="Whether results were truncated at max_results")
    directories_searched: int = Field(description="Number of directories traversed")


# === Layer 2: S3 Extra Responses ===


class ListBucketsResponse(BaseModel):
    """Response for list_buckets tool (REQ-005)."""

    buckets: list[BucketInfo] = Field(description="List of accessible S3 buckets")
    total_count: int = Field(description="Number of buckets")


class PresignedUrlResponse(BaseModel):
    """Response for get_presigned_url tool (REQ-006)."""

    url: str = Field(description="The presigned URL")
    path: str = Field(description="The S3 object path")
    operation: Literal["download", "upload"] = Field(description="download or upload")
    expires_at: datetime = Field(description="ISO 8601 timestamp when URL expires")


class ObjectMetadataResponse(BaseModel):
    """Response for get_object_metadata tool (REQ-007)."""

    path: str = Field(description="S3 object path")
    storage_class: str = Field(description="S3 storage class (STANDARD, GLACIER, etc.)")
    etag: str = Field(description="Object ETag")
    version_id: str | None = Field(
        default=None, description="Current version ID (if versioning enabled)"
    )
    tags: dict[str, str] | None = Field(default=None, description="Object tags (if requested)")
    versions: list[dict[str, Any]] | None = Field(
        default=None, description="Version history (if requested and versioning enabled)"
    )
    server_side_encryption: str | None = Field(
        default=None, description="Encryption type if applicable"
    )
    content_type: str = Field(description="S3 content type header")
    last_modified: datetime = Field(description="Last modified timestamp")


# === Layer 3: Mutation Tool Responses ===


class WriteFileResponse(BaseModel):
    """Response for write_file tool (REQ-008)."""

    path: str = Field(description="Path of the written file")
    backend: str = Field(description="Which backend served this request")
    size_bytes: int = Field(description="Size of the written file")
    created: bool = Field(description="Whether a new file was created (vs overwritten)")


class DeleteFileResponse(BaseModel):
    """Response for delete_file tool (REQ-009)."""

    path: str = Field(description="Path of the deleted file")
    backend: str = Field(description="Which backend served this request")
    deleted: bool = Field(description="Boolean confirming deletion")


class MoveFileResponse(BaseModel):
    """Response for move_file tool (REQ-010)."""

    source: str = Field(description="Original path")
    destination: str = Field(description="New path")
    backend: str = Field(description="Which backend served this request")
    overwritten: bool = Field(description="Whether an existing file was overwritten")


class CopyFileResponse(BaseModel):
    """Response for copy_file tool (REQ-011)."""

    source: str = Field(description="Source path")
    destination: str = Field(description="Destination path")
    source_backend: str = Field(description="Source backend used")
    dest_backend: str = Field(description="Destination backend used")
    size_bytes: int = Field(description="Size of the copied file")
    cross_backend: bool = Field(description="Whether this was a cross-backend copy")


class CreateDirectoryResponse(BaseModel):
    """Response for create_directory tool (REQ-012)."""

    path: str = Field(description="Path of the created directory")
    backend: str = Field(description="Which backend served this request")
    created: bool = Field(
        description="Whether the directory was newly created (vs already existed)"
    )
