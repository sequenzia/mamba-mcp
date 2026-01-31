"""Pydantic models for MCP tool inputs and outputs."""

from mamba_mcp_fs.models.files import (
    BucketInfo,
    FileEntry,
    FileInfo,
    SearchResult,
    format_size,
)
from mamba_mcp_fs.models.responses import (
    CopyFileResponse,
    CreateDirectoryResponse,
    DeleteFileResponse,
    FileInfoResponse,
    ListBucketsResponse,
    ListDirectoryResponse,
    MoveFileResponse,
    ObjectMetadataResponse,
    PresignedUrlResponse,
    ReadFileResponse,
    SearchResponse,
    WriteFileResponse,
)

__all__ = [
    # Core data models
    "FileEntry",
    "FileInfo",
    "SearchResult",
    "BucketInfo",
    "format_size",
    # Layer 1: Discovery responses
    "ListDirectoryResponse",
    "FileInfoResponse",
    "ReadFileResponse",
    "SearchResponse",
    # Layer 2: S3 Extra responses
    "ListBucketsResponse",
    "PresignedUrlResponse",
    "ObjectMetadataResponse",
    # Layer 3: Mutation responses
    "WriteFileResponse",
    "DeleteFileResponse",
    "MoveFileResponse",
    "CopyFileResponse",
    "CreateDirectoryResponse",
]
