"""Tests for Pydantic models (file entries, metadata, and tool responses).

Covers model instantiation, validation rejection, size_pretty formatting,
JSON serialization/deserialization round-trips, and edge cases.
"""

from datetime import UTC, datetime

import pytest
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
from pydantic import ValidationError

# === format_size utility tests ===


class TestFormatSize:
    """Tests for the format_size utility function."""

    def test_zero_bytes(self) -> None:
        assert format_size(0) == "0 B"

    def test_none_value(self) -> None:
        assert format_size(None) == "0 B"

    def test_small_bytes(self) -> None:
        assert format_size(500) == "500 B"

    def test_one_byte(self) -> None:
        assert format_size(1) == "1 B"

    def test_kilobytes(self) -> None:
        # 1.5 KB = 1536 bytes
        assert format_size(1536) == "1.5 KB"

    def test_exact_kilobyte(self) -> None:
        assert format_size(1024) == "1 KB"

    def test_megabytes(self) -> None:
        # 2.3 MB = 2.3 * 1024 * 1024 = 2411724.8
        assert format_size(2411725) == "2.3 MB"

    def test_gigabytes(self) -> None:
        # 1.1 GB = 1.1 * 1024^3 = 1181116006.4
        assert format_size(1181116006) == "1.1 GB"

    def test_exact_megabyte(self) -> None:
        assert format_size(1048576) == "1 MB"

    def test_exact_gigabyte(self) -> None:
        assert format_size(1073741824) == "1 GB"

    def test_terabyte_range(self) -> None:
        assert format_size(1099511627776) == "1 TB"

    def test_1023_bytes(self) -> None:
        assert format_size(1023) == "1023 B"


# === FileEntry tests ===


class TestFileEntry:
    """Tests for the FileEntry model."""

    def test_create_file_entry(self) -> None:
        entry = FileEntry(
            name="readme.md",
            path="/project/readme.md",
            type="file",
            size_bytes=1024,
            modified_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
            is_hidden=False,
        )
        assert entry.name == "readme.md"
        assert entry.path == "/project/readme.md"
        assert entry.type == "file"
        assert entry.size_bytes == 1024
        assert entry.is_hidden is False

    def test_create_directory_entry(self) -> None:
        entry = FileEntry(
            name="src",
            path="/project/src",
            type="directory",
        )
        assert entry.type == "directory"
        assert entry.size_bytes is None
        assert entry.modified_at is None
        assert entry.is_hidden is False

    def test_hidden_file(self) -> None:
        entry = FileEntry(
            name=".gitignore",
            path="/project/.gitignore",
            type="file",
            is_hidden=True,
        )
        assert entry.is_hidden is True

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FileEntry(
                name="test",
                path="/test",
                type="symlink",  # type: ignore[arg-type]
            )

    def test_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            FileEntry()  # type: ignore[call-arg]

    def test_wrong_size_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FileEntry(
                name="test",
                path="/test",
                type="file",
                size_bytes="not_a_number",  # type: ignore[arg-type]
            )


# === FileInfo tests ===


class TestFileInfo:
    """Tests for the FileInfo model."""

    def test_create_full_file_info(self) -> None:
        info = FileInfo(
            name="data.csv",
            path="/sandbox/data.csv",
            type="file",
            size_bytes=2411725,
            modified_at=datetime(2025, 6, 1, 10, 30, 0, tzinfo=UTC),
            is_hidden=False,
            mime_type="text/csv",
            created_at=datetime(2025, 5, 1, 8, 0, 0, tzinfo=UTC),
            is_symlink=False,
            permissions="rw-r--r--",
            checksum="abc123def456",
        )
        assert info.name == "data.csv"
        assert info.mime_type == "text/csv"
        assert info.permissions == "rw-r--r--"
        assert info.size_pretty == "2.3 MB"

    def test_size_pretty_computed(self) -> None:
        info = FileInfo(
            name="small.txt",
            path="/sandbox/small.txt",
            type="file",
            size_bytes=500,
        )
        assert info.size_pretty == "500 B"

    def test_size_pretty_none_bytes(self) -> None:
        info = FileInfo(
            name="dir",
            path="/sandbox/dir",
            type="directory",
        )
        assert info.size_pretty == "0 B"

    def test_s3_file_info_local_fields_none(self) -> None:
        """S3 entries have is_symlink False and permissions None."""
        info = FileInfo(
            name="data.json",
            path="s3://bucket/data.json",
            type="file",
            size_bytes=4096,
            mime_type="application/json",
        )
        assert info.is_symlink is False
        assert info.permissions is None
        assert info.checksum is None

    def test_local_file_info_with_symlink(self) -> None:
        info = FileInfo(
            name="link",
            path="/sandbox/link",
            type="file",
            is_symlink=True,
        )
        assert info.is_symlink is True


# === SearchResult tests ===


class TestSearchResult:
    """Tests for the SearchResult model."""

    def test_create_search_result_with_context(self) -> None:
        result = SearchResult(
            path="/project/main.py",
            name="main.py",
            type="file",
            size_bytes=2048,
            match_context="def main():\n    print('hello')",
        )
        assert result.match_context == "def main():\n    print('hello')"

    def test_create_search_result_name_only(self) -> None:
        result = SearchResult(
            path="/project/config/settings.yaml",
            name="settings.yaml",
            type="file",
        )
        assert result.match_context is None
        assert result.size_bytes is None

    def test_directory_search_result(self) -> None:
        result = SearchResult(
            path="/project/tests",
            name="tests",
            type="directory",
        )
        assert result.type == "directory"


# === BucketInfo tests ===


class TestBucketInfo:
    """Tests for the BucketInfo model."""

    def test_create_full_bucket_info(self) -> None:
        bucket = BucketInfo(
            name="my-data-bucket",
            creation_date=datetime(2024, 3, 15, 0, 0, 0, tzinfo=UTC),
            region="us-west-2",
        )
        assert bucket.name == "my-data-bucket"
        assert bucket.region == "us-west-2"

    def test_bucket_minimal(self) -> None:
        bucket = BucketInfo(name="bucket-name")
        assert bucket.creation_date is None
        assert bucket.region is None

    def test_missing_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BucketInfo()  # type: ignore[call-arg]


# === ListDirectoryResponse tests ===


class TestListDirectoryResponse:
    """Tests for the ListDirectoryResponse model."""

    def test_create_response(self) -> None:
        resp = ListDirectoryResponse(
            path="/sandbox",
            backend="local",
            entries=[
                FileEntry(name="file.txt", path="/sandbox/file.txt", type="file", size_bytes=100),
                FileEntry(name="sub", path="/sandbox/sub", type="directory"),
            ],
            total_count=2,
            has_more=False,
        )
        assert len(resp.entries) == 2
        assert resp.total_count == 2
        assert resp.has_more is False

    def test_empty_directory(self) -> None:
        resp = ListDirectoryResponse(
            path="/sandbox/empty",
            backend="local",
            entries=[],
            total_count=0,
            has_more=False,
        )
        assert resp.entries == []
        assert resp.total_count == 0

    def test_has_more_flag(self) -> None:
        resp = ListDirectoryResponse(
            path="s3://bucket/prefix",
            backend="s3",
            entries=[FileEntry(name="obj", path="s3://bucket/prefix/obj", type="file")],
            total_count=1,
            has_more=True,
        )
        assert resp.has_more is True


# === FileInfoResponse tests ===


class TestFileInfoResponse:
    """Tests for the FileInfoResponse model."""

    def test_create_response(self) -> None:
        resp = FileInfoResponse(
            path="/sandbox/data.csv",
            backend="local",
            name="data.csv",
            type="file",
            size_bytes=1048576,
            mime_type="text/csv",
            modified_at=datetime(2025, 1, 1, tzinfo=UTC),
            permissions="rw-r--r--",
        )
        assert resp.size_pretty == "1 MB"
        assert resp.mime_type == "text/csv"

    def test_size_pretty_computed(self) -> None:
        resp = FileInfoResponse(
            path="/test",
            backend="local",
            name="test",
            type="file",
            size_bytes=1536,
        )
        assert resp.size_pretty == "1.5 KB"


# === ReadFileResponse tests ===


class TestReadFileResponse:
    """Tests for the ReadFileResponse model."""

    def test_text_response(self) -> None:
        resp = ReadFileResponse(
            path="/sandbox/readme.md",
            backend="local",
            content="# Hello World",
            encoding="text",
            mime_type="text/markdown",
            size_bytes=13,
            bytes_read=13,
            offset=0,
            has_more=False,
            is_truncated=False,
        )
        assert resp.encoding == "text"
        assert resp.content == "# Hello World"

    def test_base64_response(self) -> None:
        resp = ReadFileResponse(
            path="/sandbox/image.png",
            backend="local",
            content="iVBORw0KGgoAAAANS...",
            encoding="base64",
            mime_type="image/png",
            size_bytes=50000,
            bytes_read=50000,
            has_more=False,
            is_truncated=False,
        )
        assert resp.encoding == "base64"

    def test_chunked_response(self) -> None:
        resp = ReadFileResponse(
            path="/sandbox/large.log",
            backend="local",
            content="partial content...",
            encoding="text",
            size_bytes=1000000,
            bytes_read=4096,
            offset=8192,
            has_more=True,
            is_truncated=False,
        )
        assert resp.offset == 8192
        assert resp.has_more is True

    def test_invalid_encoding_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReadFileResponse(
                path="/test",
                backend="local",
                content="data",
                encoding="utf-16",  # type: ignore[arg-type]
                size_bytes=4,
                bytes_read=4,
                has_more=False,
                is_truncated=False,
            )


# === SearchResponse tests ===


class TestSearchResponse:
    """Tests for the SearchResponse model."""

    def test_create_response(self) -> None:
        resp = SearchResponse(
            path="/sandbox",
            backend="local",
            results=[
                SearchResult(
                    path="/sandbox/main.py",
                    name="main.py",
                    type="file",
                    size_bytes=512,
                    match_context="import os",
                ),
            ],
            total_matches=1,
            search_truncated=False,
            directories_searched=5,
        )
        assert len(resp.results) == 1
        assert resp.directories_searched == 5

    def test_empty_results(self) -> None:
        resp = SearchResponse(
            path="/sandbox",
            backend="local",
            results=[],
            total_matches=0,
            search_truncated=False,
            directories_searched=10,
        )
        assert resp.results == []
        assert resp.total_matches == 0


# === S3 Extra Response tests ===


class TestListBucketsResponse:
    """Tests for the ListBucketsResponse model."""

    def test_create_response(self) -> None:
        resp = ListBucketsResponse(
            buckets=[
                BucketInfo(name="bucket-a", region="us-east-1"),
                BucketInfo(name="bucket-b", region="eu-west-1"),
            ],
            total_count=2,
        )
        assert len(resp.buckets) == 2
        assert resp.total_count == 2

    def test_empty_buckets(self) -> None:
        resp = ListBucketsResponse(buckets=[], total_count=0)
        assert resp.buckets == []


class TestPresignedUrlResponse:
    """Tests for the PresignedUrlResponse model."""

    def test_download_url(self) -> None:
        resp = PresignedUrlResponse(
            url="https://s3.amazonaws.com/bucket/key?Signature=abc",
            path="s3://bucket/key",
            operation="download",
            expires_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        assert resp.operation == "download"

    def test_upload_url(self) -> None:
        resp = PresignedUrlResponse(
            url="https://s3.amazonaws.com/bucket/key?Signature=xyz",
            path="s3://bucket/key",
            operation="upload",
            expires_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        assert resp.operation == "upload"

    def test_invalid_operation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PresignedUrlResponse(
                url="https://example.com",
                path="s3://bucket/key",
                operation="delete",  # type: ignore[arg-type]
                expires_at=datetime(2025, 12, 31, tzinfo=UTC),
            )


class TestObjectMetadataResponse:
    """Tests for the ObjectMetadataResponse model."""

    def test_full_metadata(self) -> None:
        resp = ObjectMetadataResponse(
            path="s3://bucket/data.json",
            storage_class="STANDARD",
            etag='"abc123"',
            version_id="v1",
            tags={"env": "prod", "team": "data"},
            server_side_encryption="AES256",
            content_type="application/json",
            last_modified=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        )
        assert resp.storage_class == "STANDARD"
        assert resp.tags == {"env": "prod", "team": "data"}

    def test_minimal_metadata(self) -> None:
        resp = ObjectMetadataResponse(
            path="s3://bucket/file.txt",
            storage_class="GLACIER",
            etag='"xyz789"',
            content_type="text/plain",
            last_modified=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert resp.version_id is None
        assert resp.tags is None
        assert resp.versions is None
        assert resp.server_side_encryption is None


# === Mutation Response tests ===


class TestWriteFileResponse:
    """Tests for the WriteFileResponse model."""

    def test_new_file(self) -> None:
        resp = WriteFileResponse(
            path="/sandbox/new.txt",
            backend="local",
            size_bytes=256,
            created=True,
        )
        assert resp.created is True

    def test_overwrite(self) -> None:
        resp = WriteFileResponse(
            path="/sandbox/existing.txt",
            backend="local",
            size_bytes=512,
            created=False,
        )
        assert resp.created is False


class TestDeleteFileResponse:
    """Tests for the DeleteFileResponse model."""

    def test_delete_response(self) -> None:
        resp = DeleteFileResponse(
            path="/sandbox/old.txt",
            backend="local",
            deleted=True,
        )
        assert resp.deleted is True


class TestMoveFileResponse:
    """Tests for the MoveFileResponse model."""

    def test_move_response(self) -> None:
        resp = MoveFileResponse(
            source="/sandbox/old-name.txt",
            destination="/sandbox/new-name.txt",
            backend="local",
            overwritten=False,
        )
        assert resp.source == "/sandbox/old-name.txt"
        assert resp.destination == "/sandbox/new-name.txt"
        assert resp.overwritten is False


class TestCopyFileResponse:
    """Tests for the CopyFileResponse model."""

    def test_same_backend_copy(self) -> None:
        resp = CopyFileResponse(
            source="/sandbox/src.txt",
            destination="/sandbox/dst.txt",
            source_backend="local",
            dest_backend="local",
            size_bytes=1024,
            cross_backend=False,
        )
        assert resp.cross_backend is False

    def test_cross_backend_copy(self) -> None:
        resp = CopyFileResponse(
            source="/sandbox/local.txt",
            destination="s3://bucket/remote.txt",
            source_backend="local",
            dest_backend="s3",
            size_bytes=2048,
            cross_backend=True,
        )
        assert resp.cross_backend is True
        assert resp.source_backend == "local"
        assert resp.dest_backend == "s3"


class TestCreateDirectoryResponse:
    """Tests for the CreateDirectoryResponse model."""

    def test_new_directory(self) -> None:
        resp = CreateDirectoryResponse(
            path="/sandbox/new-dir",
            backend="local",
            created=True,
        )
        assert resp.created is True

    def test_existing_directory(self) -> None:
        resp = CreateDirectoryResponse(
            path="/sandbox/existing-dir",
            backend="local",
            created=False,
        )
        assert resp.created is False


# === JSON Serialization / Deserialization Round-Trip ===


class TestJsonRoundTrip:
    """Tests for JSON serialization and deserialization of all models."""

    def test_file_entry_round_trip(self) -> None:
        original = FileEntry(
            name="test.py",
            path="/sandbox/test.py",
            type="file",
            size_bytes=2048,
            modified_at=datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC),
            is_hidden=False,
        )
        json_str = original.model_dump_json()
        restored = FileEntry.model_validate_json(json_str)
        assert restored == original

    def test_file_info_round_trip(self) -> None:
        original = FileInfo(
            name="data.csv",
            path="/sandbox/data.csv",
            type="file",
            size_bytes=1048576,
            modified_at=datetime(2025, 1, 1, tzinfo=UTC),
            created_at=datetime(2024, 12, 1, tzinfo=UTC),
            mime_type="text/csv",
            is_symlink=False,
            permissions="rw-r--r--",
            checksum="sha256hash",
        )
        json_str = original.model_dump_json()
        restored = FileInfo.model_validate_json(json_str)
        assert restored == original
        assert restored.size_pretty == "1 MB"

    def test_search_result_round_trip(self) -> None:
        original = SearchResult(
            path="/sandbox/main.py",
            name="main.py",
            type="file",
            size_bytes=512,
            match_context="import os\nimport sys",
        )
        json_str = original.model_dump_json()
        restored = SearchResult.model_validate_json(json_str)
        assert restored == original

    def test_bucket_info_round_trip(self) -> None:
        original = BucketInfo(
            name="test-bucket",
            creation_date=datetime(2024, 1, 1, tzinfo=UTC),
            region="us-east-1",
        )
        json_str = original.model_dump_json()
        restored = BucketInfo.model_validate_json(json_str)
        assert restored == original

    def test_list_directory_response_round_trip(self) -> None:
        original = ListDirectoryResponse(
            path="/sandbox",
            backend="local",
            entries=[
                FileEntry(name="a.txt", path="/sandbox/a.txt", type="file", size_bytes=10),
            ],
            total_count=1,
            has_more=False,
        )
        json_str = original.model_dump_json()
        restored = ListDirectoryResponse.model_validate_json(json_str)
        assert restored == original

    def test_file_info_response_round_trip(self) -> None:
        original = FileInfoResponse(
            path="/sandbox/test.txt",
            backend="local",
            name="test.txt",
            type="file",
            size_bytes=4096,
            mime_type="text/plain",
        )
        json_str = original.model_dump_json()
        restored = FileInfoResponse.model_validate_json(json_str)
        assert restored == original

    def test_read_file_response_round_trip(self) -> None:
        original = ReadFileResponse(
            path="/sandbox/readme.md",
            backend="local",
            content="# README",
            encoding="text",
            mime_type="text/markdown",
            size_bytes=8,
            bytes_read=8,
            offset=0,
            has_more=False,
            is_truncated=False,
        )
        json_str = original.model_dump_json()
        restored = ReadFileResponse.model_validate_json(json_str)
        assert restored == original

    def test_search_response_round_trip(self) -> None:
        original = SearchResponse(
            path="/sandbox",
            backend="local",
            results=[],
            total_matches=0,
            search_truncated=False,
            directories_searched=3,
        )
        json_str = original.model_dump_json()
        restored = SearchResponse.model_validate_json(json_str)
        assert restored == original

    def test_presigned_url_response_round_trip(self) -> None:
        original = PresignedUrlResponse(
            url="https://s3.amazonaws.com/bucket/key",
            path="s3://bucket/key",
            operation="download",
            expires_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        json_str = original.model_dump_json()
        restored = PresignedUrlResponse.model_validate_json(json_str)
        assert restored == original

    def test_object_metadata_response_round_trip(self) -> None:
        original = ObjectMetadataResponse(
            path="s3://bucket/key",
            storage_class="STANDARD",
            etag='"abc"',
            tags={"key": "value"},
            content_type="text/plain",
            last_modified=datetime(2025, 6, 1, tzinfo=UTC),
        )
        json_str = original.model_dump_json()
        restored = ObjectMetadataResponse.model_validate_json(json_str)
        assert restored == original

    def test_write_file_response_round_trip(self) -> None:
        original = WriteFileResponse(
            path="/sandbox/out.txt",
            backend="local",
            size_bytes=128,
            created=True,
        )
        json_str = original.model_dump_json()
        restored = WriteFileResponse.model_validate_json(json_str)
        assert restored == original

    def test_copy_file_response_round_trip(self) -> None:
        original = CopyFileResponse(
            source="/sandbox/src.txt",
            destination="s3://bucket/dst.txt",
            source_backend="local",
            dest_backend="s3",
            size_bytes=512,
            cross_backend=True,
        )
        json_str = original.model_dump_json()
        restored = CopyFileResponse.model_validate_json(json_str)
        assert restored == original

    def test_move_file_response_round_trip(self) -> None:
        original = MoveFileResponse(
            source="/sandbox/old.txt",
            destination="/sandbox/new.txt",
            backend="local",
            overwritten=False,
        )
        json_str = original.model_dump_json()
        restored = MoveFileResponse.model_validate_json(json_str)
        assert restored == original

    def test_delete_file_response_round_trip(self) -> None:
        original = DeleteFileResponse(
            path="/sandbox/gone.txt",
            backend="local",
            deleted=True,
        )
        json_str = original.model_dump_json()
        restored = DeleteFileResponse.model_validate_json(json_str)
        assert restored == original

    def test_create_directory_response_round_trip(self) -> None:
        original = CreateDirectoryResponse(
            path="/sandbox/new-dir",
            backend="local",
            created=True,
        )
        json_str = original.model_dump_json()
        restored = CreateDirectoryResponse.model_validate_json(json_str)
        assert restored == original

    def test_list_buckets_response_round_trip(self) -> None:
        original = ListBucketsResponse(
            buckets=[BucketInfo(name="b1"), BucketInfo(name="b2", region="eu-west-1")],
            total_count=2,
        )
        json_str = original.model_dump_json()
        restored = ListBucketsResponse.model_validate_json(json_str)
        assert restored == original


# === Edge Case and Validation tests ===


class TestEdgeCases:
    """Tests for edge cases: None handling, datetime formats, validation."""

    def test_all_optional_fields_none(self) -> None:
        """FileEntry optional fields default to None cleanly."""
        entry = FileEntry(
            name="test",
            path="/test",
            type="file",
        )
        assert entry.size_bytes is None
        assert entry.modified_at is None

    def test_file_info_all_optional_none(self) -> None:
        """FileInfo optional fields all default to None."""
        info = FileInfo(
            name="test",
            path="/test",
            type="file",
        )
        assert info.size_bytes is None
        assert info.modified_at is None
        assert info.mime_type is None
        assert info.created_at is None
        assert info.permissions is None
        assert info.checksum is None
        assert info.is_symlink is False
        assert info.is_hidden is False

    def test_datetime_iso8601_parsing(self) -> None:
        """Models accept ISO 8601 datetime strings via JSON."""
        json_str = (
            '{"name": "f", "path": "/f", "type": "file", "modified_at": "2025-06-15T10:30:00Z"}'
        )
        entry = FileEntry.model_validate_json(json_str)
        assert entry.modified_at is not None
        assert entry.modified_at.year == 2025
        assert entry.modified_at.month == 6
        assert entry.modified_at.day == 15

    def test_datetime_iso8601_with_offset(self) -> None:
        """Models accept ISO 8601 strings with timezone offsets."""
        json_str = (
            '{"name": "f", "path": "/f", "type": "file",'
            ' "modified_at": "2025-06-15T10:30:00+05:30"}'
        )
        entry = FileEntry.model_validate_json(json_str)
        assert entry.modified_at is not None

    def test_file_entry_null_datetime_in_json(self) -> None:
        """Null datetime in JSON is handled as None."""
        json_str = '{"name": "f", "path": "/f", "type": "file", "modified_at": null}'
        entry = FileEntry.model_validate_json(json_str)
        assert entry.modified_at is None

    def test_validation_rejects_wrong_type_for_path(self) -> None:
        """Non-string path is rejected by Pydantic validation."""
        with pytest.raises(ValidationError):
            FileEntry(
                name="test",
                path=123,  # type: ignore[arg-type]
                type="file",
            )

    def test_validation_rejects_wrong_type_for_bool(self) -> None:
        """Non-bool string for is_hidden is coerced or rejected appropriately."""
        # Pydantic v2 does coerce some values; integer 0/1 would coerce
        # But a random string should fail
        with pytest.raises(ValidationError):
            FileEntry.model_validate_json(
                '{"name": "f", "path": "/f", "type": "file", "is_hidden": "not_a_bool"}'
            )

    def test_file_info_size_pretty_in_json(self) -> None:
        """size_pretty computed field appears in JSON output."""
        info = FileInfo(
            name="big.bin",
            path="/big.bin",
            type="file",
            size_bytes=5368709120,  # 5 GB
        )
        data = info.model_dump()
        assert "size_pretty" in data
        assert data["size_pretty"] == "5 GB"

    def test_file_info_response_size_pretty_in_json(self) -> None:
        """FileInfoResponse size_pretty computed field appears in JSON output."""
        resp = FileInfoResponse(
            path="/test.txt",
            backend="local",
            name="test.txt",
            type="file",
            size_bytes=512,
        )
        data = resp.model_dump()
        assert "size_pretty" in data
        assert data["size_pretty"] == "512 B"

    def test_search_result_none_match_context_serializes(self) -> None:
        """None match_context serializes cleanly in JSON."""
        result = SearchResult(
            path="/f",
            name="f",
            type="file",
        )
        data = result.model_dump()
        assert data["match_context"] is None

    def test_object_metadata_versions_list(self) -> None:
        """versions field accepts a list of dicts."""
        resp = ObjectMetadataResponse(
            path="s3://bucket/key",
            storage_class="STANDARD",
            etag='"abc"',
            versions=[
                {"version_id": "v1", "last_modified": "2025-01-01T00:00:00Z", "is_latest": True},
                {"version_id": "v2", "last_modified": "2024-12-01T00:00:00Z", "is_latest": False},
            ],
            content_type="text/plain",
            last_modified=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert resp.versions is not None
        assert len(resp.versions) == 2
