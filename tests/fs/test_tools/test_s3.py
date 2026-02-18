"""Tests for the S3 MCP tools (list_buckets, get_presigned_url, get_object_metadata).

Covers:
- Unit: Bucket listing with mocked S3 backend (multiple buckets)
- Unit: Empty bucket list (no accessible buckets)
- Unit: Many buckets (100+)
- Unit: Bucket with creation date and region
- Unit: Bucket with missing creation date
- Unit: Error handling for disabled S3 backend (BACKEND_NOT_CONFIGURED)
- Unit: Error handling for enabled but unregistered S3 backend
- Unit: Error handling for credential/connectivity issues (BACKEND_ERROR)
- Unit: Error handling for no context
- Unit: FSError handling with cause unwrapping
- Unit: Presigned URL generation for download and upload
- Unit: Presigned URL permission check for upload in read-only mode
- Unit: Presigned URL expiration time calculation and clamping
- Unit: Presigned URL error handling (non-existent path, disabled backend)
- Unit: Object metadata retrieval with mocked S3 client
- Unit: Object tag retrieval
- Unit: Object version listing
- Unit: Object metadata edge cases (no tags, no versioning, GLACIER)
- Unit: Object metadata error handling (not found, disabled backend)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from mamba_mcp_fs.backends.base import BackendManager
from mamba_mcp_fs.config import LocalSettings, S3Settings, ServerSettings, Settings
from mamba_mcp_fs.errors import BackendError, ErrorCode
from mamba_mcp_fs.models.files import BucketInfo
from mamba_mcp_fs.models.responses import (
    ListBucketsResponse,
    ObjectMetadataResponse,
    PresignedUrlResponse,
)
from mamba_mcp_fs.rate_limit import RateLimiter
from mamba_mcp_fs.security import SecurityValidator
from mamba_mcp_fs.server import AppContext
from mamba_mcp_fs.tools.s3_tools import get_object_metadata, get_presigned_url, list_buckets

# ============================================================================
# Helpers: Mock S3 backend, context, and test data
# ============================================================================


class MockS3Backend:
    """A mock S3 backend with a fake s3fs-like interface for testing."""

    def __init__(self) -> None:
        self._list_buckets_response: dict[str, Any] = {"Buckets": []}
        self._raise_on_list_buckets: Exception | None = None
        self._presigned_url: str = "https://s3.amazonaws.com/mock-presigned-url"
        self._raise_on_generate_presigned_url: Exception | None = None
        self._exists_map: dict[str, bool] = {}
        self._default_exists: bool = True
        # head_object mock state
        self._head_object_response: dict[str, Any] = {}
        self._raise_on_head_object: Exception | None = None
        # get_object_tagging mock state
        self._tagging_response: dict[str, Any] = {"TagSet": []}
        self._raise_on_get_object_tagging: Exception | None = None
        # list_object_versions mock state
        self._versions_response: dict[str, Any] = {"Versions": []}
        self._raise_on_list_object_versions: Exception | None = None

    def set_buckets(self, buckets: list[dict[str, Any]]) -> None:
        """Set the raw bucket list returned by list_buckets."""
        self._list_buckets_response = {"Buckets": buckets}

    def set_raise_on_list_buckets(self, exc: Exception) -> None:
        """Make list_buckets raise an exception."""
        self._raise_on_list_buckets = exc

    def set_presigned_url(self, url: str) -> None:
        """Set the URL returned by generate_presigned_url."""
        self._presigned_url = url

    def set_raise_on_generate_presigned_url(self, exc: Exception) -> None:
        """Make generate_presigned_url raise an exception."""
        self._raise_on_generate_presigned_url = exc

    def set_exists(self, path: str, value: bool) -> None:
        """Set existence result for a specific path."""
        self._exists_map[path] = value

    def set_head_object(self, response: dict[str, Any]) -> None:
        """Set the response for head_object calls."""
        self._head_object_response = response

    def set_raise_on_head_object(self, exc: Exception) -> None:
        """Make head_object raise an exception."""
        self._raise_on_head_object = exc

    def set_tagging(self, tag_set: list[dict[str, str]]) -> None:
        """Set the TagSet returned by get_object_tagging."""
        self._tagging_response = {"TagSet": tag_set}

    def set_raise_on_get_object_tagging(self, exc: Exception) -> None:
        """Make get_object_tagging raise an exception."""
        self._raise_on_get_object_tagging = exc

    def set_versions(self, versions: list[dict[str, Any]]) -> None:
        """Set the Versions returned by list_object_versions."""
        self._versions_response = {"Versions": versions}

    def set_raise_on_list_object_versions(self, exc: Exception) -> None:
        """Make list_object_versions raise an exception."""
        self._raise_on_list_object_versions = exc

    @property
    def fs(self) -> MockS3Backend:
        """Mimic S3Backend.fs property returning the filesystem."""
        return self

    @property
    def s3(self) -> MockS3Backend:
        """Mimic s3fs.S3FileSystem.s3 (botocore client)."""
        return self

    def list_buckets(self) -> dict[str, Any]:
        """Mimic botocore S3 client list_buckets."""
        if self._raise_on_list_buckets is not None:
            raise self._raise_on_list_buckets
        return dict(self._list_buckets_response)

    def generate_presigned_url(self, **kwargs: Any) -> str:
        """Mimic botocore S3 client generate_presigned_url."""
        if self._raise_on_generate_presigned_url is not None:
            raise self._raise_on_generate_presigned_url
        return self._presigned_url

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        """Mimic botocore S3 client head_object."""
        if self._raise_on_head_object is not None:
            raise self._raise_on_head_object
        return dict(self._head_object_response)

    def get_object_tagging(self, **kwargs: Any) -> dict[str, Any]:
        """Mimic botocore S3 client get_object_tagging."""
        if self._raise_on_get_object_tagging is not None:
            raise self._raise_on_get_object_tagging
        return dict(self._tagging_response)

    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]:
        """Mimic botocore S3 client list_object_versions."""
        if self._raise_on_list_object_versions is not None:
            raise self._raise_on_list_object_versions
        return dict(self._versions_response)

    # Required BackendProtocol methods (stubs for type compliance)
    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return []

    def info(self, path: str) -> dict[str, Any]:
        return {"name": path, "type": "file", "size": 0}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        return b""

    def pipe_file(self, path: str, data: bytes) -> None:
        pass

    def rm(self, path: str) -> None:
        pass

    def cp_file(self, source: str, destination: str) -> None:
        pass

    def mv(self, source: str, destination: str) -> None:
        pass

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        pass

    def exists(self, path: str) -> bool:
        if path in self._exists_map:
            return self._exists_map[path]
        return self._default_exists

    def isdir(self, path: str) -> bool:
        return False

    def isfile(self, path: str) -> bool:
        return True


def _make_settings(
    sandbox: Path,
    s3_enabled: bool = True,
    s3_region: str = "us-east-1",
    read_only: bool = True,
) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(base_path=str(sandbox)),
        s3=S3Settings(enabled=s3_enabled, region=s3_region),
    )


def _make_app_ctx(
    sandbox: Path,
    mock_s3_backend: MockS3Backend | None = None,
    s3_enabled: bool = True,
    s3_region: str = "us-east-1",
    read_only: bool = True,
) -> AppContext:
    """Create an AppContext for testing with mocked S3 backend."""
    settings = _make_settings(
        sandbox, s3_enabled=s3_enabled, s3_region=s3_region, read_only=read_only
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3 if settings.s3.enabled else None,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        s3_backend=mock_s3_backend if s3_enabled and mock_s3_backend is not None else None,
    )
    rate_limiter = RateLimiter(ops_per_minute=0)
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=rate_limiter,
    )


def _make_mock_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock MCP Context that provides AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


def _make_raw_bucket(
    name: str,
    creation_date: datetime | None = None,
) -> dict[str, Any]:
    """Create a raw bucket dict as returned by botocore list_buckets."""
    bucket: dict[str, Any] = {"Name": name}
    if creation_date is not None:
        bucket["CreationDate"] = creation_date
    return bucket


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Create a temporary sandbox directory."""
    return tmp_path


@pytest.fixture()
def mock_s3_backend() -> MockS3Backend:
    """A mock S3 backend."""
    return MockS3Backend()


@pytest.fixture()
def app_ctx(sandbox: Path, mock_s3_backend: MockS3Backend) -> AppContext:
    """AppContext with S3 enabled and mock backend."""
    return _make_app_ctx(sandbox, mock_s3_backend)


@pytest.fixture()
def mock_ctx(app_ctx: AppContext) -> MagicMock:
    """Mock MCP context with S3 enabled."""
    return _make_mock_ctx(app_ctx)


# ============================================================================
# TestListBucketsBasic: Core bucket listing functionality
# ============================================================================


class TestListBucketsBasic:
    """Tests for basic list_buckets behavior."""

    @pytest.mark.asyncio
    async def test_list_single_bucket(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """List a single bucket returns correct response."""
        creation = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        mock_s3_backend.set_buckets([_make_raw_bucket("my-bucket", creation)])

        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 1
        assert len(result.buckets) == 1
        assert result.buckets[0].name == "my-bucket"
        assert result.buckets[0].creation_date == creation
        assert result.buckets[0].region == "us-east-1"

    @pytest.mark.asyncio
    async def test_list_multiple_buckets(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """List multiple buckets returns all of them."""
        d1 = datetime(2024, 1, 1, tzinfo=UTC)
        d2 = datetime(2024, 2, 1, tzinfo=UTC)
        d3 = datetime(2024, 3, 1, tzinfo=UTC)
        mock_s3_backend.set_buckets(
            [
                _make_raw_bucket("bucket-a", d1),
                _make_raw_bucket("bucket-b", d2),
                _make_raw_bucket("bucket-c", d3),
            ]
        )

        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 3
        names = [b.name for b in result.buckets]
        assert names == ["bucket-a", "bucket-b", "bucket-c"]

    @pytest.mark.asyncio
    async def test_list_buckets_returns_correct_total_count(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """total_count matches the number of buckets returned."""
        mock_s3_backend.set_buckets(
            [
                _make_raw_bucket("b1"),
                _make_raw_bucket("b2"),
                _make_raw_bucket("b3"),
                _make_raw_bucket("b4"),
                _make_raw_bucket("b5"),
            ]
        )

        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 5
        assert len(result.buckets) == 5


# ============================================================================
# TestListBucketsMetadata: Bucket metadata fields
# ============================================================================


class TestListBucketsMetadata:
    """Tests for bucket metadata fields (name, creation_date, region)."""

    @pytest.mark.asyncio
    async def test_bucket_name(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """Bucket name is correctly extracted."""
        mock_s3_backend.set_buckets([_make_raw_bucket("data-lake-prod")])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.buckets[0].name == "data-lake-prod"

    @pytest.mark.asyncio
    async def test_bucket_creation_date(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Bucket creation_date is correctly passed through."""
        dt = datetime(2023, 6, 15, 14, 22, 33, tzinfo=UTC)
        mock_s3_backend.set_buckets([_make_raw_bucket("test-bucket", dt)])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.buckets[0].creation_date == dt

    @pytest.mark.asyncio
    async def test_bucket_missing_creation_date(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Bucket with no CreationDate gets None for creation_date."""
        mock_s3_backend.set_buckets([{"Name": "no-date-bucket"}])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.buckets[0].name == "no-date-bucket"
        assert result.buckets[0].creation_date is None

    @pytest.mark.asyncio
    async def test_bucket_non_datetime_creation_date_ignored(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Non-datetime CreationDate values are treated as None."""
        mock_s3_backend.set_buckets([{"Name": "bad-date", "CreationDate": "not-a-datetime"}])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.buckets[0].creation_date is None

    @pytest.mark.asyncio
    async def test_bucket_region_from_settings(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Region comes from S3 settings, not from the bucket itself."""
        mock_s3_backend.set_buckets([_make_raw_bucket("regional-bucket")])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend, s3_region="eu-west-1")
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.buckets[0].region == "eu-west-1"

    @pytest.mark.asyncio
    async def test_all_buckets_get_same_region(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """All buckets in the response use the configured region."""
        mock_s3_backend.set_buckets(
            [
                _make_raw_bucket("b1"),
                _make_raw_bucket("b2"),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend, s3_region="ap-southeast-1")
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        for bucket in result.buckets:
            assert bucket.region == "ap-southeast-1"


# ============================================================================
# TestListBucketsEdgeCases: Edge cases
# ============================================================================


class TestListBucketsEdgeCases:
    """Tests for edge case scenarios."""

    @pytest.mark.asyncio
    async def test_no_buckets_returns_empty_list(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """No accessible buckets returns empty list with total_count 0."""
        mock_s3_backend.set_buckets([])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 0
        assert result.buckets == []

    @pytest.mark.asyncio
    async def test_many_buckets_all_returned(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """100+ buckets are all returned without truncation."""
        bucket_count = 150
        raw_buckets = [_make_raw_bucket(f"bucket-{i:04d}") for i in range(bucket_count)]
        mock_s3_backend.set_buckets(raw_buckets)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == bucket_count
        assert len(result.buckets) == bucket_count

    @pytest.mark.asyncio
    async def test_response_missing_buckets_key(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Handles botocore response that lacks Buckets key gracefully."""
        mock_s3_backend._list_buckets_response = {}
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 0
        assert result.buckets == []

    @pytest.mark.asyncio
    async def test_bucket_with_empty_name(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Bucket with empty name is still returned."""
        mock_s3_backend.set_buckets([{"Name": ""}])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 1
        assert result.buckets[0].name == ""

    @pytest.mark.asyncio
    async def test_bucket_missing_name_key(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Bucket dict missing Name key defaults to empty string."""
        mock_s3_backend.set_buckets([{}])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert result.total_count == 1
        assert result.buckets[0].name == ""


# ============================================================================
# TestListBucketsErrors: Error handling
# ============================================================================


class TestListBucketsErrors:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_s3_disabled_returns_backend_not_configured(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 backend is not enabled."""
        app_ctx = _make_app_ctx(sandbox, s3_enabled=False)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED
        assert "not enabled" in result["message"]

    @pytest.mark.asyncio
    async def test_s3_enabled_but_no_instance_returns_error(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 is enabled but no backend registered."""
        # Create with s3_enabled=True but no mock_s3_backend passed
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend=None, s3_enabled=True)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED
        assert "no instance" in result["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_backend_error(self) -> None:
        """BACKEND_ERROR when no context is available."""
        result = await list_buckets(ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_credential_error_returns_backend_error(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """BACKEND_ERROR for credential issues."""
        mock_s3_backend.set_raise_on_list_buckets(Exception("Unable to locate credentials"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "credentials" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_connectivity_error_returns_backend_error(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """BACKEND_ERROR for connectivity issues."""
        mock_s3_backend.set_raise_on_list_buckets(ConnectionError("Could not connect to endpoint"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "connect" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_fs_error_unwraps_cause(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """FSError with __cause__ unwraps to surface original error code."""
        from mamba_mcp_fs.errors import PathNotFoundError

        inner = PathNotFoundError("bucket not found")
        outer = BackendError("wrapper")
        outer.__cause__ = inner
        mock_s3_backend.set_raise_on_list_buckets(outer)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "bucket not found" in result["message"]

    @pytest.mark.asyncio
    async def test_fs_error_without_cause(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """FSError without __cause__ uses its own code."""
        mock_s3_backend.set_raise_on_list_buckets(BackendError("S3 operational error"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "operational error" in result["message"].lower()


# ============================================================================
# TestListBucketsResponseModel: Response model validation
# ============================================================================


class TestListBucketsResponseModel:
    """Tests for ListBucketsResponse model behavior."""

    @pytest.mark.asyncio
    async def test_response_is_list_buckets_response(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Successful response is a ListBucketsResponse instance."""
        mock_s3_backend.set_buckets([_make_raw_bucket("test")])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)

    @pytest.mark.asyncio
    async def test_bucket_entries_are_bucket_info(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Each bucket entry is a BucketInfo model."""
        mock_s3_backend.set_buckets([_make_raw_bucket("test")])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        assert all(isinstance(b, BucketInfo) for b in result.buckets)

    @pytest.mark.asyncio
    async def test_response_json_serializable(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response can be serialized to JSON (round-trip)."""
        dt = datetime(2024, 3, 15, tzinfo=UTC)
        mock_s3_backend.set_buckets([_make_raw_bucket("json-test", dt)])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await list_buckets(ctx=ctx)

        assert isinstance(result, ListBucketsResponse)
        json_str = result.model_dump_json()
        assert "json-test" in json_str
        assert "total_count" in json_str


# ============================================================================
# TestGetPresignedUrlDownload: Download presigned URL generation
# ============================================================================


class TestGetPresignedUrlDownload:
    """Tests for presigned download URL generation."""

    @pytest.mark.asyncio
    async def test_download_url_basic(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """Generates a presigned download URL for an existing object."""
        mock_s3_backend.set_presigned_url("https://s3.example.com/bucket/file.txt?signed=abc")
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.url == "https://s3.example.com/bucket/file.txt?signed=abc"
        assert result.path == "s3://bucket/file.txt"
        assert result.operation == "download"

    @pytest.mark.asyncio
    async def test_download_url_default_operation(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Default operation is 'download'."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.operation == "download"

    @pytest.mark.asyncio
    async def test_download_url_default_expiration(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Default expires_in is 3600 seconds (1 hour)."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        # expires_at should be ~1 hour from now
        expected_min = before + timedelta(seconds=3600)
        expected_max = after + timedelta(seconds=3600)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_download_url_custom_expiration(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Custom expires_in is respected in expires_at calculation."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", expires_in=7200, ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        expected_min = before + timedelta(seconds=7200)
        expected_max = after + timedelta(seconds=7200)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_download_url_nonexistent_object(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """PATH_NOT_FOUND for download of non-existent object."""
        mock_s3_backend.set_exists("s3://bucket/missing.txt", False)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/missing.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "does not exist" in result["message"]

    @pytest.mark.asyncio
    async def test_download_url_preserves_original_path(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response path matches the original input path."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://my-bucket/deep/nested/file.csv", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.path == "s3://my-bucket/deep/nested/file.csv"


# ============================================================================
# TestGetPresignedUrlUpload: Upload presigned URL generation
# ============================================================================


class TestGetPresignedUrlUpload:
    """Tests for presigned upload URL generation."""

    @pytest.mark.asyncio
    async def test_upload_url_basic(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """Generates a presigned upload URL when write mode is enabled."""
        mock_s3_backend.set_presigned_url("https://s3.example.com/upload?signed=xyz")
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend, read_only=False)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(
            path="s3://bucket/new-file.txt", operation="upload", ctx=ctx
        )

        assert isinstance(result, PresignedUrlResponse)
        assert result.url == "https://s3.example.com/upload?signed=xyz"
        assert result.path == "s3://bucket/new-file.txt"
        assert result.operation == "upload"

    @pytest.mark.asyncio
    async def test_upload_url_does_not_check_exists(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Upload URLs do not require the object to already exist."""
        mock_s3_backend._default_exists = False
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend, read_only=False)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(
            path="s3://bucket/new-file.txt", operation="upload", ctx=ctx
        )

        assert isinstance(result, PresignedUrlResponse)
        assert result.operation == "upload"

    @pytest.mark.asyncio
    async def test_upload_url_read_only_rejected(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """PERMISSION_DENIED for upload URLs when server is in read-only mode."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", operation="upload", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "read-only" in result["message"]

    @pytest.mark.asyncio
    async def test_upload_url_expiration(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Upload URL respects expires_in parameter."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend, read_only=False)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(
            path="s3://bucket/file.txt", operation="upload", expires_in=1800, ctx=ctx
        )
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        expected_min = before + timedelta(seconds=1800)
        expected_max = after + timedelta(seconds=1800)
        assert expected_min <= result.expires_at <= expected_max


# ============================================================================
# TestGetPresignedUrlExpiration: Expiration clamping and calculation
# ============================================================================


class TestGetPresignedUrlExpiration:
    """Tests for expires_in clamping and expires_at calculation."""

    @pytest.mark.asyncio
    async def test_expires_in_capped_at_max(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """expires_in exceeding 604800 is capped to 604800 seconds."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", expires_in=999999, ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        # Should be capped at 7 days (604800 seconds)
        expected_min = before + timedelta(seconds=604800)
        expected_max = after + timedelta(seconds=604800)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_expires_in_zero_clamped_to_minimum(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """expires_in of 0 is clamped to minimum (60 seconds)."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", expires_in=0, ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        expected_min = before + timedelta(seconds=60)
        expected_max = after + timedelta(seconds=60)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_expires_in_negative_clamped_to_minimum(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Negative expires_in is clamped to minimum (60 seconds)."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", expires_in=-100, ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        expected_min = before + timedelta(seconds=60)
        expected_max = after + timedelta(seconds=60)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_expires_in_at_exact_max(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """expires_in at exactly 604800 is accepted without clamping."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", expires_in=604800, ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        expected_min = before + timedelta(seconds=604800)
        expected_max = after + timedelta(seconds=604800)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_expires_in_at_exact_minimum(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """expires_in at exactly 60 is accepted without clamping."""
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", expires_in=60, ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, PresignedUrlResponse)
        expected_min = before + timedelta(seconds=60)
        expected_max = after + timedelta(seconds=60)
        assert expected_min <= result.expires_at <= expected_max

    @pytest.mark.asyncio
    async def test_expires_at_is_utc(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """expires_at timestamp is in UTC."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.expires_at.tzinfo == UTC


# ============================================================================
# TestGetPresignedUrlEdgeCases: Edge cases
# ============================================================================


class TestGetPresignedUrlEdgeCases:
    """Tests for edge case scenarios."""

    @pytest.mark.asyncio
    async def test_very_long_s3_key(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """Handles very long S3 key paths."""
        long_key = "/".join(["dir"] * 50) + "/file.txt"
        path = f"s3://bucket/{long_key}"
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path=path, ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.path == path

    @pytest.mark.asyncio
    async def test_path_with_special_characters(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Handles S3 keys with special characters."""
        path = "s3://bucket/path with spaces/file (1).txt"
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path=path, ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.path == path

    @pytest.mark.asyncio
    async def test_empty_bucket_name(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """INVALID_OPERATION for S3 path with empty bucket name."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3:///key/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "empty bucket" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_no_object_key(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """INVALID_OPERATION for S3 path with no object key."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "no object key" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_bucket_only_with_trailing_slash(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """INVALID_OPERATION for S3 path with bucket and trailing slash but no key."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "no object key" in result["message"].lower()


# ============================================================================
# TestGetPresignedUrlErrors: Error handling
# ============================================================================


class TestGetPresignedUrlErrors:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_s3_disabled_returns_backend_not_configured(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 backend is not enabled."""
        app_ctx = _make_app_ctx(sandbox, s3_enabled=False)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED
        assert "not enabled" in result["message"]

    @pytest.mark.asyncio
    async def test_s3_enabled_but_no_instance(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 is enabled but no backend registered."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend=None, s3_enabled=True)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED
        assert "no instance" in result["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_backend_error(self) -> None:
        """BACKEND_ERROR when no context is available."""
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_generate_presigned_url_exception(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """BACKEND_ERROR when botocore generate_presigned_url raises."""
        mock_s3_backend.set_raise_on_generate_presigned_url(Exception("Unable to generate URL"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "Unable to generate URL" in result["message"]

    @pytest.mark.asyncio
    async def test_fs_error_unwraps_cause(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """FSError with __cause__ unwraps to surface original error code."""
        from mamba_mcp_fs.errors import PathNotFoundError

        inner = PathNotFoundError("object not found")
        outer = BackendError("wrapper")
        outer.__cause__ = inner
        mock_s3_backend.set_raise_on_generate_presigned_url(outer)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "object not found" in result["message"]


# ============================================================================
# TestGetPresignedUrlResponseModel: Response model validation
# ============================================================================


class TestGetPresignedUrlResponseModel:
    """Tests for PresignedUrlResponse model behavior."""

    @pytest.mark.asyncio
    async def test_response_is_presigned_url_response(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Successful response is a PresignedUrlResponse instance."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)

    @pytest.mark.asyncio
    async def test_response_has_all_required_fields(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response contains all required fields."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert isinstance(result.url, str)
        assert isinstance(result.path, str)
        assert result.operation in ("download", "upload")
        assert isinstance(result.expires_at, datetime)

    @pytest.mark.asyncio
    async def test_response_json_serializable(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response can be serialized to JSON."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        json_str = result.model_dump_json()
        assert "url" in json_str
        assert "path" in json_str
        assert "operation" in json_str
        assert "expires_at" in json_str


# ============================================================================
# Helpers: Standard head_object response data
# ============================================================================


def _make_head_response(
    storage_class: str = "STANDARD",
    etag: str = '"abc123"',
    version_id: str | None = None,
    server_side_encryption: str | None = None,
    content_type: str = "application/pdf",
    last_modified: datetime | None = None,
) -> dict[str, Any]:
    """Create a mock head_object response."""
    resp: dict[str, Any] = {
        "StorageClass": storage_class,
        "ETag": etag,
        "ContentType": content_type,
    }
    if last_modified is not None:
        resp["LastModified"] = last_modified
    else:
        resp["LastModified"] = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    if version_id is not None:
        resp["VersionId"] = version_id
    if server_side_encryption is not None:
        resp["ServerSideEncryption"] = server_side_encryption
    return resp


# ============================================================================
# TestGetObjectMetadataBasic: Core metadata retrieval
# ============================================================================


class TestGetObjectMetadataBasic:
    """Tests for basic get_object_metadata behavior."""

    @pytest.mark.asyncio
    async def test_basic_metadata(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """Returns core S3 metadata from head_object."""
        last_mod = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        mock_s3_backend.set_head_object(
            _make_head_response(
                storage_class="STANDARD",
                etag='"abc123def"',
                content_type="text/plain",
                last_modified=last_mod,
            )
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.path == "s3://bucket/file.txt"
        assert result.storage_class == "STANDARD"
        assert result.etag == '"abc123def"'
        assert result.content_type == "text/plain"
        assert result.last_modified == last_mod

    @pytest.mark.asyncio
    async def test_metadata_with_encryption(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Returns server-side encryption info from head_object."""
        mock_s3_backend.set_head_object(_make_head_response(server_side_encryption="aws:kms"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/encrypted.dat", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.server_side_encryption == "aws:kms"

    @pytest.mark.asyncio
    async def test_metadata_with_version_id(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Returns version_id when bucket has versioning enabled."""
        mock_s3_backend.set_head_object(_make_head_response(version_id="v1-abc-123"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/versioned.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.version_id == "v1-abc-123"

    @pytest.mark.asyncio
    async def test_metadata_without_version_id(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """version_id is None when bucket does not have versioning."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.version_id is None

    @pytest.mark.asyncio
    async def test_content_type_populated(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """content_type is correctly populated from head_object."""
        mock_s3_backend.set_head_object(_make_head_response(content_type="image/png"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/image.png", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.content_type == "image/png"

    @pytest.mark.asyncio
    async def test_last_modified_populated(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """last_modified is correctly populated from head_object."""
        ts = datetime(2025, 1, 10, 8, 30, 0, tzinfo=UTC)
        mock_s3_backend.set_head_object(_make_head_response(last_modified=ts))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/recent.csv", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.last_modified == ts

    @pytest.mark.asyncio
    async def test_preserves_original_path(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response path matches the original input path."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://my-bucket/deep/nested/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.path == "s3://my-bucket/deep/nested/file.txt"


# ============================================================================
# TestGetObjectMetadataTags: Tag retrieval
# ============================================================================


class TestGetObjectMetadataTags:
    """Tests for object tag retrieval."""

    @pytest.mark.asyncio
    async def test_tags_included_by_default(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Tags are included by default (include_tags=True)."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_tagging(
            [
                {"Key": "env", "Value": "production"},
                {"Key": "team", "Value": "data"},
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.tags == {"env": "production", "team": "data"}

    @pytest.mark.asyncio
    async def test_tags_empty_when_no_tags(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Returns empty dict when object has no tags."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_tagging([])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.tags == {}

    @pytest.mark.asyncio
    async def test_tags_excluded_when_include_tags_false(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Tags are None when include_tags is False."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_tagging([{"Key": "env", "Value": "production"}])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", include_tags=False, ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.tags is None

    @pytest.mark.asyncio
    async def test_tags_graceful_on_tagging_error(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Returns empty tags dict when get_object_tagging fails."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_raise_on_get_object_tagging(Exception("Access denied"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.tags == {}

    @pytest.mark.asyncio
    async def test_many_tags(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """Returns all tags when there are many."""
        tag_set = [{"Key": f"key-{i}", "Value": f"val-{i}"} for i in range(10)]
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_tagging(tag_set)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.tags is not None
        assert len(result.tags) == 10
        assert result.tags["key-0"] == "val-0"
        assert result.tags["key-9"] == "val-9"


# ============================================================================
# TestGetObjectMetadataVersions: Version listing
# ============================================================================


class TestGetObjectMetadataVersions:
    """Tests for version history retrieval."""

    @pytest.mark.asyncio
    async def test_versions_not_included_by_default(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Versions are not included by default (include_versions=False)."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.versions is None

    @pytest.mark.asyncio
    async def test_versions_included_when_requested(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Versions are returned when include_versions=True."""
        mock_s3_backend.set_head_object(_make_head_response())
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 2, 1, tzinfo=UTC)
        mock_s3_backend.set_versions(
            [
                {
                    "Key": "file.txt",
                    "VersionId": "v2",
                    "IsLatest": True,
                    "LastModified": ts2,
                    "Size": 200,
                    "StorageClass": "STANDARD",
                    "ETag": '"def456"',
                },
                {
                    "Key": "file.txt",
                    "VersionId": "v1",
                    "IsLatest": False,
                    "LastModified": ts1,
                    "Size": 100,
                    "StorageClass": "STANDARD",
                    "ETag": '"abc123"',
                },
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(
            path="s3://bucket/file.txt", include_versions=True, ctx=ctx
        )

        assert isinstance(result, ObjectMetadataResponse)
        assert result.versions is not None
        assert len(result.versions) == 2
        assert result.versions[0]["version_id"] == "v2"
        assert result.versions[0]["is_latest"] is True
        assert result.versions[1]["version_id"] == "v1"
        assert result.versions[1]["is_latest"] is False

    @pytest.mark.asyncio
    async def test_versions_empty_when_no_versioning(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Returns empty versions list when bucket has no versioning."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_versions([])
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(
            path="s3://bucket/file.txt", include_versions=True, ctx=ctx
        )

        assert isinstance(result, ObjectMetadataResponse)
        assert result.versions == []

    @pytest.mark.asyncio
    async def test_versions_filters_by_exact_key(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Only versions matching the exact key are included."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_versions(
            [
                {
                    "Key": "file.txt",
                    "VersionId": "v1",
                    "IsLatest": True,
                    "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
                    "Size": 100,
                },
                {
                    "Key": "file.txt.bak",
                    "VersionId": "v-other",
                    "IsLatest": True,
                    "LastModified": datetime(2024, 1, 2, tzinfo=UTC),
                    "Size": 50,
                },
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(
            path="s3://bucket/file.txt", include_versions=True, ctx=ctx
        )

        assert isinstance(result, ObjectMetadataResponse)
        assert result.versions is not None
        assert len(result.versions) == 1
        assert result.versions[0]["version_id"] == "v1"

    @pytest.mark.asyncio
    async def test_versions_graceful_on_error(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Returns empty list when list_object_versions fails."""
        mock_s3_backend.set_head_object(_make_head_response())
        mock_s3_backend.set_raise_on_list_object_versions(Exception("Access denied"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(
            path="s3://bucket/file.txt", include_versions=True, ctx=ctx
        )

        assert isinstance(result, ObjectMetadataResponse)
        assert result.versions == []


# ============================================================================
# TestGetObjectMetadataEdgeCases: Edge cases
# ============================================================================


class TestGetObjectMetadataEdgeCases:
    """Tests for edge case scenarios."""

    @pytest.mark.asyncio
    async def test_glacier_storage_class(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Metadata is accessible for GLACIER storage class objects."""
        mock_s3_backend.set_head_object(_make_head_response(storage_class="GLACIER"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/archived.tar.gz", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.storage_class == "GLACIER"

    @pytest.mark.asyncio
    async def test_deep_archive_storage_class(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Metadata is accessible for DEEP_ARCHIVE storage class objects."""
        mock_s3_backend.set_head_object(_make_head_response(storage_class="DEEP_ARCHIVE"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/deep.tar.gz", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.storage_class == "DEEP_ARCHIVE"

    @pytest.mark.asyncio
    async def test_missing_storage_class_defaults_to_standard(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Missing StorageClass in head_object defaults to STANDARD."""
        mock_s3_backend.set_head_object(
            {
                "ETag": '"abc"',
                "ContentType": "text/plain",
                "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.storage_class == "STANDARD"

    @pytest.mark.asyncio
    async def test_no_encryption_returns_none(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """server_side_encryption is None when not set."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.server_side_encryption is None

    @pytest.mark.asyncio
    async def test_empty_bucket_name_rejected(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """INVALID_OPERATION for empty bucket name."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3:///key/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "empty bucket" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_no_object_key_rejected(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """INVALID_OPERATION for path with no object key."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "no object key" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_content_type_defaults_to_octet_stream(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Missing ContentType defaults to application/octet-stream."""
        mock_s3_backend.set_head_object(
            {
                "StorageClass": "STANDARD",
                "ETag": '"abc"',
                "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/unknown", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.content_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_last_modified_fallback_when_missing(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Falls back to current time when LastModified is missing."""
        mock_s3_backend.set_head_object(
            {
                "StorageClass": "STANDARD",
                "ETag": '"abc"',
                "ContentType": "text/plain",
            }
        )
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, ObjectMetadataResponse)
        assert before <= result.last_modified <= after


# ============================================================================
# TestGetObjectMetadataErrors: Error handling
# ============================================================================


class TestGetObjectMetadataErrors:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_s3_disabled_returns_backend_not_configured(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 backend is not enabled."""
        app_ctx = _make_app_ctx(sandbox, s3_enabled=False)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED
        assert "not enabled" in result["message"]

    @pytest.mark.asyncio
    async def test_s3_enabled_but_no_instance(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 is enabled but no backend registered."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend=None, s3_enabled=True)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED
        assert "no instance" in result["message"]

    @pytest.mark.asyncio
    async def test_no_context_returns_backend_error(self) -> None:
        """BACKEND_ERROR when no context is available."""
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_object_not_found(self, sandbox: Path, mock_s3_backend: MockS3Backend) -> None:
        """PATH_NOT_FOUND when head_object returns 404."""
        mock_s3_backend.set_raise_on_head_object(
            Exception("An error occurred (404) when calling HeadObject: Not Found")
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/missing.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "does not exist" in result["message"]

    @pytest.mark.asyncio
    async def test_object_not_found_nosuchkey(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """PATH_NOT_FOUND when head_object raises NoSuchKey."""
        mock_s3_backend.set_raise_on_head_object(Exception("NoSuchKey"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/nope.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_unexpected_head_object_error(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """BACKEND_ERROR for unexpected head_object exceptions."""
        mock_s3_backend.set_raise_on_head_object(Exception("Internal server error"))
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "Internal server error" in result["message"]

    @pytest.mark.asyncio
    async def test_fs_error_unwraps_cause(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """FSError with __cause__ unwraps to surface original error code."""
        from mamba_mcp_fs.errors import PathNotFoundError

        inner = PathNotFoundError("object not found")
        outer = BackendError("wrapper")
        outer.__cause__ = inner
        mock_s3_backend.set_raise_on_head_object(outer)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "object not found" in result["message"]


# ============================================================================
# TestGetObjectMetadataResponseModel: Response model validation
# ============================================================================


class TestGetObjectMetadataResponseModel:
    """Tests for ObjectMetadataResponse model behavior."""

    @pytest.mark.asyncio
    async def test_response_is_object_metadata_response(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Successful response is an ObjectMetadataResponse instance."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)

    @pytest.mark.asyncio
    async def test_response_has_all_required_fields(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response contains all required fields."""
        mock_s3_backend.set_head_object(
            _make_head_response(version_id="v1", server_side_encryption="AES256")
        )
        mock_s3_backend.set_tagging([{"Key": "env", "Value": "test"}])
        mock_s3_backend.set_versions(
            [
                {
                    "Key": "file.txt",
                    "VersionId": "v1",
                    "IsLatest": True,
                    "LastModified": datetime(2024, 1, 1, tzinfo=UTC),
                    "Size": 100,
                }
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(
            path="s3://bucket/file.txt", include_versions=True, ctx=ctx
        )

        assert isinstance(result, ObjectMetadataResponse)
        assert isinstance(result.path, str)
        assert isinstance(result.storage_class, str)
        assert isinstance(result.etag, str)
        assert isinstance(result.content_type, str)
        assert isinstance(result.last_modified, datetime)
        assert isinstance(result.tags, dict)
        assert isinstance(result.versions, list)
        assert result.version_id == "v1"
        assert result.server_side_encryption == "AES256"

    @pytest.mark.asyncio
    async def test_response_json_serializable(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Response can be serialized to JSON."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        json_str = result.model_dump_json()
        assert "path" in json_str
        assert "storage_class" in json_str
        assert "etag" in json_str
        assert "content_type" in json_str
        assert "last_modified" in json_str


# ============================================================================
# TestGetPresignedUrlNonS3Path: Non-s3:// path handling
# ============================================================================


class TestGetPresignedUrlNonS3Path:
    """Tests for presigned URL with non-s3:// path format."""

    @pytest.mark.asyncio
    async def test_path_without_s3_prefix(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Path without s3:// prefix is parsed as bucket/key directly."""
        mock_s3_backend.set_presigned_url("https://s3.example.com/signed")
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="bucket/file.txt", ctx=ctx)

        assert isinstance(result, PresignedUrlResponse)
        assert result.path == "bucket/file.txt"
        assert result.url == "https://s3.example.com/signed"

    @pytest.mark.asyncio
    async def test_path_without_prefix_empty_key(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Non-s3:// path with no key returns INVALID_OPERATION."""
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_presigned_url(path="bucket-only", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "no object key" in result["message"].lower()


# ============================================================================
# TestGetObjectMetadataNonS3Path: Non-s3:// path handling
# ============================================================================


class TestGetObjectMetadataNonS3Path:
    """Tests for object metadata with non-s3:// path format."""

    @pytest.mark.asyncio
    async def test_path_without_s3_prefix(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Path without s3:// prefix is parsed as bucket/key directly."""
        mock_s3_backend.set_head_object(_make_head_response())
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="bucket/file.txt", ctx=ctx)

        assert isinstance(result, ObjectMetadataResponse)
        assert result.path == "bucket/file.txt"

    @pytest.mark.asyncio
    async def test_non_datetime_last_modified_handled(
        self, sandbox: Path, mock_s3_backend: MockS3Backend
    ) -> None:
        """Non-datetime LastModified value is replaced with current UTC time."""
        mock_s3_backend.set_head_object(
            {
                "StorageClass": "STANDARD",
                "ETag": '"abc"',
                "ContentType": "text/plain",
                "LastModified": "not-a-datetime-string",
            }
        )
        before = datetime.now(UTC)
        app_ctx = _make_app_ctx(sandbox, mock_s3_backend)
        ctx = _make_mock_ctx(app_ctx)
        result = await get_object_metadata(path="s3://bucket/file.txt", ctx=ctx)
        after = datetime.now(UTC)

        assert isinstance(result, ObjectMetadataResponse)
        # Non-datetime value should be replaced with current time
        assert before <= result.last_modified <= after
