"""Tests for the S3 backend implementation.

Covers:
- S3Backend initialization with s3fs (credentials, region, endpoint_url)
- BackendProtocol compliance
- All 11 methods delegating correctly to mocked s3fs filesystem
- S3 path parsing (_parse_s3_path, _to_s3_path)
- Entry normalization (_normalize_entry)
- Error mapping from S3 ClientError to BackendError/PathNotFoundError
- Credential errors producing clear messages
- Network/OS errors producing clear BACKEND_ERROR messages
- S3 virtual directory handling (prefix-based)
- Move implemented as copy + delete
- mkdir creates prefix placeholder object
- Edge cases: bucket root listing, special characters, empty paths
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from mamba_mcp_fs.backends.base import BackendProtocol
from mamba_mcp_fs.backends.s3 import (
    _DIR_PLACEHOLDER_SUFFIX,
    S3_SCHEME,
    S3Backend,
    _map_s3_error,
    _parse_s3_path,
    _to_s3_path,
)
from mamba_mcp_fs.config import S3Settings
from mamba_mcp_fs.errors import BackendError, PathNotFoundError

# ============================================================================
# Helpers
# ============================================================================


def _make_client_error(code: str, message: str = "test error") -> ClientError:
    """Create a botocore ClientError with the given error code and message."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="TestOperation",
    )


def _make_s3_settings(
    *,
    enabled: bool = True,
    bucket: str | None = "test-bucket",
    prefix: str = "",
    region: str = "us-east-1",
    endpoint_url: str | None = None,
) -> S3Settings:
    """Create S3Settings for testing."""
    return S3Settings(
        enabled=enabled,
        bucket=bucket,
        prefix=prefix,
        region=region,
        endpoint_url=endpoint_url,
    )


def _make_backend(settings: S3Settings | None = None) -> S3Backend:
    """Create an S3Backend with a mocked s3fs filesystem."""
    if settings is None:
        settings = _make_s3_settings()

    with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem"):
        backend = S3Backend(settings)

    # Replace the _fs with a fresh MagicMock for test control
    backend._fs = MagicMock()
    return backend


# ============================================================================
# TestS3PathParsing: _parse_s3_path and _to_s3_path utilities
# ============================================================================


class TestS3PathParsing:
    """Tests for S3 path parsing helper functions."""

    def test_parse_full_s3_url(self) -> None:
        """Parse s3://bucket/key/path format."""
        bucket, key = _parse_s3_path("s3://my-bucket/some/key/path.txt")
        assert bucket == "my-bucket"
        assert key == "some/key/path.txt"

    def test_parse_bucket_only_url(self) -> None:
        """Parse s3://bucket with no key."""
        bucket, key = _parse_s3_path("s3://my-bucket")
        assert bucket == "my-bucket"
        assert key == ""

    def test_parse_bucket_with_trailing_slash(self) -> None:
        """Parse s3://bucket/ with trailing slash."""
        bucket, key = _parse_s3_path("s3://my-bucket/")
        assert bucket == "my-bucket"
        assert key == ""

    def test_parse_without_scheme(self) -> None:
        """Parse bucket/key format without s3:// prefix."""
        bucket, key = _parse_s3_path("my-bucket/some/key.txt")
        assert bucket == "my-bucket"
        assert key == "some/key.txt"

    def test_parse_bucket_only_without_scheme(self) -> None:
        """Parse bare bucket name."""
        bucket, key = _parse_s3_path("my-bucket")
        assert bucket == "my-bucket"
        assert key == ""

    def test_parse_empty_string(self) -> None:
        """Empty string returns empty bucket and key."""
        bucket, key = _parse_s3_path("")
        assert bucket == ""
        assert key == ""

    def test_parse_just_scheme(self) -> None:
        """Just s3:// with no bucket returns empty."""
        bucket, key = _parse_s3_path("s3://")
        assert bucket == ""
        assert key == ""

    def test_parse_key_with_special_characters(self) -> None:
        """Keys with special characters should be preserved."""
        bucket, key = _parse_s3_path("s3://bucket/path/file with spaces.txt")
        assert bucket == "bucket"
        assert key == "path/file with spaces.txt"

    def test_parse_key_with_dots(self) -> None:
        """Keys with dots in various positions."""
        bucket, key = _parse_s3_path("bucket/path/to/.hidden/file.tar.gz")
        assert bucket == "bucket"
        assert key == "path/to/.hidden/file.tar.gz"

    def test_to_s3_path_with_key(self) -> None:
        """Construct bucket/key path."""
        result = _to_s3_path("my-bucket", "some/key.txt")
        assert result == "my-bucket/some/key.txt"

    def test_to_s3_path_bucket_only(self) -> None:
        """Construct bucket-only path when key is empty."""
        result = _to_s3_path("my-bucket", "")
        assert result == "my-bucket"


# ============================================================================
# TestS3BackendInit: Initialization and configuration
# ============================================================================


class TestS3BackendInit:
    """Tests for S3Backend initialization."""

    def test_init_with_region(self) -> None:
        """Backend passes region to s3fs client_kwargs."""
        settings = _make_s3_settings(region="eu-west-1")
        with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem") as mock_s3fs:
            S3Backend(settings)
            mock_s3fs.assert_called_once_with(
                anon=False,
                client_kwargs={"region_name": "eu-west-1"},
            )

    def test_init_with_endpoint_url(self) -> None:
        """Backend passes endpoint_url for MinIO/LocalStack."""
        settings = _make_s3_settings(
            region="us-east-1",
            endpoint_url="http://localhost:4566",
        )
        with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem") as mock_s3fs:
            S3Backend(settings)
            mock_s3fs.assert_called_once_with(
                anon=False,
                client_kwargs={
                    "region_name": "us-east-1",
                    "endpoint_url": "http://localhost:4566",
                },
            )

    def test_init_anon_false(self) -> None:
        """Backend always sets anon=False for authenticated access."""
        settings = _make_s3_settings()
        with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem") as mock_s3fs:
            S3Backend(settings)
            call_args = mock_s3fs.call_args
            assert call_args.kwargs["anon"] is False

    def test_settings_property(self) -> None:
        """Backend exposes settings via property."""
        settings = _make_s3_settings()
        backend = _make_backend(settings)
        assert backend.settings is settings

    def test_fs_property(self) -> None:
        """Backend exposes the s3fs filesystem via property."""
        backend = _make_backend()
        assert backend.fs is backend._fs


# ============================================================================
# TestBackendProtocolCompliance: S3Backend satisfies BackendProtocol
# ============================================================================


class TestBackendProtocolCompliance:
    """Tests that S3Backend satisfies the BackendProtocol."""

    def test_s3_backend_satisfies_protocol(self) -> None:
        """S3Backend should satisfy BackendProtocol at runtime."""
        backend = _make_backend()
        assert isinstance(backend, BackendProtocol)

    def test_s3_backend_has_all_methods(self) -> None:
        """S3Backend should implement all BackendProtocol methods."""
        expected = {
            "ls",
            "info",
            "cat_file",
            "pipe_file",
            "rm",
            "cp_file",
            "mv",
            "mkdir",
            "exists",
            "isdir",
            "isfile",
        }
        backend = _make_backend()
        for method_name in expected:
            assert hasattr(backend, method_name), f"Missing method: {method_name}"
            assert callable(getattr(backend, method_name))


# ============================================================================
# TestLs: ls() method
# ============================================================================


class TestLs:
    """Tests for S3Backend.ls() method."""

    def test_ls_with_detail(self) -> None:
        """ls with detail=True returns normalized entry dicts."""
        backend = _make_backend()
        backend._fs.ls.return_value = [
            {"name": "bucket/file.txt", "type": "file", "size": 100},
            {"name": "bucket/subdir", "type": "directory", "size": 0},
        ]

        result = backend.ls("bucket", detail=True)
        backend._fs.ls.assert_called_once_with("bucket", detail=True)
        assert len(result) == 2
        assert result[0]["name"] == "bucket/file.txt"
        assert result[0]["type"] == "file"
        assert result[0]["size"] == 100
        assert result[1]["type"] == "directory"

    def test_ls_without_detail(self) -> None:
        """ls with detail=False returns name-only dicts."""
        backend = _make_backend()
        backend._fs.ls.return_value = ["bucket/file.txt", "bucket/subdir"]

        result = backend.ls("bucket", detail=False)
        backend._fs.ls.assert_called_once_with("bucket", detail=False)
        assert result == [
            {"name": "bucket/file.txt"},
            {"name": "bucket/subdir"},
        ]

    def test_ls_empty_path(self) -> None:
        """ls with empty path lists top-level (buckets)."""
        backend = _make_backend()
        backend._fs.ls.return_value = []

        backend.ls("", detail=True)
        backend._fs.ls.assert_called_once_with("", detail=True)

    def test_ls_strips_slashes(self) -> None:
        """ls strips leading/trailing slashes from path."""
        backend = _make_backend()
        backend._fs.ls.return_value = []

        backend.ls("/bucket/prefix/", detail=True)
        backend._fs.ls.assert_called_once_with("bucket/prefix", detail=True)

    def test_ls_client_error_mapped(self) -> None:
        """ls maps ClientError to appropriate FSError."""
        backend = _make_backend()
        backend._fs.ls.side_effect = _make_client_error("NoSuchBucket", "Bucket not found")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.ls("nonexistent-bucket")

    def test_ls_credential_error(self) -> None:
        """ls maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.ls.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.ls("bucket")

    def test_ls_file_not_found(self) -> None:
        """ls maps FileNotFoundError to PathNotFoundError."""
        backend = _make_backend()
        backend._fs.ls.side_effect = FileNotFoundError("not found")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.ls("bucket/nonexistent")

    def test_ls_os_error(self) -> None:
        """ls maps OSError to BackendError."""
        backend = _make_backend()
        backend._fs.ls.side_effect = OSError("network timeout")

        with pytest.raises(BackendError, match="S3 operation failed"):
            backend.ls("bucket")


# ============================================================================
# TestInfo: info() method
# ============================================================================


class TestInfo:
    """Tests for S3Backend.info() method."""

    def test_info_returns_normalized_entry(self) -> None:
        """info returns a normalized metadata dict."""
        backend = _make_backend()
        backend._fs.info.return_value = {
            "name": "bucket/file.txt",
            "type": "file",
            "size": 1024,
            "ContentType": "text/plain",
            "LastModified": "2025-01-01T00:00:00Z",
            "ETag": '"abc123"',
        }

        result = backend.info("bucket/file.txt")
        backend._fs.info.assert_called_once_with("bucket/file.txt")
        assert result["name"] == "bucket/file.txt"
        assert result["type"] == "file"
        assert result["size"] == 1024
        assert result["mime_type"] == "text/plain"
        assert result["last_modified"] == "2025-01-01T00:00:00Z"
        assert result["etag"] == '"abc123"'

    def test_info_directory_type(self) -> None:
        """info for a directory returns type='directory'."""
        backend = _make_backend()
        backend._fs.info.return_value = {
            "name": "bucket/prefix",
            "type": "directory",
            "size": 0,
        }

        result = backend.info("bucket/prefix")
        assert result["type"] == "directory"
        assert result["size"] == 0

    def test_info_not_found(self) -> None:
        """info for nonexistent object raises PathNotFoundError."""
        backend = _make_backend()
        backend._fs.info.side_effect = FileNotFoundError("not found")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.info("bucket/nonexistent.txt")

    def test_info_client_error(self) -> None:
        """info maps ClientError to appropriate error."""
        backend = _make_backend()
        backend._fs.info.side_effect = _make_client_error("NoSuchKey")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.info("bucket/missing.txt")


# ============================================================================
# TestCatFile: cat_file() method
# ============================================================================


class TestCatFile:
    """Tests for S3Backend.cat_file() method."""

    def test_cat_file_full_read(self) -> None:
        """cat_file reads entire object."""
        backend = _make_backend()
        backend._fs.cat_file.return_value = b"hello world"

        result = backend.cat_file("bucket/file.txt")
        backend._fs.cat_file.assert_called_once_with("bucket/file.txt", start=None, end=None)
        assert result == b"hello world"

    def test_cat_file_byte_range(self) -> None:
        """cat_file supports start/end byte range."""
        backend = _make_backend()
        backend._fs.cat_file.return_value = b"world"

        result = backend.cat_file("bucket/file.txt", start=6, end=11)
        backend._fs.cat_file.assert_called_once_with("bucket/file.txt", start=6, end=11)
        assert result == b"world"

    def test_cat_file_start_only(self) -> None:
        """cat_file with start only."""
        backend = _make_backend()
        backend._fs.cat_file.return_value = b"world"

        backend.cat_file("bucket/file.txt", start=6)
        backend._fs.cat_file.assert_called_once_with("bucket/file.txt", start=6, end=None)

    def test_cat_file_not_found(self) -> None:
        """cat_file for nonexistent object raises PathNotFoundError."""
        backend = _make_backend()
        backend._fs.cat_file.side_effect = _make_client_error("NoSuchKey")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.cat_file("bucket/missing.txt")

    def test_cat_file_credential_error(self) -> None:
        """cat_file credential error gives helpful message."""
        backend = _make_backend()
        backend._fs.cat_file.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.cat_file("bucket/file.txt")


# ============================================================================
# TestPipeFile: pipe_file() method
# ============================================================================


class TestPipeFile:
    """Tests for S3Backend.pipe_file() method."""

    def test_pipe_file_upload(self) -> None:
        """pipe_file uploads data to S3."""
        backend = _make_backend()
        data = b"hello S3"

        backend.pipe_file("bucket/file.txt", data)
        backend._fs.pipe_file.assert_called_once_with("bucket/file.txt", data)

    def test_pipe_file_empty_data(self) -> None:
        """pipe_file uploads empty bytes."""
        backend = _make_backend()

        backend.pipe_file("bucket/empty.txt", b"")
        backend._fs.pipe_file.assert_called_once_with("bucket/empty.txt", b"")

    def test_pipe_file_client_error(self) -> None:
        """pipe_file maps ClientError to BackendError."""
        backend = _make_backend()
        backend._fs.pipe_file.side_effect = _make_client_error("AccessDenied")

        with pytest.raises(BackendError, match="access denied"):
            backend.pipe_file("bucket/file.txt", b"data")

    def test_pipe_file_credential_error(self) -> None:
        """pipe_file credential error gives helpful message."""
        backend = _make_backend()
        backend._fs.pipe_file.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.pipe_file("bucket/file.txt", b"data")


# ============================================================================
# TestRm: rm() method
# ============================================================================


class TestRm:
    """Tests for S3Backend.rm() method."""

    def test_rm_deletes_object(self) -> None:
        """rm delegates to s3fs.rm."""
        backend = _make_backend()

        backend.rm("bucket/file.txt")
        backend._fs.rm.assert_called_once_with("bucket/file.txt")

    def test_rm_not_found(self) -> None:
        """rm for nonexistent object raises PathNotFoundError."""
        backend = _make_backend()
        backend._fs.rm.side_effect = FileNotFoundError("not found")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.rm("bucket/missing.txt")

    def test_rm_client_error(self) -> None:
        """rm maps ClientError to appropriate error."""
        backend = _make_backend()
        backend._fs.rm.side_effect = _make_client_error("AccessDenied")

        with pytest.raises(BackendError, match="access denied"):
            backend.rm("bucket/file.txt")


# ============================================================================
# TestCpFile: cp_file() method
# ============================================================================


class TestCpFile:
    """Tests for S3Backend.cp_file() method."""

    def test_cp_file_copies(self) -> None:
        """cp_file delegates to s3fs.cp_file."""
        backend = _make_backend()

        backend.cp_file("bucket/source.txt", "bucket/dest.txt")
        backend._fs.cp_file.assert_called_once_with("bucket/source.txt", "bucket/dest.txt")

    def test_cp_file_cross_bucket(self) -> None:
        """cp_file works across buckets."""
        backend = _make_backend()

        backend.cp_file("bucket-a/file.txt", "bucket-b/file.txt")
        backend._fs.cp_file.assert_called_once_with("bucket-a/file.txt", "bucket-b/file.txt")

    def test_cp_file_not_found(self) -> None:
        """cp_file for nonexistent source raises PathNotFoundError."""
        backend = _make_backend()
        backend._fs.cp_file.side_effect = FileNotFoundError("not found")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.cp_file("bucket/missing.txt", "bucket/dest.txt")

    def test_cp_file_client_error(self) -> None:
        """cp_file maps ClientError to appropriate error."""
        backend = _make_backend()
        backend._fs.cp_file.side_effect = _make_client_error("403", "Forbidden")

        with pytest.raises(BackendError, match="access denied"):
            backend.cp_file("bucket/file.txt", "bucket/dest.txt")


# ============================================================================
# TestMv: mv() method (copy + delete)
# ============================================================================


class TestMv:
    """Tests for S3Backend.mv() method (copy + delete)."""

    def test_mv_copies_then_deletes(self) -> None:
        """mv calls cp_file then rm (copy + delete pattern)."""
        backend = _make_backend()

        backend.mv("bucket/old.txt", "bucket/new.txt")

        # Verify copy was called
        backend._fs.cp_file.assert_called_once_with("bucket/old.txt", "bucket/new.txt")
        # Verify delete was called
        backend._fs.rm.assert_called_once_with("bucket/old.txt")

    def test_mv_copy_failure_does_not_delete(self) -> None:
        """If copy fails, delete should not be called."""
        backend = _make_backend()
        backend._fs.cp_file.side_effect = _make_client_error("NoSuchKey")

        with pytest.raises(PathNotFoundError):
            backend.mv("bucket/missing.txt", "bucket/new.txt")

        # rm should NOT have been called since copy failed
        backend._fs.rm.assert_not_called()

    def test_mv_delete_failure_after_copy(self) -> None:
        """If delete fails after copy, the error propagates."""
        backend = _make_backend()
        backend._fs.rm.side_effect = _make_client_error("AccessDenied")

        with pytest.raises(BackendError, match="access denied"):
            backend.mv("bucket/old.txt", "bucket/new.txt")

        # Copy should have succeeded
        backend._fs.cp_file.assert_called_once()


# ============================================================================
# TestMkdir: mkdir() method (prefix placeholder)
# ============================================================================


class TestMkdir:
    """Tests for S3Backend.mkdir() method."""

    def test_mkdir_creates_placeholder(self) -> None:
        """mkdir creates an empty object with trailing / suffix."""
        backend = _make_backend()

        backend.mkdir("bucket/new-dir")
        backend._fs.pipe_file.assert_called_once_with("bucket/new-dir/", b"")

    def test_mkdir_with_trailing_slash(self) -> None:
        """mkdir strips trailing slash before adding placeholder suffix."""
        backend = _make_backend()

        backend.mkdir("bucket/new-dir/")
        # Stripped to "bucket/new-dir", then appended "/"
        backend._fs.pipe_file.assert_called_once_with("bucket/new-dir/", b"")

    def test_mkdir_create_parents_ignored(self) -> None:
        """create_parents parameter is ignored for S3 (prefixes are implicit)."""
        backend = _make_backend()

        backend.mkdir("bucket/a/b/c", create_parents=False)
        backend._fs.pipe_file.assert_called_once_with("bucket/a/b/c/", b"")

    def test_mkdir_empty_path_noop(self) -> None:
        """mkdir with empty path is a no-op."""
        backend = _make_backend()

        backend.mkdir("")
        backend._fs.pipe_file.assert_not_called()

    def test_mkdir_client_error(self) -> None:
        """mkdir maps ClientError to BackendError."""
        backend = _make_backend()
        backend._fs.pipe_file.side_effect = _make_client_error("AccessDenied")

        with pytest.raises(BackendError, match="access denied"):
            backend.mkdir("bucket/new-dir")


# ============================================================================
# TestExists: exists() method
# ============================================================================


class TestExists:
    """Tests for S3Backend.exists() method."""

    def test_exists_true(self) -> None:
        """exists returns True for existing object."""
        backend = _make_backend()
        backend._fs.exists.return_value = True

        assert backend.exists("bucket/file.txt") is True
        backend._fs.exists.assert_called_once_with("bucket/file.txt")

    def test_exists_false(self) -> None:
        """exists returns False for nonexistent object."""
        backend = _make_backend()
        backend._fs.exists.return_value = False

        assert backend.exists("bucket/missing.txt") is False

    def test_exists_empty_path(self) -> None:
        """exists with empty path delegates to s3fs."""
        backend = _make_backend()
        backend._fs.exists.return_value = True

        backend.exists("")
        backend._fs.exists.assert_called_once_with("")

    def test_exists_client_error(self) -> None:
        """exists maps ClientError to BackendError."""
        backend = _make_backend()
        backend._fs.exists.side_effect = _make_client_error("500", "Internal")

        with pytest.raises(BackendError, match="S3 error"):
            backend.exists("bucket/file.txt")


# ============================================================================
# TestIsdir: isdir() method
# ============================================================================


class TestIsdir:
    """Tests for S3Backend.isdir() method."""

    def test_isdir_true(self) -> None:
        """isdir returns True for a directory prefix."""
        backend = _make_backend()
        backend._fs.isdir.return_value = True

        assert backend.isdir("bucket/prefix") is True
        backend._fs.isdir.assert_called_once_with("bucket/prefix")

    def test_isdir_false(self) -> None:
        """isdir returns False for a file object."""
        backend = _make_backend()
        backend._fs.isdir.return_value = False

        assert backend.isdir("bucket/file.txt") is False

    def test_isdir_empty_path_returns_true(self) -> None:
        """isdir with empty path returns True (root is always a directory)."""
        backend = _make_backend()

        assert backend.isdir("") is True
        # Should not call s3fs since we short-circuit
        backend._fs.isdir.assert_not_called()

    def test_isdir_client_error(self) -> None:
        """isdir maps ClientError to BackendError."""
        backend = _make_backend()
        backend._fs.isdir.side_effect = _make_client_error("500", "Internal")

        with pytest.raises(BackendError, match="S3 error"):
            backend.isdir("bucket/prefix")


# ============================================================================
# TestIsfile: isfile() method
# ============================================================================


class TestIsfile:
    """Tests for S3Backend.isfile() method."""

    def test_isfile_true(self) -> None:
        """isfile returns True for a file object."""
        backend = _make_backend()
        backend._fs.isfile.return_value = True

        assert backend.isfile("bucket/file.txt") is True
        backend._fs.isfile.assert_called_once_with("bucket/file.txt")

    def test_isfile_false(self) -> None:
        """isfile returns False for a directory prefix."""
        backend = _make_backend()
        backend._fs.isfile.return_value = False

        assert backend.isfile("bucket/prefix") is False

    def test_isfile_empty_path_returns_false(self) -> None:
        """isfile with empty path returns False (root is not a file)."""
        backend = _make_backend()

        assert backend.isfile("") is False
        # Should not call s3fs since we short-circuit
        backend._fs.isfile.assert_not_called()

    def test_isfile_client_error(self) -> None:
        """isfile maps ClientError to BackendError."""
        backend = _make_backend()
        backend._fs.isfile.side_effect = _make_client_error("500", "Internal")

        with pytest.raises(BackendError, match="S3 error"):
            backend.isfile("bucket/file.txt")


# ============================================================================
# TestNormalizeEntry: _normalize_entry metadata mapping
# ============================================================================


class TestNormalizeEntry:
    """Tests for S3Backend._normalize_entry metadata normalization."""

    def test_normalize_basic_file(self) -> None:
        """Basic file entry with name, type, size."""
        backend = _make_backend()
        entry = {"name": "bucket/file.txt", "type": "file", "size": 512}

        result = backend._normalize_entry(entry)
        assert result["name"] == "bucket/file.txt"
        assert result["type"] == "file"
        assert result["size"] == 512

    def test_normalize_directory(self) -> None:
        """Directory entry has type='directory' and size=0."""
        backend = _make_backend()
        entry = {"name": "bucket/prefix", "type": "directory", "size": 0}

        result = backend._normalize_entry(entry)
        assert result["type"] == "directory"
        assert result["size"] == 0

    def test_normalize_content_type_mapped(self) -> None:
        """ContentType is mapped to mime_type."""
        backend = _make_backend()
        entry = {
            "name": "bucket/file.txt",
            "type": "file",
            "size": 100,
            "ContentType": "text/plain",
        }

        result = backend._normalize_entry(entry)
        assert result["mime_type"] == "text/plain"

    def test_normalize_last_modified(self) -> None:
        """LastModified is preserved."""
        backend = _make_backend()
        entry = {
            "name": "bucket/file.txt",
            "type": "file",
            "size": 100,
            "LastModified": "2025-01-01T00:00:00Z",
        }

        result = backend._normalize_entry(entry)
        assert result["last_modified"] == "2025-01-01T00:00:00Z"

    def test_normalize_etag(self) -> None:
        """ETag is preserved."""
        backend = _make_backend()
        entry = {
            "name": "bucket/file.txt",
            "type": "file",
            "size": 100,
            "ETag": '"abc123"',
        }

        result = backend._normalize_entry(entry)
        assert result["etag"] == '"abc123"'

    def test_normalize_storage_class(self) -> None:
        """StorageClass is preserved."""
        backend = _make_backend()
        entry = {
            "name": "bucket/file.txt",
            "type": "file",
            "size": 100,
            "StorageClass": "STANDARD",
        }

        result = backend._normalize_entry(entry)
        assert result["storage_class"] == "STANDARD"

    def test_normalize_version_id(self) -> None:
        """VersionId is preserved."""
        backend = _make_backend()
        entry = {
            "name": "bucket/file.txt",
            "type": "file",
            "size": 100,
            "VersionId": "v1",
        }

        result = backend._normalize_entry(entry)
        assert result["version_id"] == "v1"

    def test_normalize_missing_size_defaults_to_zero(self) -> None:
        """Missing size defaults to 0."""
        backend = _make_backend()
        entry = {"name": "bucket/dir", "type": "directory"}

        result = backend._normalize_entry(entry)
        assert result["size"] == 0

    def test_normalize_none_size_defaults_to_zero(self) -> None:
        """None size defaults to 0."""
        backend = _make_backend()
        entry = {"name": "bucket/dir", "type": "directory", "size": None}

        result = backend._normalize_entry(entry)
        assert result["size"] == 0

    def test_normalize_uses_key_fallback(self) -> None:
        """Uses 'Key' if 'name' is not present."""
        backend = _make_backend()
        entry = {"Key": "bucket/file.txt", "type": "file", "Size": 100}

        result = backend._normalize_entry(entry)
        assert result["name"] == "bucket/file.txt"
        assert result["size"] == 100

    def test_normalize_optional_fields_absent(self) -> None:
        """Optional fields (mime_type, etag, etc.) are omitted when not in source."""
        backend = _make_backend()
        entry = {"name": "bucket/file.txt", "type": "file", "size": 50}

        result = backend._normalize_entry(entry)
        assert "mime_type" not in result
        assert "last_modified" not in result
        assert "etag" not in result
        assert "storage_class" not in result
        assert "version_id" not in result

    def test_normalize_full_metadata(self) -> None:
        """Full metadata entry with all fields mapped."""
        backend = _make_backend()
        entry = {
            "name": "bucket/report.pdf",
            "type": "file",
            "size": 204800,
            "ContentType": "application/pdf",
            "LastModified": "2025-06-15T12:00:00Z",
            "ETag": '"def456"',
            "StorageClass": "GLACIER",
            "VersionId": "ver-2",
        }

        result = backend._normalize_entry(entry)
        assert result == {
            "name": "bucket/report.pdf",
            "type": "file",
            "size": 204800,
            "mime_type": "application/pdf",
            "last_modified": "2025-06-15T12:00:00Z",
            "etag": '"def456"',
            "storage_class": "GLACIER",
            "version_id": "ver-2",
        }


# ============================================================================
# TestErrorMapping: _map_s3_error function
# ============================================================================


class TestErrorMapping:
    """Tests for _map_s3_error error mapping from ClientError."""

    def test_404_maps_to_path_not_found(self) -> None:
        """404 error code maps to PathNotFoundError."""
        exc = _make_client_error("404", "Not Found")
        result = _map_s3_error(exc, "bucket/key")
        assert isinstance(result, PathNotFoundError)
        assert "S3 path not found" in result.message

    def test_no_such_key_maps_to_path_not_found(self) -> None:
        """NoSuchKey maps to PathNotFoundError."""
        exc = _make_client_error("NoSuchKey", "The specified key does not exist.")
        result = _map_s3_error(exc, "bucket/missing.txt")
        assert isinstance(result, PathNotFoundError)

    def test_no_such_bucket_maps_to_path_not_found(self) -> None:
        """NoSuchBucket maps to PathNotFoundError."""
        exc = _make_client_error("NoSuchBucket", "The specified bucket does not exist.")
        result = _map_s3_error(exc, "missing-bucket/key")
        assert isinstance(result, PathNotFoundError)

    def test_403_maps_to_backend_error_with_access_info(self) -> None:
        """403 error maps to BackendError with access denied message."""
        exc = _make_client_error("403", "Forbidden")
        result = _map_s3_error(exc, "bucket/key")
        assert isinstance(result, BackendError)
        assert "access denied" in result.message

    def test_access_denied_maps_to_backend_error(self) -> None:
        """AccessDenied maps to BackendError with IAM suggestion."""
        exc = _make_client_error("AccessDenied", "Access Denied")
        result = _map_s3_error(exc, "bucket/key")
        assert isinstance(result, BackendError)
        assert "IAM permissions" in result.message

    def test_unknown_error_maps_to_backend_error(self) -> None:
        """Unknown error codes map to generic BackendError."""
        exc = _make_client_error("InternalError", "Something went wrong")
        result = _map_s3_error(exc, "bucket/key")
        assert isinstance(result, BackendError)
        assert "InternalError" in result.message

    def test_500_maps_to_backend_error(self) -> None:
        """500 error maps to generic BackendError."""
        exc = _make_client_error("500", "Internal Server Error")
        result = _map_s3_error(exc, "bucket/key")
        assert isinstance(result, BackendError)
        assert not isinstance(result, PathNotFoundError)


# ============================================================================
# TestEdgeCases: Edge case handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge case handling in S3Backend."""

    def test_path_with_special_characters(self) -> None:
        """Paths with spaces and special chars are handled."""
        backend = _make_backend()
        backend._fs.info.return_value = {
            "name": "bucket/path/file with spaces (1).txt",
            "type": "file",
            "size": 100,
        }

        result = backend.info("bucket/path/file with spaces (1).txt")
        assert result["name"] == "bucket/path/file with spaces (1).txt"

    def test_path_with_unicode_characters(self) -> None:
        """Paths with unicode characters are handled."""
        backend = _make_backend()
        backend._fs.info.return_value = {
            "name": "bucket/data/resume.txt",
            "type": "file",
            "size": 50,
        }

        result = backend.info("bucket/data/resume.txt")
        assert result["name"] == "bucket/data/resume.txt"

    def test_bucket_root_listing(self) -> None:
        """Listing at bucket level (no prefix) works."""
        backend = _make_backend()
        backend._fs.ls.return_value = [
            {"name": "bucket/dir1", "type": "directory", "size": 0},
            {"name": "bucket/file.txt", "type": "file", "size": 100},
        ]

        result = backend.ls("bucket", detail=True)
        assert len(result) == 2

    def test_virtual_directory_no_objects(self) -> None:
        """S3 prefix with no objects returns empty list."""
        backend = _make_backend()
        backend._fs.ls.return_value = []

        result = backend.ls("bucket/empty-prefix", detail=True)
        assert result == []

    def test_path_with_leading_trailing_slashes(self) -> None:
        """Leading/trailing slashes are stripped from all operations."""
        backend = _make_backend()
        backend._fs.exists.return_value = True

        backend.exists("/bucket/key/")
        backend._fs.exists.assert_called_once_with("bucket/key")

    def test_cat_file_empty_returns_bytes(self) -> None:
        """cat_file for empty object returns empty bytes."""
        backend = _make_backend()
        backend._fs.cat_file.return_value = b""

        result = backend.cat_file("bucket/empty.txt")
        assert result == b""


# ============================================================================
# TestCustomEndpoint: MinIO/LocalStack endpoint support
# ============================================================================


class TestCustomEndpoint:
    """Tests for custom S3 endpoint URL configuration."""

    def test_localstack_endpoint(self) -> None:
        """LocalStack endpoint URL is passed to s3fs."""
        settings = _make_s3_settings(endpoint_url="http://localhost:4566")
        with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem") as mock_s3fs:
            S3Backend(settings)
            call_kwargs = mock_s3fs.call_args.kwargs
            assert call_kwargs["client_kwargs"]["endpoint_url"] == "http://localhost:4566"

    def test_minio_endpoint(self) -> None:
        """MinIO endpoint URL is passed to s3fs."""
        settings = _make_s3_settings(endpoint_url="http://minio:9000")
        with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem") as mock_s3fs:
            S3Backend(settings)
            call_kwargs = mock_s3fs.call_args.kwargs
            assert call_kwargs["client_kwargs"]["endpoint_url"] == "http://minio:9000"

    def test_no_endpoint_url_when_none(self) -> None:
        """When endpoint_url is None, it is not included in client_kwargs."""
        settings = _make_s3_settings(endpoint_url=None)
        with patch("mamba_mcp_fs.backends.s3.s3fs.S3FileSystem") as mock_s3fs:
            S3Backend(settings)
            call_kwargs = mock_s3fs.call_args.kwargs
            assert "endpoint_url" not in (call_kwargs.get("client_kwargs") or {})


# ============================================================================
# TestConstants: Module-level constants
# ============================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_s3_scheme(self) -> None:
        """S3_SCHEME should be 's3://'."""
        assert S3_SCHEME == "s3://"

    def test_dir_placeholder_suffix(self) -> None:
        """Directory placeholder suffix should be '/'."""
        assert _DIR_PLACEHOLDER_SUFFIX == "/"


# ============================================================================
# TestNetworkErrors: Network and timeout error handling
# ============================================================================


class TestNetworkErrors:
    """Tests for network-related error handling."""

    def test_os_error_on_ls(self) -> None:
        """OSError during ls is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.ls.side_effect = OSError("Connection timed out")

        with pytest.raises(BackendError, match="S3 operation failed"):
            backend.ls("bucket")

    def test_os_error_on_cat_file(self) -> None:
        """OSError during cat_file is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.cat_file.side_effect = OSError("Connection reset")

        with pytest.raises(BackendError, match="S3 operation failed"):
            backend.cat_file("bucket/file.txt")

    def test_os_error_on_pipe_file(self) -> None:
        """OSError during pipe_file is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.pipe_file.side_effect = OSError("Connection refused")

        with pytest.raises(BackendError, match="S3 upload failed"):
            backend.pipe_file("bucket/file.txt", b"data")

    def test_os_error_on_rm(self) -> None:
        """OSError during rm is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.rm.side_effect = OSError("timeout")

        with pytest.raises(BackendError, match="S3 delete failed"):
            backend.rm("bucket/file.txt")

    def test_os_error_on_cp_file(self) -> None:
        """OSError during cp_file is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.cp_file.side_effect = OSError("network error")

        with pytest.raises(BackendError, match="S3 copy failed"):
            backend.cp_file("bucket/a.txt", "bucket/b.txt")

    def test_os_error_on_mkdir(self) -> None:
        """OSError during mkdir is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.pipe_file.side_effect = OSError("timeout")

        with pytest.raises(BackendError, match="S3 mkdir failed"):
            backend.mkdir("bucket/dir")

    def test_os_error_on_exists(self) -> None:
        """OSError during exists is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.exists.side_effect = OSError("timeout")

        with pytest.raises(BackendError, match="S3 exists check failed"):
            backend.exists("bucket/file.txt")

    def test_os_error_on_isdir(self) -> None:
        """OSError during isdir is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.isdir.side_effect = OSError("timeout")

        with pytest.raises(BackendError, match="S3 isdir check failed"):
            backend.isdir("bucket/prefix")

    def test_os_error_on_isfile(self) -> None:
        """OSError during isfile is mapped to BackendError."""
        backend = _make_backend()
        backend._fs.isfile.side_effect = OSError("timeout")

        with pytest.raises(BackendError, match="S3 isfile check failed"):
            backend.isfile("bucket/file.txt")


# ============================================================================
# TestCredentialErrors: NoCredentialsError handling for all remaining methods
# ============================================================================


class TestCredentialErrors:
    """Tests for NoCredentialsError handling across all S3 methods.

    Complements the credential error tests in individual method test classes
    by covering methods that were missing NoCredentialsError test coverage:
    info, rm, cp_file, mkdir, exists, isdir, isfile.
    """

    def test_info_credential_error(self) -> None:
        """info maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.info.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.info("bucket/file.txt")

    def test_rm_credential_error(self) -> None:
        """rm maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.rm.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.rm("bucket/file.txt")

    def test_cp_file_credential_error(self) -> None:
        """cp_file maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.cp_file.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.cp_file("bucket/src.txt", "bucket/dst.txt")

    def test_mkdir_credential_error(self) -> None:
        """mkdir maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.pipe_file.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.mkdir("bucket/new-dir")

    def test_exists_credential_error(self) -> None:
        """exists maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.exists.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.exists("bucket/file.txt")

    def test_isdir_credential_error(self) -> None:
        """isdir maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.isdir.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.isdir("bucket/prefix")

    def test_isfile_credential_error(self) -> None:
        """isfile maps NoCredentialsError to BackendError with helpful message."""
        backend = _make_backend()
        backend._fs.isfile.side_effect = NoCredentialsError()

        with pytest.raises(BackendError, match="credentials not found"):
            backend.isfile("bucket/file.txt")


# ============================================================================
# TestInfoFileNotFoundAndOSError: Additional error paths for info()
# ============================================================================


class TestInfoFileNotFoundAndOSError:
    """Tests for FileNotFoundError and OSError handling in info()."""

    def test_info_file_not_found(self) -> None:
        """info maps FileNotFoundError to PathNotFoundError."""
        backend = _make_backend()
        backend._fs.info.side_effect = FileNotFoundError("not found")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.info("bucket/missing.txt")

    def test_info_os_error(self) -> None:
        """info maps OSError to BackendError."""
        backend = _make_backend()
        backend._fs.info.side_effect = OSError("connection refused")

        with pytest.raises(BackendError, match="S3 operation failed"):
            backend.info("bucket/file.txt")


# ============================================================================
# TestCatFileFileNotFound: FileNotFoundError handling in cat_file()
# ============================================================================


class TestCatFileFileNotFound:
    """Tests for FileNotFoundError handling in cat_file()."""

    def test_cat_file_file_not_found(self) -> None:
        """cat_file maps FileNotFoundError to PathNotFoundError."""
        backend = _make_backend()
        backend._fs.cat_file.side_effect = FileNotFoundError("no such file")

        with pytest.raises(PathNotFoundError, match="S3 path not found"):
            backend.cat_file("bucket/missing.txt")


# ============================================================================
# TestIntegration: Integration tests (skipped -- require real S3/LocalStack)
# ============================================================================


@pytest.mark.skip(reason="Requires LocalStack or real S3; no S3 service available in CI")
class TestIntegrationLocalStack:
    """Integration tests that require a real S3 service (LocalStack).

    These tests are skipped by default. To run them, set up LocalStack
    and remove the skip marker.
    """

    def test_list_buckets(self) -> None:
        """List available S3 buckets."""

    def test_put_and_get_object(self) -> None:
        """Upload an object and read it back."""

    def test_delete_object(self) -> None:
        """Delete an uploaded object."""

    def test_copy_object(self) -> None:
        """Copy an object within S3."""

    def test_move_object(self) -> None:
        """Move an object (copy + delete)."""

    def test_mkdir_creates_prefix_placeholder(self) -> None:
        """mkdir creates an empty placeholder object."""

    def test_exists_for_object_and_prefix(self) -> None:
        """exists returns correct values for objects and prefixes."""
