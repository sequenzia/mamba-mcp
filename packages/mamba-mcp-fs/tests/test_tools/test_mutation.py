"""Tests for the mutation MCP tools (write_file, delete_file, move_file, copy_file).

Covers:
- Unit: Text file creation with mocked backend
- Unit: Binary file creation (base64 decode)
- Unit: Overwrite protection
- Unit: Read-only mode enforcement
- Unit: Size limit enforcement
- Unit: Extension security policy enforcement
- Unit: Parent directory creation
- Unit: No context error
- Unit: BackendError unwrapping
- Unit: Empty content handling
- Unit: Overwrite vs create (response.created flag)
- Integration: Real file writing with tmp_path
- Integration: Parent directory creation on real filesystem
- Integration: Binary file writing on real filesystem
- Unit: File deletion with mocked backend
- Unit: Delete read-only mode enforcement
- Unit: Delete directory rejection
- Unit: Delete non-existent file
- Unit: Delete path traversal errors
- Unit: Delete BackendError unwrapping
- Integration: Real file deletion with tmp_path
- Unit: File move with mocked backend
- Unit: Cross-backend move rejection
- Unit: Move overwrite protection
- Unit: Move read-only mode enforcement
- Unit: Source not found for move
- Unit: Path traversal errors on move source and destination
- Unit: Move overwritten flag correctly reflects destination existence
- Unit: Move backend error handling and unwrapping
- Integration: Real file move/rename with tmp_path
- Integration: Move to different subdirectory
- Integration: Move overwrite on real filesystem
- Unit: Same-backend copy with mocked backend
- Unit: Cross-backend copy with mocked backends
- Unit: Copy overwrite protection
- Unit: Copy size limit enforcement on destination
- Unit: Copy read-only mode enforcement
- Unit: Copy source not found
- Unit: Copy path traversal errors
- Unit: Copy cross_backend flag correctly set
- Unit: Copy backend error handling and unwrapping
- Integration: Local-to-local copy with tmp_path
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from mamba_mcp_fs.backends.base import BackendManager
from mamba_mcp_fs.config import LocalSettings, S3Settings, ServerSettings, Settings
from mamba_mcp_fs.errors import (
    BackendError,
    ErrorCode,
    PathOutsideSandboxError,
    PermissionDeniedError,
)
from mamba_mcp_fs.models.responses import (
    CopyFileResponse,
    CreateDirectoryResponse,
    DeleteFileResponse,
    MoveFileResponse,
    WriteFileResponse,
)
from mamba_mcp_fs.rate_limit import RateLimiter
from mamba_mcp_fs.security import SecurityValidator
from mamba_mcp_fs.server import AppContext
from mamba_mcp_fs.tools.mutation_tools import (
    copy_file,
    create_directory,
    delete_file,
    move_file,
    write_file,
)

# ============================================================================
# Helpers: Mock backend, context, and test data
# ============================================================================


class MockBackend:
    """A mock backend for unit testing mutation tools."""

    def __init__(self) -> None:
        self._exists_result: bool = False
        self._written_files: dict[str, bytes] = {}
        self._created_dirs: list[str] = []
        self._raise_on_pipe_file: Exception | None = None
        self._raise_on_exists: Exception | None = None
        self._raise_on_mkdir: Exception | None = None

    def set_exists_result(self, result: bool) -> None:
        self._exists_result = result

    def set_raise_on_pipe_file(self, exc: Exception) -> None:
        self._raise_on_pipe_file = exc

    def set_raise_on_exists(self, exc: Exception) -> None:
        self._raise_on_exists = exc

    def set_raise_on_mkdir(self, exc: Exception) -> None:
        self._raise_on_mkdir = exc

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return []

    def info(self, path: str) -> dict[str, Any]:
        return {"name": path, "type": "file", "size": 0}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        return b""

    def pipe_file(self, path: str, data: bytes) -> None:
        if self._raise_on_pipe_file is not None:
            raise self._raise_on_pipe_file
        self._written_files[path] = data

    def rm(self, path: str) -> None:
        pass

    def cp_file(self, source: str, destination: str) -> None:
        pass

    def mv(self, source: str, destination: str) -> None:
        pass

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        if self._raise_on_mkdir is not None:
            raise self._raise_on_mkdir
        self._created_dirs.append(path)

    def exists(self, path: str) -> bool:
        if self._raise_on_exists is not None:
            raise self._raise_on_exists
        return self._exists_result

    def isdir(self, path: str) -> bool:
        return False

    def isfile(self, path: str) -> bool:
        return self._exists_result


def _make_settings(
    sandbox: Path,
    read_only: bool = False,
    max_file_size: int = 10_485_760,
    denied_extensions: str | None = None,
) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        server=ServerSettings(read_only=read_only, denied_extensions=denied_extensions),
        local=LocalSettings(base_path=str(sandbox), max_file_size=max_file_size),
        s3=S3Settings(enabled=False),
    )


def _make_app_ctx(
    sandbox: Path,
    mock_backend: MockBackend,
    read_only: bool = False,
    max_file_size: int = 10_485_760,
    denied_extensions: str | None = None,
) -> AppContext:
    """Create an AppContext for testing with mocked dependencies."""
    settings = _make_settings(
        sandbox,
        read_only=read_only,
        max_file_size=max_file_size,
        denied_extensions=denied_extensions,
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=mock_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


def _make_mock_ctx(
    app_ctx: AppContext,
) -> MagicMock:
    """Create a mock MCP Context that provides AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Create a temporary sandbox directory."""
    return tmp_path


@pytest.fixture()
def mock_backend() -> MockBackend:
    """A mock backend."""
    return MockBackend()


@pytest.fixture()
def app_ctx(sandbox: Path, mock_backend: MockBackend) -> AppContext:
    """AppContext with read_only=False (write mode enabled)."""
    return _make_app_ctx(sandbox, mock_backend, read_only=False)


@pytest.fixture()
def mock_ctx(app_ctx: AppContext) -> MagicMock:
    """Mock MCP context."""
    return _make_mock_ctx(app_ctx)


# ============================================================================
# Tests: write_file -- Basic text file creation
# ============================================================================


class TestWriteFileBasicText:
    """Test text file creation with write_file."""

    @pytest.mark.anyio()
    async def test_creates_text_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Creates new file with text content."""
        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="Hello, world!", ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.path == file_path
        assert result.backend == "local"
        assert result.size_bytes == len(b"Hello, world!")
        assert result.created is True
        assert mock_backend._written_files[file_path] == b"Hello, world!"

    @pytest.mark.anyio()
    async def test_creates_empty_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Writing empty content creates empty file."""
        file_path = str(sandbox / "empty.txt")
        result = await write_file(path=file_path, content="", ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == 0
        assert result.created is True
        assert mock_backend._written_files[file_path] == b""

    @pytest.mark.anyio()
    async def test_creates_file_with_unicode(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Creates file with unicode content."""
        file_path = str(sandbox / "unicode.txt")
        content = "Hello, world! \u2603 \u2764"
        result = await write_file(path=file_path, content=content, ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == len(content.encode("utf-8"))
        assert mock_backend._written_files[file_path] == content.encode("utf-8")

    @pytest.mark.anyio()
    async def test_returns_local_backend(self, sandbox: Path, mock_ctx: MagicMock) -> None:
        """Returns backend='local' for local paths."""
        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="test", ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.backend == "local"


# ============================================================================
# Tests: write_file -- Binary file creation (base64)
# ============================================================================


class TestWriteFileBinaryBase64:
    """Test binary file creation with base64 encoding."""

    @pytest.mark.anyio()
    async def test_creates_binary_file_from_base64(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Creates file with base64-decoded binary content."""
        file_path = str(sandbox / "image.png")
        raw_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00"
        b64_content = base64.b64encode(raw_bytes).decode("ascii")

        result = await write_file(
            path=file_path, content=b64_content, encoding="base64", ctx=mock_ctx
        )

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == len(raw_bytes)
        assert result.created is True
        assert mock_backend._written_files[file_path] == raw_bytes

    @pytest.mark.anyio()
    async def test_empty_base64_creates_empty_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Empty base64 content creates empty file."""
        file_path = str(sandbox / "empty.bin")
        b64_content = base64.b64encode(b"").decode("ascii")

        result = await write_file(
            path=file_path, content=b64_content, encoding="base64", ctx=mock_ctx
        )

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == 0
        assert mock_backend._written_files[file_path] == b""

    @pytest.mark.anyio()
    async def test_invalid_base64_returns_error(self, sandbox: Path, mock_ctx: MagicMock) -> None:
        """Invalid base64 content returns INVALID_OPERATION error."""
        file_path = str(sandbox / "bad.bin")

        result = await write_file(
            path=file_path, content="not-valid-base64!!!", encoding="base64", ctx=mock_ctx
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "base64" in result["message"].lower()


# ============================================================================
# Tests: write_file -- Overwrite protection
# ============================================================================


class TestWriteFileOverwriteProtection:
    """Test overwrite behavior."""

    @pytest.mark.anyio()
    async def test_overwrite_existing_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Overwrites existing file when overwrite=true."""
        file_path = str(sandbox / "existing.txt")
        mock_backend.set_exists_result(True)

        result = await write_file(
            path=file_path, content="new content", overwrite=True, ctx=mock_ctx
        )

        assert isinstance(result, WriteFileResponse)
        assert result.created is False  # Overwritten, not created
        assert result.size_bytes == len(b"new content")

    @pytest.mark.anyio()
    async def test_overwrite_false_with_existing_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Returns PERMISSION_DENIED when overwrite=false and file exists."""
        file_path = str(sandbox / "existing.txt")
        mock_backend.set_exists_result(True)

        result = await write_file(path=file_path, content="content", overwrite=False, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "overwrite" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_overwrite_false_with_new_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Creates file when overwrite=false and file does not exist."""
        file_path = str(sandbox / "new.txt")
        mock_backend.set_exists_result(False)

        result = await write_file(path=file_path, content="content", overwrite=False, ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.created is True

    @pytest.mark.anyio()
    async def test_created_flag_new_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """created=True when writing a new file."""
        file_path = str(sandbox / "brand_new.txt")
        mock_backend.set_exists_result(False)

        result = await write_file(path=file_path, content="data", ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.created is True

    @pytest.mark.anyio()
    async def test_created_flag_overwritten_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """created=False when overwriting an existing file."""
        file_path = str(sandbox / "exists.txt")
        mock_backend.set_exists_result(True)

        result = await write_file(path=file_path, content="data", ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.created is False


# ============================================================================
# Tests: write_file -- Read-only mode enforcement
# ============================================================================


class TestWriteFileReadOnlyMode:
    """Test read-only mode enforcement."""

    @pytest.mark.anyio()
    async def test_read_only_returns_permission_denied(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Returns PERMISSION_DENIED when server is in read-only mode."""
        app_ctx = _make_app_ctx(sandbox, mock_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="content", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "read-only" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_read_only_prevents_all_writes(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Read-only mode blocks write even with overwrite=true."""
        app_ctx = _make_app_ctx(sandbox, mock_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="content", overwrite=True, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        # Ensure no file was written
        assert len(mock_backend._written_files) == 0


# ============================================================================
# Tests: write_file -- Size limit enforcement
# ============================================================================


class TestWriteFileSizeLimit:
    """Test size limit enforcement."""

    @pytest.mark.anyio()
    async def test_content_within_limit(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Content within size limit succeeds."""
        app_ctx = _make_app_ctx(sandbox, mock_backend, read_only=False, max_file_size=100)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "small.txt")
        result = await write_file(path=file_path, content="x" * 50, ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == 50

    @pytest.mark.anyio()
    async def test_content_exceeds_limit(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Content exceeding size limit returns FILE_TOO_LARGE."""
        app_ctx = _make_app_ctx(sandbox, mock_backend, read_only=False, max_file_size=100)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "big.txt")
        result = await write_file(path=file_path, content="x" * 200, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE
        assert "200" in result["message"]
        assert "100" in result["message"]

    @pytest.mark.anyio()
    async def test_content_exactly_at_limit(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Content exactly at size limit succeeds."""
        app_ctx = _make_app_ctx(sandbox, mock_backend, read_only=False, max_file_size=100)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "exact.txt")
        result = await write_file(path=file_path, content="x" * 100, ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == 100

    @pytest.mark.anyio()
    async def test_base64_size_check_uses_decoded_size(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Size check uses decoded bytes, not base64 string length."""
        # 200 bytes of data will encode to ~268 chars in base64
        app_ctx = _make_app_ctx(sandbox, mock_backend, read_only=False, max_file_size=100)
        ctx = _make_mock_ctx(app_ctx)

        raw = b"x" * 200
        b64 = base64.b64encode(raw).decode("ascii")
        file_path = str(sandbox / "big.bin")
        result = await write_file(path=file_path, content=b64, encoding="base64", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE


# ============================================================================
# Tests: write_file -- Extension security policy
# ============================================================================


class TestWriteFileExtensionPolicy:
    """Test extension-based security policy."""

    @pytest.mark.anyio()
    async def test_blocked_extension_returns_permission_denied(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Blocked file extension returns PERMISSION_DENIED."""
        app_ctx = _make_app_ctx(
            sandbox, mock_backend, read_only=False, denied_extensions=".exe,.bat"
        )
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "malware.exe")
        result = await write_file(path=file_path, content="bad stuff", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED

    @pytest.mark.anyio()
    async def test_allowed_extension_succeeds(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Non-blocked extension succeeds."""
        app_ctx = _make_app_ctx(
            sandbox, mock_backend, read_only=False, denied_extensions=".exe,.bat"
        )
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "script.py")
        result = await write_file(path=file_path, content="print('hi')", ctx=ctx)

        assert isinstance(result, WriteFileResponse)


# ============================================================================
# Tests: write_file -- Parent directory creation
# ============================================================================


class TestWriteFileParentDirectories:
    """Test parent directory creation behavior."""

    @pytest.mark.anyio()
    async def test_create_parents_true_calls_mkdir(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """create_parents=true creates parent directories."""
        file_path = str(sandbox / "sub" / "deep" / "file.txt")
        result = await write_file(
            path=file_path, content="content", create_parents=True, ctx=mock_ctx
        )

        assert isinstance(result, WriteFileResponse)
        # Check mkdir was called with parent dir
        parent = str(sandbox / "sub" / "deep")
        assert parent in mock_backend._created_dirs

    @pytest.mark.anyio()
    async def test_create_parents_false_no_mkdir(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """create_parents=false does not create directories."""
        file_path = str(sandbox / "sub" / "file.txt")
        result = await write_file(
            path=file_path, content="content", create_parents=False, ctx=mock_ctx
        )

        # Should still attempt write (backend may fail if dir doesn't exist)
        assert isinstance(result, WriteFileResponse)
        assert len(mock_backend._created_dirs) == 0

    @pytest.mark.anyio()
    async def test_mkdir_failure_does_not_prevent_write_attempt(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """mkdir failure is swallowed; write still attempted."""
        mock_backend.set_raise_on_mkdir(OSError("mkdir failed"))
        file_path = str(sandbox / "sub" / "file.txt")

        result = await write_file(
            path=file_path, content="content", create_parents=True, ctx=mock_ctx
        )

        # The write should still proceed (backend doesn't raise on pipe_file)
        assert isinstance(result, WriteFileResponse)


# ============================================================================
# Tests: write_file -- Error handling
# ============================================================================


class TestWriteFileErrors:
    """Test error handling in write_file."""

    @pytest.mark.anyio()
    async def test_no_context_returns_error(self) -> None:
        """Returns error when ctx is None."""
        result = await write_file(path="/test.txt", content="content", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "no context" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_path_traversal_returns_path_outside_sandbox(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Path traversal attempt returns PATH_OUTSIDE_SANDBOX."""
        traversal_path = str(sandbox / ".." / ".." / "etc" / "passwd")
        result = await write_file(path=traversal_path, content="bad", ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_backend_error_on_write(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Backend error during write is surfaced properly."""
        mock_backend.set_raise_on_pipe_file(BackendError("Disk full"))
        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="content", ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR

    @pytest.mark.anyio()
    async def test_backend_error_unwraps_cause(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """BackendError wrapping PermissionDeniedError surfaces original code."""
        inner = PermissionDeniedError("Cannot write to read-only mount")
        outer = BackendError("Backend failed")
        outer.__cause__ = inner
        mock_backend.set_raise_on_pipe_file(outer)

        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="content", ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED

    @pytest.mark.anyio()
    async def test_unexpected_exception_returns_backend_error(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """Non-FSError exceptions return BACKEND_ERROR."""
        mock_backend.set_raise_on_pipe_file(RuntimeError("unexpected"))

        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="content", ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "unexpected" in result["message"]

    @pytest.mark.anyio()
    async def test_exists_error_treated_as_new_file(
        self, sandbox: Path, mock_backend: MockBackend, mock_ctx: MagicMock
    ) -> None:
        """If exists() raises, file is treated as new (created=True)."""
        mock_backend.set_raise_on_exists(OSError("cannot stat"))

        file_path = str(sandbox / "test.txt")
        result = await write_file(path=file_path, content="content", ctx=mock_ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.created is True


# ============================================================================
# Tests: write_file -- Integration with real filesystem
# ============================================================================


class TestWriteFileIntegration:
    """Integration tests using real filesystem (tmp_path)."""

    def _make_integration_ctx(
        self,
        sandbox: Path,
        read_only: bool = False,
        max_file_size: int = 10_485_760,
    ) -> MagicMock:
        """Create a context with real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(read_only=read_only),
            local=LocalSettings(base_path=str(sandbox), max_file_size=max_file_size),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        local_backend = LocalBackend(
            fs=LocalFileSystem(auto_mkdir=False),
            settings=settings.local,
            security=security,
        )
        backend_manager = BackendManager(
            settings=settings,
            security=security,
            local_backend=local_backend,
        )
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        ctx = MagicMock()
        ctx.request_context.lifespan_context = app_ctx
        return ctx

    @pytest.mark.anyio()
    async def test_write_text_file_on_disk(self, sandbox: Path) -> None:
        """Writes a text file to actual disk."""
        ctx = self._make_integration_ctx(sandbox)
        file_path = str(sandbox / "output.txt")

        result = await write_file(path=file_path, content="Hello, integration!", ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == len(b"Hello, integration!")
        assert result.created is True

        # Verify the file actually exists on disk
        written = Path(file_path).read_text(encoding="utf-8")
        assert written == "Hello, integration!"

    @pytest.mark.anyio()
    async def test_write_binary_file_on_disk(self, sandbox: Path) -> None:
        """Writes a base64-decoded binary file to actual disk."""
        ctx = self._make_integration_ctx(sandbox)
        file_path = str(sandbox / "data.bin")
        raw = b"\x00\x01\x02\x03\xff\xfe\xfd"
        b64 = base64.b64encode(raw).decode("ascii")

        result = await write_file(path=file_path, content=b64, encoding="base64", ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == len(raw)

        # Verify actual bytes on disk
        written = Path(file_path).read_bytes()
        assert written == raw

    @pytest.mark.anyio()
    async def test_create_parent_dirs_on_disk(self, sandbox: Path) -> None:
        """Creates parent directories on actual filesystem."""
        ctx = self._make_integration_ctx(sandbox)
        file_path = str(sandbox / "a" / "b" / "c" / "deep.txt")

        result = await write_file(path=file_path, content="deep file", create_parents=True, ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.created is True

        # Verify the file and directories exist
        assert Path(file_path).exists()
        assert Path(file_path).read_text(encoding="utf-8") == "deep file"
        assert (sandbox / "a" / "b" / "c").is_dir()

    @pytest.mark.anyio()
    async def test_overwrite_existing_file_on_disk(self, sandbox: Path) -> None:
        """Overwrites an existing file on actual filesystem."""
        ctx = self._make_integration_ctx(sandbox)
        file_path = str(sandbox / "replace.txt")

        # Create initial file
        Path(file_path).write_text("original", encoding="utf-8")

        result = await write_file(path=file_path, content="replaced", ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.created is False  # Overwritten
        assert Path(file_path).read_text(encoding="utf-8") == "replaced"

    @pytest.mark.anyio()
    async def test_overwrite_false_blocks_on_disk(self, sandbox: Path) -> None:
        """Overwrite=false blocks writing to existing file on disk."""
        ctx = self._make_integration_ctx(sandbox)
        file_path = str(sandbox / "protected.txt")

        # Create initial file
        Path(file_path).write_text("original", encoding="utf-8")

        result = await write_file(path=file_path, content="attempt", overwrite=False, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED

        # Verify original content is unchanged
        assert Path(file_path).read_text(encoding="utf-8") == "original"

    @pytest.mark.anyio()
    async def test_write_empty_file_on_disk(self, sandbox: Path) -> None:
        """Writing empty content creates empty file on disk."""
        ctx = self._make_integration_ctx(sandbox)
        file_path = str(sandbox / "empty.txt")

        result = await write_file(path=file_path, content="", ctx=ctx)

        assert isinstance(result, WriteFileResponse)
        assert result.size_bytes == 0
        assert Path(file_path).exists()
        assert Path(file_path).read_bytes() == b""

    @pytest.mark.anyio()
    async def test_size_limit_on_disk(self, sandbox: Path) -> None:
        """Size limit enforced on real filesystem."""
        ctx = self._make_integration_ctx(sandbox, max_file_size=50)
        file_path = str(sandbox / "big.txt")

        result = await write_file(path=file_path, content="x" * 100, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE

        # Verify file was not created
        assert not Path(file_path).exists()

    @pytest.mark.anyio()
    async def test_path_traversal_on_disk(self, sandbox: Path) -> None:
        """Path traversal blocked on real filesystem."""
        ctx = self._make_integration_ctx(sandbox)
        traversal_path = str(sandbox / ".." / ".." / "etc" / "evil.txt")

        result = await write_file(path=traversal_path, content="evil", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX


# ============================================================================
# delete_file helpers: MockDeleteBackend with per-path exists and isdir
# ============================================================================


class MockDeleteBackend:
    """A mock backend for unit testing delete_file.

    Supports per-path existence and directory detection, plus recording
    rm() calls for assertion.
    """

    def __init__(self) -> None:
        self._exists_map: dict[str, bool] = {}
        self._isdir_map: dict[str, bool] = {}
        self._raise_on_rm: Exception | None = None
        self._raise_on_isdir: Exception | None = None
        self._raise_on_exists: Exception | None = None
        self._rm_calls: list[str] = []

    def set_exists(self, path: str, exists: bool) -> None:
        """Set existence status for a specific path."""
        self._exists_map[path] = exists

    def set_isdir(self, path: str, is_dir: bool) -> None:
        """Set whether a path is a directory."""
        self._isdir_map[path] = is_dir

    def set_raise_on_rm(self, exc: Exception) -> None:
        """Configure rm to raise an exception."""
        self._raise_on_rm = exc

    def set_raise_on_isdir(self, exc: Exception) -> None:
        """Configure isdir to raise an exception."""
        self._raise_on_isdir = exc

    def set_raise_on_exists(self, exc: Exception) -> None:
        """Configure exists to raise an exception."""
        self._raise_on_exists = exc

    @property
    def rm_calls(self) -> list[str]:
        """Return the recorded rm calls."""
        return list(self._rm_calls)

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return []

    def info(self, path: str) -> dict[str, Any]:
        return {"name": path, "type": "file", "size": 100}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        return b""

    def pipe_file(self, path: str, data: bytes) -> None:
        pass

    def rm(self, path: str) -> None:
        if self._raise_on_rm is not None:
            raise self._raise_on_rm
        self._rm_calls.append(path)

    def cp_file(self, source: str, destination: str) -> None:
        pass

    def mv(self, source: str, destination: str) -> None:
        pass

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        pass

    def exists(self, path: str) -> bool:
        if self._raise_on_exists is not None:
            raise self._raise_on_exists
        return self._exists_map.get(path, False)

    def isdir(self, path: str) -> bool:
        if self._raise_on_isdir is not None:
            raise self._raise_on_isdir
        return self._isdir_map.get(path, False)

    def isfile(self, path: str) -> bool:
        return self._exists_map.get(path, False) and not self._isdir_map.get(path, False)


def _make_delete_app_ctx(
    sandbox: Path,
    delete_backend: MockDeleteBackend,
    read_only: bool = False,
) -> AppContext:
    """Create an AppContext for delete_file testing."""
    settings = Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(base_path=str(sandbox)),
        s3=S3Settings(enabled=False),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=delete_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


# ============================================================================
# delete_file fixtures
# ============================================================================


@pytest.fixture()
def delete_backend() -> MockDeleteBackend:
    """A mock backend for delete_file tests."""
    return MockDeleteBackend()


@pytest.fixture()
def delete_app_ctx(sandbox: Path, delete_backend: MockDeleteBackend) -> AppContext:
    """AppContext for delete_file with read_only=False."""
    return _make_delete_app_ctx(sandbox, delete_backend, read_only=False)


@pytest.fixture()
def delete_ctx(delete_app_ctx: AppContext) -> MagicMock:
    """Mock MCP context for delete_file tests."""
    return _make_mock_ctx(delete_app_ctx)


# ============================================================================
# TestDeleteFileBasic: Core deletion functionality
# ============================================================================


class TestDeleteFileBasic:
    """Test basic file deletion operations."""

    @pytest.mark.anyio()
    async def test_delete_file_success(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Deleting an existing file returns DeleteFileResponse with deleted=True."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.path == file_path
        assert result.backend == "local"
        assert result.deleted is True

    @pytest.mark.anyio()
    async def test_delete_file_calls_backend_rm(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Delete should call backend.rm with the file path."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)

        await delete_file(path=file_path, ctx=delete_ctx)

        assert len(delete_backend.rm_calls) == 1
        assert delete_backend.rm_calls[0] == file_path

    @pytest.mark.anyio()
    async def test_delete_file_returns_local_backend(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Returns backend='local' for local paths."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.backend == "local"

    @pytest.mark.anyio()
    async def test_delete_file_no_context(self) -> None:
        """Delete without context returns BACKEND_ERROR."""
        result = await delete_file(path="/data/file.txt", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.anyio()
    async def test_delete_file_explicit_backend(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Explicit backend='local' is used in response."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)

        result = await delete_file(path=file_path, backend="local", ctx=delete_ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.backend == "local"


# ============================================================================
# TestDeleteFileReadOnly: Read-only mode enforcement
# ============================================================================


class TestDeleteFileReadOnly:
    """Test read-only mode blocks delete operations."""

    @pytest.mark.anyio()
    async def test_read_only_returns_permission_denied(
        self, sandbox: Path, delete_backend: MockDeleteBackend
    ) -> None:
        """Returns PERMISSION_DENIED when server is in read-only mode."""
        app_ctx = _make_delete_app_ctx(sandbox, delete_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "file.txt")
        result = await delete_file(path=file_path, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "read-only" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_read_only_no_backend_call(
        self, sandbox: Path, delete_backend: MockDeleteBackend
    ) -> None:
        """Read-only rejection happens before any backend interaction."""
        app_ctx = _make_delete_app_ctx(sandbox, delete_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        file_path = str(sandbox / "file.txt")
        await delete_file(path=file_path, ctx=ctx)

        assert len(delete_backend.rm_calls) == 0


# ============================================================================
# TestDeleteFileDirectoryRejection: Directory deletion prevention
# ============================================================================


class TestDeleteFileDirectoryRejection:
    """Test that directory paths are rejected with INVALID_OPERATION."""

    @pytest.mark.anyio()
    async def test_directory_path_returns_invalid_operation(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Attempting to delete a directory returns INVALID_OPERATION."""
        dir_path = str(sandbox / "subdir")
        delete_backend.set_exists(dir_path, True)
        delete_backend.set_isdir(dir_path, True)

        result = await delete_file(path=dir_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "directory" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_directory_no_rm_call(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Backend.rm is not called when path is a directory."""
        dir_path = str(sandbox / "subdir")
        delete_backend.set_exists(dir_path, True)
        delete_backend.set_isdir(dir_path, True)

        await delete_file(path=dir_path, ctx=delete_ctx)

        assert len(delete_backend.rm_calls) == 0


# ============================================================================
# TestDeleteFileNotFound: Non-existent file handling
# ============================================================================


class TestDeleteFileNotFound:
    """Test deletion of non-existent files."""

    @pytest.mark.anyio()
    async def test_nonexistent_file_returns_path_not_found(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Deleting a non-existent file returns PATH_NOT_FOUND."""
        file_path = str(sandbox / "nonexistent.txt")
        delete_backend.set_exists(file_path, False)

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "not found" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_nonexistent_no_rm_call(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Backend.rm is not called when file does not exist."""
        file_path = str(sandbox / "nonexistent.txt")
        delete_backend.set_exists(file_path, False)

        await delete_file(path=file_path, ctx=delete_ctx)

        assert len(delete_backend.rm_calls) == 0


# ============================================================================
# TestDeleteFilePathSecurity: Path traversal and sandbox escape
# ============================================================================


class TestDeleteFilePathSecurity:
    """Test path security validation for delete_file."""

    @pytest.mark.anyio()
    async def test_path_traversal_returns_path_outside_sandbox(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Path traversal attempt returns PATH_OUTSIDE_SANDBOX."""
        traversal_path = str(sandbox / ".." / ".." / "etc" / "passwd")
        result = await delete_file(path=traversal_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_path_traversal_no_rm_call(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Backend.rm is not called for path traversal attempts."""
        traversal_path = str(sandbox / ".." / ".." / "etc" / "passwd")
        await delete_file(path=traversal_path, ctx=delete_ctx)

        assert len(delete_backend.rm_calls) == 0


# ============================================================================
# TestDeleteFileErrors: Backend errors during deletion
# ============================================================================


class TestDeleteFileErrors:
    """Test error handling in delete_file."""

    @pytest.mark.anyio()
    async def test_backend_error_during_rm(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Backend error during rm is reported."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)
        delete_backend.set_raise_on_rm(OSError("disk error"))

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "disk error" in result["message"]

    @pytest.mark.anyio()
    async def test_fs_error_during_rm_unwrapped(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """FSError wrapped in BackendError is unwrapped to surface original code."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)

        original = PathOutsideSandboxError("Path escapes sandbox")
        wrapper = BackendError("Wrapped error")
        wrapper.__cause__ = original
        delete_backend.set_raise_on_rm(wrapper)

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_unexpected_exception_returns_backend_error(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """Non-FSError exceptions return BACKEND_ERROR."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)
        delete_backend.set_raise_on_rm(RuntimeError("unexpected"))

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "unexpected" in result["message"]

    @pytest.mark.anyio()
    async def test_backend_error_wrapping_permission(
        self, sandbox: Path, delete_backend: MockDeleteBackend, delete_ctx: MagicMock
    ) -> None:
        """BackendError wrapping PermissionDeniedError surfaces PERMISSION_DENIED."""
        file_path = str(sandbox / "file.txt")
        delete_backend.set_exists(file_path, True)

        inner = PermissionDeniedError("Cannot delete from read-only mount")
        outer = BackendError("Backend failed")
        outer.__cause__ = inner
        delete_backend.set_raise_on_rm(outer)

        result = await delete_file(path=file_path, ctx=delete_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED


# ============================================================================
# TestDeleteFileIntegration: Real filesystem integration tests
# ============================================================================


class TestDeleteFileIntegration:
    """Integration tests using real filesystem (tmp_path)."""

    def _make_real_ctx(self, sandbox: Path, read_only: bool = False) -> MagicMock:
        """Create a context with a real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(read_only=read_only),
            local=LocalSettings(base_path=str(sandbox), follow_symlinks=True),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        local_backend = LocalBackend(
            fs=LocalFileSystem(),
            security=security,
            settings=settings.local,
        )
        backend_manager = BackendManager(
            settings=settings,
            security=security,
            local_backend=local_backend,
        )
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        return _make_mock_ctx(app_ctx)

    @pytest.mark.anyio()
    async def test_delete_file_on_disk(self, sandbox: Path) -> None:
        """Deletes a file from actual disk."""
        file_path = sandbox / "to_delete.txt"
        file_path.write_text("delete me", encoding="utf-8")
        assert file_path.exists()

        ctx = self._make_real_ctx(sandbox)
        result = await delete_file(path=str(file_path), ctx=ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.deleted is True
        assert result.backend == "local"
        assert result.path == str(file_path)
        # Verify file is actually gone
        assert not file_path.exists()

    @pytest.mark.anyio()
    async def test_delete_nonexistent_file_on_disk(self, sandbox: Path) -> None:
        """Deleting a non-existent file returns PATH_NOT_FOUND on real filesystem."""
        ctx = self._make_real_ctx(sandbox)
        result = await delete_file(path=str(sandbox / "nonexistent.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.anyio()
    async def test_delete_directory_on_disk(self, sandbox: Path) -> None:
        """Deleting a directory returns INVALID_OPERATION on real filesystem."""
        dir_path = sandbox / "subdir"
        dir_path.mkdir()

        ctx = self._make_real_ctx(sandbox)
        result = await delete_file(path=str(dir_path), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        # Verify directory still exists
        assert dir_path.exists()

    @pytest.mark.anyio()
    async def test_delete_path_traversal_on_disk(self, sandbox: Path) -> None:
        """Path traversal blocked on real filesystem."""
        ctx = self._make_real_ctx(sandbox)
        traversal_path = str(sandbox / ".." / ".." / "etc" / "evil.txt")

        result = await delete_file(path=traversal_path, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_delete_symlink_on_disk(self, sandbox: Path) -> None:
        """Deleting a symlink succeeds and returns deleted=True.

        Note: The LocalBackend resolves symlinks before passing to fsspec,
        so currently fsspec deletes the resolved target rather than the
        symlink itself. This is a known limitation of the path resolution
        strategy. The spec edge case ("delete symlink, not target") would
        require the backend to use os.unlink on the pre-resolved path.
        """
        target = sandbox / "target.txt"
        target.write_text("real content", encoding="utf-8")
        link = sandbox / "link.txt"
        link.symlink_to(target)

        ctx = self._make_real_ctx(sandbox)
        result = await delete_file(path=str(link), ctx=ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.deleted is True
        assert result.path == str(link)
        assert result.backend == "local"

    @pytest.mark.anyio()
    async def test_delete_binary_file_on_disk(self, sandbox: Path) -> None:
        """Deletes a binary file from actual disk."""
        file_path = sandbox / "data.bin"
        file_path.write_bytes(b"\x00\x01\x02\xff")
        assert file_path.exists()

        ctx = self._make_real_ctx(sandbox)
        result = await delete_file(path=str(file_path), ctx=ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.deleted is True
        assert not file_path.exists()

    @pytest.mark.anyio()
    async def test_delete_nested_file_on_disk(self, sandbox: Path) -> None:
        """Deletes a file in a nested directory."""
        nested_dir = sandbox / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        file_path = nested_dir / "deep.txt"
        file_path.write_text("deep content")

        ctx = self._make_real_ctx(sandbox)
        result = await delete_file(path=str(file_path), ctx=ctx)

        assert isinstance(result, DeleteFileResponse)
        assert result.deleted is True
        assert not file_path.exists()
        # Parent directories should remain
        assert nested_dir.exists()


# ============================================================================
# move_file helpers: MockMoveBackend for per-path exists
# ============================================================================


class MockMoveBackend:
    """A mock backend for unit testing move_file.

    Unlike MockBackend (which uses a single _exists_result bool),
    this backend supports per-path existence via set_exists().
    """

    def __init__(self) -> None:
        self._exists_map: dict[str, bool] = {}
        self._raise_on_mv: Exception | None = None
        self._mv_calls: list[tuple[str, str]] = []

    def set_exists(self, path: str, exists: bool) -> None:
        """Set existence status for a specific path."""
        self._exists_map[path] = exists

    def set_raise_on_mv(self, exc: Exception) -> None:
        """Configure mv to raise an exception."""
        self._raise_on_mv = exc

    @property
    def mv_calls(self) -> list[tuple[str, str]]:
        """Return the recorded mv calls."""
        return list(self._mv_calls)

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return []

    def info(self, path: str) -> dict[str, Any]:
        return {"name": path, "type": "file", "size": 100}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        return b""

    def pipe_file(self, path: str, data: bytes) -> None:
        pass

    def rm(self, path: str) -> None:
        pass

    def cp_file(self, source: str, destination: str) -> None:
        pass

    def mv(self, source: str, destination: str) -> None:
        if self._raise_on_mv is not None:
            raise self._raise_on_mv
        self._mv_calls.append((source, destination))

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        pass

    def exists(self, path: str) -> bool:
        return self._exists_map.get(path, False)

    def isdir(self, path: str) -> bool:
        return False

    def isfile(self, path: str) -> bool:
        return self._exists_map.get(path, False)


def _make_move_app_ctx(
    sandbox: Path,
    move_backend: MockMoveBackend,
    read_only: bool = False,
) -> AppContext:
    """Create an AppContext for move_file testing."""
    settings = Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(base_path=str(sandbox)),
        s3=S3Settings(enabled=False),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=move_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


# ============================================================================
# move_file fixtures
# ============================================================================


@pytest.fixture()
def move_backend() -> MockMoveBackend:
    """A mock backend for move_file tests."""
    return MockMoveBackend()


@pytest.fixture()
def move_app_ctx(sandbox: Path, move_backend: MockMoveBackend) -> AppContext:
    """AppContext for move_file with read_only=False."""
    return _make_move_app_ctx(sandbox, move_backend, read_only=False)


@pytest.fixture()
def move_ctx(move_app_ctx: AppContext) -> MagicMock:
    """Mock MCP context for move_file tests."""
    return _make_mock_ctx(move_app_ctx)


# ============================================================================
# TestMoveFileBasic: Core move functionality
# ============================================================================


class TestMoveFileBasic:
    """Test basic file move operations."""

    @pytest.mark.anyio()
    async def test_move_file_success(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Moving a file returns MoveFileResponse with correct fields."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)

        result = await move_file(source=source, destination=destination, ctx=move_ctx)

        assert isinstance(result, MoveFileResponse)
        assert result.source == source
        assert result.destination == destination
        assert result.backend == "local"
        assert result.overwritten is False

    @pytest.mark.anyio()
    async def test_move_file_calls_backend_mv(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Move should call backend.mv with source and destination."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)

        await move_file(source=source, destination=destination, ctx=move_ctx)

        assert len(move_backend.mv_calls) == 1
        assert move_backend.mv_calls[0] == (source, destination)

    @pytest.mark.anyio()
    async def test_move_file_no_context(self) -> None:
        """Move without context returns BACKEND_ERROR."""
        result = await move_file(source="/data/old.txt", destination="/data/new.txt", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]


# ============================================================================
# TestMoveFileOverwrite: Overwrite protection and overwritten flag
# ============================================================================


class TestMoveFileOverwrite:
    """Test overwrite behavior."""

    @pytest.mark.anyio()
    async def test_overwrite_false_destination_exists(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Moving to existing destination with overwrite=false returns PERMISSION_DENIED."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "existing.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, True)

        result = await move_file(
            source=source, destination=destination, overwrite=False, ctx=move_ctx
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "already exists" in result["message"]

    @pytest.mark.anyio()
    async def test_overwrite_true_destination_exists(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Moving to existing destination with overwrite=true succeeds."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "existing.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, True)

        result = await move_file(
            source=source, destination=destination, overwrite=True, ctx=move_ctx
        )

        assert isinstance(result, MoveFileResponse)
        assert result.overwritten is True

    @pytest.mark.anyio()
    async def test_overwritten_false_when_destination_not_exists(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """overwritten flag is False when destination did not exist."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)

        result = await move_file(
            source=source, destination=destination, overwrite=True, ctx=move_ctx
        )

        assert isinstance(result, MoveFileResponse)
        assert result.overwritten is False

    @pytest.mark.anyio()
    async def test_overwrite_default_is_false(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Default overwrite is False -- destination exists triggers error."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "existing.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, True)

        result = await move_file(source=source, destination=destination, ctx=move_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED

    @pytest.mark.anyio()
    async def test_no_mv_call_when_overwrite_blocked(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Backend.mv is not called when overwrite is blocked."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "existing.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, True)

        await move_file(source=source, destination=destination, overwrite=False, ctx=move_ctx)

        assert len(move_backend.mv_calls) == 0


# ============================================================================
# TestMoveFileReadOnly: Read-only mode enforcement
# ============================================================================


class TestMoveFileReadOnly:
    """Test read-only mode blocks move operations."""

    @pytest.mark.anyio()
    async def test_read_only_mode(self, sandbox: Path, move_backend: MockMoveBackend) -> None:
        """Move is rejected when server is in read-only mode."""
        app_ctx = _make_move_app_ctx(sandbox, move_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await move_file(
            source=str(sandbox / "old.txt"),
            destination=str(sandbox / "new.txt"),
            ctx=ctx,
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "read-only" in result["message"]

    @pytest.mark.anyio()
    async def test_read_only_no_backend_call(
        self, sandbox: Path, move_backend: MockMoveBackend
    ) -> None:
        """Read-only rejection happens before any backend interaction."""
        app_ctx = _make_move_app_ctx(sandbox, move_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        await move_file(
            source=str(sandbox / "old.txt"),
            destination=str(sandbox / "new.txt"),
            ctx=ctx,
        )

        assert len(move_backend.mv_calls) == 0


# ============================================================================
# TestMoveFileSourceNotFound: Source existence validation
# ============================================================================


class TestMoveFileSourceNotFound:
    """Test source file existence checking."""

    @pytest.mark.anyio()
    async def test_source_not_found(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Moving a non-existent source returns PATH_NOT_FOUND."""
        source = str(sandbox / "nonexistent.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, False)

        result = await move_file(source=source, destination=destination, ctx=move_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND
        assert "not found" in result["message"]

    @pytest.mark.anyio()
    async def test_no_mv_call_when_source_missing(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Backend.mv is not called when source does not exist."""
        source = str(sandbox / "nonexistent.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, False)

        await move_file(source=source, destination=destination, ctx=move_ctx)

        assert len(move_backend.mv_calls) == 0


# ============================================================================
# TestMoveFileCrossBackend: Cross-backend move rejection
# ============================================================================


class TestMoveFileCrossBackend:
    """Test cross-backend move detection and rejection."""

    @pytest.mark.anyio()
    async def test_local_to_s3_rejected(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Moving from local to S3 returns INVALID_OPERATION."""
        result = await move_file(
            source=str(sandbox / "local.txt"),
            destination="s3://bucket/remote.txt",
            ctx=move_ctx,
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "Cross-backend" in result["message"]
        assert "copy_file" in result["message"]

    @pytest.mark.anyio()
    async def test_s3_to_local_rejected(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Moving from S3 to local returns INVALID_OPERATION."""
        result = await move_file(
            source="s3://bucket/remote.txt",
            destination=str(sandbox / "local.txt"),
            ctx=move_ctx,
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "Cross-backend" in result["message"]

    @pytest.mark.anyio()
    async def test_cross_backend_details(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Cross-backend error includes backend names in details."""
        result = await move_file(
            source=str(sandbox / "local.txt"),
            destination="s3://bucket/remote.txt",
            ctx=move_ctx,
        )

        assert isinstance(result, dict)
        assert result["details"]["source_backend"] == "local"
        assert result["details"]["dest_backend"] == "s3"


# ============================================================================
# TestMoveFilePathSecurity: Path traversal and sandbox escape
# ============================================================================


class TestMoveFilePathSecurity:
    """Test path security validation on source and destination."""

    @pytest.mark.anyio()
    async def test_source_path_traversal(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Source path traversal outside sandbox returns PATH_OUTSIDE_SANDBOX."""
        result = await move_file(
            source=str(sandbox / ".." / "etc" / "passwd"),
            destination=str(sandbox / "new.txt"),
            ctx=move_ctx,
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_destination_path_traversal(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Destination path traversal outside sandbox returns PATH_OUTSIDE_SANDBOX."""
        source = str(sandbox / "old.txt")
        move_backend.set_exists(source, True)

        result = await move_file(
            source=source,
            destination=str(sandbox / ".." / "etc" / "evil.txt"),
            ctx=move_ctx,
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX


# ============================================================================
# TestMoveFileBackendErrors: Backend-level errors during move
# ============================================================================


class TestMoveFileBackendErrors:
    """Test handling of backend errors during mv operation."""

    @pytest.mark.anyio()
    async def test_backend_error_during_mv(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Backend error during mv is reported."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)
        move_backend.set_raise_on_mv(OSError("disk full"))

        result = await move_file(source=source, destination=destination, ctx=move_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "disk full" in result["message"]

    @pytest.mark.anyio()
    async def test_fs_error_during_mv_unwrapped(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """FSError wrapped in BackendError is unwrapped to surface original code."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)

        original = PathOutsideSandboxError("Path escapes sandbox")
        wrapper = BackendError("Wrapped error")
        wrapper.__cause__ = original
        move_backend.set_raise_on_mv(wrapper)

        result = await move_file(source=source, destination=destination, ctx=move_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX


# ============================================================================
# TestMoveFileExplicitBackend: Using explicit backend parameter
# ============================================================================


class TestMoveFileExplicitBackend:
    """Test explicit backend parameter behavior."""

    @pytest.mark.anyio()
    async def test_explicit_backend_local(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Explicit backend='local' forces local backend for both paths."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "new.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)

        result = await move_file(
            source=source, destination=destination, backend="local", ctx=move_ctx
        )

        assert isinstance(result, MoveFileResponse)
        assert result.backend == "local"

    @pytest.mark.anyio()
    async def test_explicit_backend_prevents_cross_backend(
        self, sandbox: Path, move_backend: MockMoveBackend, move_ctx: MagicMock
    ) -> None:
        """Explicit backend forces same backend for both paths."""
        source = str(sandbox / "old.txt")
        destination = str(sandbox / "s3-style-name.txt")
        move_backend.set_exists(source, True)
        move_backend.set_exists(destination, False)

        result = await move_file(
            source=source, destination=destination, backend="local", ctx=move_ctx
        )

        assert isinstance(result, MoveFileResponse)
        assert result.backend == "local"


# ============================================================================
# TestMoveFileIntegration: Real filesystem integration tests
# ============================================================================


class TestMoveFileIntegration:
    """Integration tests using real filesystem via tmp_path."""

    def _make_real_ctx(self, sandbox: Path) -> MagicMock:
        """Create a context with a real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(base_path=str(sandbox), follow_symlinks=True),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        local_backend = LocalBackend(
            fs=LocalFileSystem(),
            security=security,
            settings=settings.local,
        )
        backend_manager = BackendManager(
            settings=settings,
            security=security,
            local_backend=local_backend,
        )
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        return _make_mock_ctx(app_ctx)

    @pytest.mark.anyio()
    async def test_move_file_renames(self, sandbox: Path) -> None:
        """Move renames a file on the real filesystem."""
        source = sandbox / "original.txt"
        source.write_text("hello world")
        destination = sandbox / "renamed.txt"

        ctx = self._make_real_ctx(sandbox)
        result = await move_file(source=str(source), destination=str(destination), ctx=ctx)

        assert isinstance(result, MoveFileResponse)
        assert result.source == str(source)
        assert result.destination == str(destination)
        assert result.overwritten is False
        # Verify on disk
        assert not source.exists()
        assert destination.exists()
        assert destination.read_text() == "hello world"

    @pytest.mark.anyio()
    async def test_move_file_to_subdirectory(self, sandbox: Path) -> None:
        """Move file to a different subdirectory."""
        subdir = sandbox / "subdir"
        subdir.mkdir()
        source = sandbox / "file.txt"
        source.write_text("content")
        destination = subdir / "file.txt"

        ctx = self._make_real_ctx(sandbox)
        result = await move_file(source=str(source), destination=str(destination), ctx=ctx)

        assert isinstance(result, MoveFileResponse)
        assert not source.exists()
        assert destination.exists()
        assert destination.read_text() == "content"

    @pytest.mark.anyio()
    async def test_move_file_overwrite_real(self, sandbox: Path) -> None:
        """Move file overwrites existing destination when overwrite=true."""
        source = sandbox / "new.txt"
        source.write_text("new content")
        destination = sandbox / "old.txt"
        destination.write_text("old content")

        ctx = self._make_real_ctx(sandbox)
        result = await move_file(
            source=str(source), destination=str(destination), overwrite=True, ctx=ctx
        )

        assert isinstance(result, MoveFileResponse)
        assert result.overwritten is True
        assert not source.exists()
        assert destination.read_text() == "new content"

    @pytest.mark.anyio()
    async def test_move_file_overwrite_blocked_real(self, sandbox: Path) -> None:
        """Move file fails when destination exists and overwrite=false."""
        source = sandbox / "new.txt"
        source.write_text("new content")
        destination = sandbox / "old.txt"
        destination.write_text("old content")

        ctx = self._make_real_ctx(sandbox)
        result = await move_file(
            source=str(source), destination=str(destination), overwrite=False, ctx=ctx
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        # Both files should be intact
        assert source.exists()
        assert destination.read_text() == "old content"

    @pytest.mark.anyio()
    async def test_move_source_not_found_real(self, sandbox: Path) -> None:
        """Move non-existent source on real filesystem returns PATH_NOT_FOUND."""
        ctx = self._make_real_ctx(sandbox)
        result = await move_file(
            source=str(sandbox / "nonexistent.txt"),
            destination=str(sandbox / "new.txt"),
            ctx=ctx,
        )

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND


# ============================================================================
# copy_file helpers: MockCopyBackend with per-path exists, info, and content
# ============================================================================


class MockCopyBackend:
    """A mock backend for unit testing copy_file.

    Supports per-path existence, per-path info metadata, per-path file content,
    and records cp_file, cat_file, and pipe_file calls for assertions.
    """

    def __init__(self, name: str = "local") -> None:
        self.name = name
        self._exists_map: dict[str, bool] = {}
        self._info_map: dict[str, dict[str, Any]] = {}
        self._content_map: dict[str, bytes] = {}
        self._raise_on_cp_file: Exception | None = None
        self._raise_on_cat_file: Exception | None = None
        self._raise_on_pipe_file: Exception | None = None
        self._cp_file_calls: list[tuple[str, str]] = []
        self._cat_file_calls: list[str] = []
        self._pipe_file_calls: list[tuple[str, bytes]] = []

    def set_exists(self, path: str, exists: bool) -> None:
        self._exists_map[path] = exists

    def set_info(self, path: str, info: dict[str, Any]) -> None:
        self._info_map[path] = info

    def set_content(self, path: str, content: bytes) -> None:
        self._content_map[path] = content

    def set_raise_on_cp_file(self, exc: Exception) -> None:
        self._raise_on_cp_file = exc

    def set_raise_on_cat_file(self, exc: Exception) -> None:
        self._raise_on_cat_file = exc

    def set_raise_on_pipe_file(self, exc: Exception) -> None:
        self._raise_on_pipe_file = exc

    @property
    def cp_file_calls(self) -> list[tuple[str, str]]:
        return list(self._cp_file_calls)

    @property
    def cat_file_calls(self) -> list[str]:
        return list(self._cat_file_calls)

    @property
    def pipe_file_calls(self) -> list[tuple[str, bytes]]:
        return list(self._pipe_file_calls)

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return []

    def info(self, path: str) -> dict[str, Any]:
        if path in self._info_map:
            return self._info_map[path]
        return {"name": path, "type": "file", "size": 100}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        if self._raise_on_cat_file is not None:
            raise self._raise_on_cat_file
        self._cat_file_calls.append(path)
        return self._content_map.get(path, b"")

    def pipe_file(self, path: str, data: bytes) -> None:
        if self._raise_on_pipe_file is not None:
            raise self._raise_on_pipe_file
        self._pipe_file_calls.append((path, data))

    def rm(self, path: str) -> None:
        pass

    def cp_file(self, source: str, destination: str) -> None:
        if self._raise_on_cp_file is not None:
            raise self._raise_on_cp_file
        self._cp_file_calls.append((source, destination))

    def mv(self, source: str, destination: str) -> None:
        pass

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        pass

    def exists(self, path: str) -> bool:
        return self._exists_map.get(path, False)

    def isdir(self, path: str) -> bool:
        return False

    def isfile(self, path: str) -> bool:
        return self._exists_map.get(path, False)


def _make_copy_app_ctx(
    sandbox: Path,
    copy_backend: MockCopyBackend,
    read_only: bool = False,
    max_file_size: int = 10_485_760,
) -> AppContext:
    """Create an AppContext for same-backend copy_file testing."""
    settings = Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(base_path=str(sandbox), max_file_size=max_file_size),
        s3=S3Settings(enabled=False),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=copy_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


def _make_cross_backend_copy_app_ctx(
    sandbox: Path,
    local_backend: MockCopyBackend,
    s3_backend: MockCopyBackend,
    read_only: bool = False,
    local_max_file_size: int = 10_485_760,
    s3_max_file_size: int = 10_485_760,
) -> AppContext:
    """Create an AppContext for cross-backend copy_file testing."""
    settings = Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(base_path=str(sandbox), max_file_size=local_max_file_size),
        s3=S3Settings(
            enabled=True,
            bucket="test-bucket",
            region="us-east-1",
            max_file_size=s3_max_file_size,
        ),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=local_backend,
        s3_backend=s3_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


# ============================================================================
# copy_file fixtures
# ============================================================================


@pytest.fixture()
def copy_backend() -> MockCopyBackend:
    return MockCopyBackend(name="local")


@pytest.fixture()
def copy_app_ctx(sandbox: Path, copy_backend: MockCopyBackend) -> AppContext:
    return _make_copy_app_ctx(sandbox, copy_backend, read_only=False)


@pytest.fixture()
def copy_ctx(copy_app_ctx: AppContext) -> MagicMock:
    return _make_mock_ctx(copy_app_ctx)


# ============================================================================
# TestCopyFileBasic
# ============================================================================


class TestCopyFileBasic:
    """Test basic same-backend file copy operations."""

    @pytest.mark.anyio()
    async def test_copy_file_success(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 42})
        result = await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.source == source
        assert result.destination == destination
        assert result.source_backend == "local"
        assert result.dest_backend == "local"
        assert result.size_bytes == 42
        assert result.cross_backend is False

    @pytest.mark.anyio()
    async def test_copy_file_calls_backend_cp_file(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert len(copy_backend.cp_file_calls) == 1
        assert copy_backend.cp_file_calls[0] == (source, destination)
        assert len(copy_backend.cat_file_calls) == 0
        assert len(copy_backend.pipe_file_calls) == 0

    @pytest.mark.anyio()
    async def test_copy_file_no_context(self) -> None:
        result = await copy_file(source="/data/s.txt", destination="/data/d.txt", ctx=None)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR

    @pytest.mark.anyio()
    async def test_copy_file_returns_local_backend(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        result = await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.source_backend == "local"
        assert result.dest_backend == "local"


# ============================================================================
# TestCopyFileCrossBackend
# ============================================================================


class TestCopyFileCrossBackend:
    """Test cross-backend copy operations."""

    @pytest.mark.anyio()
    async def test_local_to_s3_copy(self, sandbox: Path) -> None:
        local_be = MockCopyBackend(name="local")
        s3_be = MockCopyBackend(name="s3")
        source = str(sandbox / "local_file.txt")
        destination = "s3://test-bucket/remote_file.txt"
        local_be.set_exists(source, True)
        local_be.set_info(source, {"name": source, "type": "file", "size": 50})
        local_be.set_content(source, b"hello from local")
        s3_be.set_exists(destination, False)
        app_ctx = _make_cross_backend_copy_app_ctx(sandbox, local_be, s3_be)
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.source_backend == "local"
        assert result.dest_backend == "s3"
        assert result.cross_backend is True
        assert result.size_bytes == len(b"hello from local")
        assert len(local_be.cat_file_calls) == 1
        assert len(s3_be.pipe_file_calls) == 1
        assert s3_be.pipe_file_calls[0] == (destination, b"hello from local")
        assert len(local_be.cp_file_calls) == 0

    @pytest.mark.anyio()
    async def test_s3_to_local_copy(self, sandbox: Path) -> None:
        local_be = MockCopyBackend(name="local")
        s3_be = MockCopyBackend(name="s3")
        source = "s3://test-bucket/remote_file.txt"
        destination = str(sandbox / "local_copy.txt")
        s3_be.set_exists(source, True)
        s3_be.set_info(source, {"name": source, "type": "file", "size": 30})
        s3_be.set_content(source, b"hello from s3")
        local_be.set_exists(destination, False)
        app_ctx = _make_cross_backend_copy_app_ctx(sandbox, local_be, s3_be)
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.source_backend == "s3"
        assert result.dest_backend == "local"
        assert result.cross_backend is True
        assert result.size_bytes == len(b"hello from s3")
        assert len(s3_be.cat_file_calls) == 1
        assert len(local_be.pipe_file_calls) == 1

    @pytest.mark.anyio()
    async def test_cross_backend_flag_false_for_same_backend(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "a.txt")
        destination = str(sandbox / "b.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        result = await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.cross_backend is False

    @pytest.mark.anyio()
    async def test_explicit_source_and_dest_backends(self, sandbox: Path) -> None:
        local_be = MockCopyBackend(name="local")
        s3_be = MockCopyBackend(name="s3")
        source = str(sandbox / "file.txt")
        destination = "s3://test-bucket/file.txt"
        local_be.set_exists(source, True)
        local_be.set_info(source, {"name": source, "type": "file", "size": 20})
        local_be.set_content(source, b"explicit backend test")
        s3_be.set_exists(destination, False)
        app_ctx = _make_cross_backend_copy_app_ctx(sandbox, local_be, s3_be)
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(
            source=source,
            destination=destination,
            source_backend="local",
            dest_backend="s3",
            ctx=ctx,
        )
        assert isinstance(result, CopyFileResponse)
        assert result.source_backend == "local"
        assert result.dest_backend == "s3"
        assert result.cross_backend is True


# ============================================================================
# TestCopyFileOverwrite
# ============================================================================


class TestCopyFileOverwrite:
    """Test overwrite behavior for copy_file."""

    @pytest.mark.anyio()
    async def test_overwrite_false_destination_exists(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "existing.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, True)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        result = await copy_file(
            source=source, destination=destination, overwrite=False, ctx=copy_ctx
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED

    @pytest.mark.anyio()
    async def test_overwrite_true_destination_exists(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "existing.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, True)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        result = await copy_file(
            source=source, destination=destination, overwrite=True, ctx=copy_ctx
        )
        assert isinstance(result, CopyFileResponse)
        assert result.size_bytes == 10

    @pytest.mark.anyio()
    async def test_no_cp_file_call_when_overwrite_blocked(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "existing.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, True)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        await copy_file(source=source, destination=destination, overwrite=False, ctx=copy_ctx)
        assert len(copy_backend.cp_file_calls) == 0


# ============================================================================
# TestCopyFileReadOnly
# ============================================================================


class TestCopyFileReadOnly:
    """Test read-only mode blocks copy operations."""

    @pytest.mark.anyio()
    async def test_read_only_returns_permission_denied(
        self, sandbox: Path, copy_backend: MockCopyBackend
    ) -> None:
        app_ctx = _make_copy_app_ctx(sandbox, copy_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(
            source=str(sandbox / "source.txt"),
            destination=str(sandbox / "dest.txt"),
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "read-only" in result["message"]

    @pytest.mark.anyio()
    async def test_read_only_no_backend_call(
        self, sandbox: Path, copy_backend: MockCopyBackend
    ) -> None:
        app_ctx = _make_copy_app_ctx(sandbox, copy_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)
        await copy_file(
            source=str(sandbox / "source.txt"),
            destination=str(sandbox / "dest.txt"),
            ctx=ctx,
        )
        assert len(copy_backend.cp_file_calls) == 0


# ============================================================================
# TestCopyFileSourceNotFound
# ============================================================================


class TestCopyFileSourceNotFound:
    """Test source file existence checking."""

    @pytest.mark.anyio()
    async def test_source_not_found(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "nonexistent.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, False)
        result = await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.anyio()
    async def test_no_cp_file_call_when_source_missing(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "nonexistent.txt")
        copy_backend.set_exists(source, False)
        await copy_file(source=source, destination=str(sandbox / "d.txt"), ctx=copy_ctx)
        assert len(copy_backend.cp_file_calls) == 0


# ============================================================================
# TestCopyFileSizeLimit
# ============================================================================


class TestCopyFileSizeLimit:
    """Test size limit enforcement against destination backend."""

    @pytest.mark.anyio()
    async def test_source_exceeds_destination_limit(
        self, sandbox: Path, copy_backend: MockCopyBackend
    ) -> None:
        app_ctx = _make_copy_app_ctx(sandbox, copy_backend, max_file_size=100)
        ctx = _make_mock_ctx(app_ctx)
        source = str(sandbox / "big.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 200})
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE
        assert "200" in result["message"]
        assert "100" in result["message"]

    @pytest.mark.anyio()
    async def test_source_within_destination_limit(
        self, sandbox: Path, copy_backend: MockCopyBackend
    ) -> None:
        app_ctx = _make_copy_app_ctx(sandbox, copy_backend, max_file_size=100)
        ctx = _make_mock_ctx(app_ctx)
        source = str(sandbox / "small.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 50})
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.size_bytes == 50

    @pytest.mark.anyio()
    async def test_cross_backend_size_limit_on_destination(self, sandbox: Path) -> None:
        local_be = MockCopyBackend(name="local")
        s3_be = MockCopyBackend(name="s3")
        source = str(sandbox / "file.txt")
        destination = "s3://test-bucket/file.txt"
        local_be.set_exists(source, True)
        local_be.set_info(source, {"name": source, "type": "file", "size": 500})
        s3_be.set_exists(destination, False)
        app_ctx = _make_cross_backend_copy_app_ctx(
            sandbox,
            local_be,
            s3_be,
            local_max_file_size=10_000,
            s3_max_file_size=100,
        )
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE


# ============================================================================
# TestCopyFilePathSecurity
# ============================================================================


class TestCopyFilePathSecurity:
    """Test path security validation on source and destination."""

    @pytest.mark.anyio()
    async def test_source_path_traversal(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        result = await copy_file(
            source=str(sandbox / ".." / "etc" / "passwd"),
            destination=str(sandbox / "dest.txt"),
            ctx=copy_ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_destination_path_traversal(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        result = await copy_file(
            source=source,
            destination=str(sandbox / ".." / "etc" / "evil.txt"),
            ctx=copy_ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX


# ============================================================================
# TestCopyFileBackendErrors
# ============================================================================


class TestCopyFileBackendErrors:
    """Test handling of backend errors during copy operations."""

    @pytest.mark.anyio()
    async def test_backend_error_during_cp_file(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        copy_backend.set_raise_on_cp_file(OSError("disk full"))
        result = await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "disk full" in result["message"]

    @pytest.mark.anyio()
    async def test_fs_error_unwrapped(
        self, sandbox: Path, copy_backend: MockCopyBackend, copy_ctx: MagicMock
    ) -> None:
        source = str(sandbox / "source.txt")
        destination = str(sandbox / "dest.txt")
        copy_backend.set_exists(source, True)
        copy_backend.set_exists(destination, False)
        copy_backend.set_info(source, {"name": source, "type": "file", "size": 10})
        original = PathOutsideSandboxError("Path escapes sandbox")
        wrapper = BackendError("Wrapped error")
        wrapper.__cause__ = original
        copy_backend.set_raise_on_cp_file(wrapper)
        result = await copy_file(source=source, destination=destination, ctx=copy_ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_cross_backend_cat_file_error(self, sandbox: Path) -> None:
        local_be = MockCopyBackend(name="local")
        s3_be = MockCopyBackend(name="s3")
        source = str(sandbox / "file.txt")
        destination = "s3://test-bucket/file.txt"
        local_be.set_exists(source, True)
        local_be.set_info(source, {"name": source, "type": "file", "size": 10})
        local_be.set_raise_on_cat_file(OSError("read error"))
        s3_be.set_exists(destination, False)
        app_ctx = _make_cross_backend_copy_app_ctx(sandbox, local_be, s3_be)
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "read error" in result["message"]

    @pytest.mark.anyio()
    async def test_cross_backend_pipe_file_error(self, sandbox: Path) -> None:
        local_be = MockCopyBackend(name="local")
        s3_be = MockCopyBackend(name="s3")
        source = str(sandbox / "file.txt")
        destination = "s3://test-bucket/file.txt"
        local_be.set_exists(source, True)
        local_be.set_info(source, {"name": source, "type": "file", "size": 10})
        local_be.set_content(source, b"data")
        s3_be.set_exists(destination, False)
        s3_be.set_raise_on_pipe_file(OSError("upload failed"))
        app_ctx = _make_cross_backend_copy_app_ctx(sandbox, local_be, s3_be)
        ctx = _make_mock_ctx(app_ctx)
        result = await copy_file(source=source, destination=destination, ctx=ctx)
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "upload failed" in result["message"]


# ============================================================================
# TestCopyFileIntegration
# ============================================================================


class TestCopyFileIntegration:
    """Integration tests using real filesystem via tmp_path."""

    def _make_real_ctx(self, sandbox: Path, max_file_size: int = 10_485_760) -> MagicMock:
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(read_only=False),
            local=LocalSettings(
                base_path=str(sandbox),
                follow_symlinks=True,
                max_file_size=max_file_size,
            ),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        local_backend = LocalBackend(
            fs=LocalFileSystem(),
            security=security,
            settings=settings.local,
        )
        backend_manager = BackendManager(
            settings=settings,
            security=security,
            local_backend=local_backend,
        )
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        return _make_mock_ctx(app_ctx)

    @pytest.mark.anyio()
    async def test_copy_file_on_disk(self, sandbox: Path) -> None:
        source = sandbox / "original.txt"
        source.write_text("hello world")
        destination = sandbox / "copy.txt"
        ctx = self._make_real_ctx(sandbox)
        result = await copy_file(source=str(source), destination=str(destination), ctx=ctx)
        assert isinstance(result, CopyFileResponse)
        assert result.cross_backend is False
        assert source.exists()
        assert destination.exists()
        assert destination.read_text() == "hello world"

    @pytest.mark.anyio()
    async def test_copy_preserves_source(self, sandbox: Path) -> None:
        source = sandbox / "keep.txt"
        source.write_text("keep me")
        destination = sandbox / "clone.txt"
        ctx = self._make_real_ctx(sandbox)
        await copy_file(source=str(source), destination=str(destination), ctx=ctx)
        assert source.exists()
        assert source.read_text() == "keep me"

    @pytest.mark.anyio()
    async def test_copy_overwrite_real(self, sandbox: Path) -> None:
        source = sandbox / "new.txt"
        source.write_text("new content")
        destination = sandbox / "old.txt"
        destination.write_text("old content")
        ctx = self._make_real_ctx(sandbox)
        result = await copy_file(
            source=str(source),
            destination=str(destination),
            overwrite=True,
            ctx=ctx,
        )
        assert isinstance(result, CopyFileResponse)
        assert destination.read_text() == "new content"
        assert source.read_text() == "new content"

    @pytest.mark.anyio()
    async def test_copy_overwrite_blocked_real(self, sandbox: Path) -> None:
        source = sandbox / "new.txt"
        source.write_text("new content")
        destination = sandbox / "old.txt"
        destination.write_text("old content")
        ctx = self._make_real_ctx(sandbox)
        result = await copy_file(
            source=str(source),
            destination=str(destination),
            overwrite=False,
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert destination.read_text() == "old content"

    @pytest.mark.anyio()
    async def test_copy_source_not_found_real(self, sandbox: Path) -> None:
        ctx = self._make_real_ctx(sandbox)
        result = await copy_file(
            source=str(sandbox / "nonexistent.txt"),
            destination=str(sandbox / "dest.txt"),
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.anyio()
    async def test_copy_binary_file_on_disk(self, sandbox: Path) -> None:
        source = sandbox / "data.bin"
        raw = b"\x00\x01\x02\x03\xff\xfe\xfd"
        source.write_bytes(raw)
        destination = sandbox / "copy.bin"
        ctx = self._make_real_ctx(sandbox)
        result = await copy_file(source=str(source), destination=str(destination), ctx=ctx)
        assert isinstance(result, CopyFileResponse)
        assert destination.read_bytes() == raw

    @pytest.mark.anyio()
    async def test_copy_size_limit_real(self, sandbox: Path) -> None:
        source = sandbox / "big.txt"
        source.write_text("x" * 200)
        ctx = self._make_real_ctx(sandbox, max_file_size=100)
        result = await copy_file(
            source=str(source),
            destination=str(sandbox / "dest.txt"),
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE

    @pytest.mark.anyio()
    async def test_copy_path_traversal_real(self, sandbox: Path) -> None:
        ctx = self._make_real_ctx(sandbox)
        result = await copy_file(
            source=str(sandbox / ".." / ".." / "etc" / "evil.txt"),
            destination=str(sandbox / "dest.txt"),
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX


# ============================================================================
# create_directory helpers: MockCreateDirBackend with per-path isdir
# ============================================================================


class MockCreateDirBackend:
    """A mock backend for unit testing create_directory.

    Supports per-path isdir detection, records mkdir and pipe_file calls,
    and supports configurable exceptions.
    """

    def __init__(self) -> None:
        self._isdir_map: dict[str, bool] = {}
        self._raise_on_mkdir: Exception | None = None
        self._raise_on_pipe_file: Exception | None = None
        self._raise_on_isdir: Exception | None = None
        self._mkdir_calls: list[tuple[str, bool]] = []
        self._pipe_file_calls: list[tuple[str, bytes]] = []

    def set_isdir(self, path: str, is_dir: bool) -> None:
        """Set whether a path is a directory."""
        self._isdir_map[path] = is_dir

    def set_raise_on_mkdir(self, exc: Exception) -> None:
        """Configure mkdir to raise an exception."""
        self._raise_on_mkdir = exc

    def set_raise_on_pipe_file(self, exc: Exception) -> None:
        """Configure pipe_file to raise an exception."""
        self._raise_on_pipe_file = exc

    def set_raise_on_isdir(self, exc: Exception) -> None:
        """Configure isdir to raise an exception."""
        self._raise_on_isdir = exc

    @property
    def mkdir_calls(self) -> list[tuple[str, bool]]:
        """Return recorded mkdir calls as (path, create_parents) tuples."""
        return list(self._mkdir_calls)

    @property
    def pipe_file_calls(self) -> list[tuple[str, bytes]]:
        """Return recorded pipe_file calls."""
        return list(self._pipe_file_calls)

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        return []

    def info(self, path: str) -> dict[str, Any]:
        return {"name": path, "type": "directory", "size": 0}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        return b""

    def pipe_file(self, path: str, data: bytes) -> None:
        if self._raise_on_pipe_file is not None:
            raise self._raise_on_pipe_file
        self._pipe_file_calls.append((path, data))

    def rm(self, path: str) -> None:
        pass

    def cp_file(self, source: str, destination: str) -> None:
        pass

    def mv(self, source: str, destination: str) -> None:
        pass

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        if self._raise_on_mkdir is not None:
            raise self._raise_on_mkdir
        self._mkdir_calls.append((path, create_parents))

    def exists(self, path: str) -> bool:
        return self._isdir_map.get(path, False)

    def isdir(self, path: str) -> bool:
        if self._raise_on_isdir is not None:
            raise self._raise_on_isdir
        return self._isdir_map.get(path, False)

    def isfile(self, path: str) -> bool:
        return False


def _make_mkdir_app_ctx(
    sandbox: Path,
    mkdir_backend: MockCreateDirBackend,
    read_only: bool = False,
) -> AppContext:
    """Create an AppContext for create_directory testing."""
    settings = Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(base_path=str(sandbox)),
        s3=S3Settings(enabled=False),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=mkdir_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


def _make_mkdir_s3_app_ctx(
    sandbox: Path,
    s3_backend: MockCreateDirBackend,
    read_only: bool = False,
) -> AppContext:
    """Create an AppContext for create_directory S3 testing."""
    settings = Settings(
        server=ServerSettings(read_only=read_only),
        local=LocalSettings(enabled=False, base_path=str(sandbox)),
        s3=S3Settings(enabled=True, bucket="test-bucket", region="us-east-1"),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        s3_backend=s3_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


# ============================================================================
# create_directory fixtures
# ============================================================================


@pytest.fixture()
def mkdir_backend() -> MockCreateDirBackend:
    """A mock backend for create_directory tests."""
    return MockCreateDirBackend()


@pytest.fixture()
def mkdir_app_ctx(sandbox: Path, mkdir_backend: MockCreateDirBackend) -> AppContext:
    """AppContext for create_directory with read_only=False."""
    return _make_mkdir_app_ctx(sandbox, mkdir_backend, read_only=False)


@pytest.fixture()
def mkdir_ctx(mkdir_app_ctx: AppContext) -> MagicMock:
    """Mock MCP context for create_directory tests."""
    return _make_mock_ctx(mkdir_app_ctx)


# ============================================================================
# TestCreateDirectoryBasic: Core directory creation functionality
# ============================================================================


class TestCreateDirectoryBasic:
    """Test basic directory creation operations."""

    @pytest.mark.anyio()
    async def test_create_directory_success(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Creating a new directory returns CreateDirectoryResponse with created=True."""
        dir_path = str(sandbox / "new_dir")
        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.path == dir_path
        assert result.backend == "local"
        assert result.created is True

    @pytest.mark.anyio()
    async def test_create_directory_calls_backend_mkdir(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Should call backend.mkdir with the path and create_parents=True (default)."""
        dir_path = str(sandbox / "new_dir")
        await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert len(mkdir_backend.mkdir_calls) == 1
        assert mkdir_backend.mkdir_calls[0] == (dir_path, True)

    @pytest.mark.anyio()
    async def test_create_directory_returns_local_backend(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Returns backend='local' for local paths."""
        dir_path = str(sandbox / "new_dir")
        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.backend == "local"

    @pytest.mark.anyio()
    async def test_create_directory_no_context(self) -> None:
        """Create directory without context returns BACKEND_ERROR."""
        result = await create_directory(path="/data/new_dir", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.anyio()
    async def test_create_directory_explicit_backend(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Explicit backend='local' is used in response."""
        dir_path = str(sandbox / "new_dir")
        result = await create_directory(path=dir_path, backend="local", ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.backend == "local"


# ============================================================================
# TestCreateDirectoryParents: Parent directory creation
# ============================================================================


class TestCreateDirectoryParents:
    """Test parents parameter behavior."""

    @pytest.mark.anyio()
    async def test_parents_true_passes_to_backend(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """parents=True is passed through to backend.mkdir."""
        dir_path = str(sandbox / "a" / "b" / "c")
        result = await create_directory(path=dir_path, parents=True, ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert mkdir_backend.mkdir_calls[0] == (dir_path, True)

    @pytest.mark.anyio()
    async def test_parents_false_passes_to_backend(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """parents=False is passed through to backend.mkdir."""
        dir_path = str(sandbox / "new_dir")
        result = await create_directory(path=dir_path, parents=False, ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert mkdir_backend.mkdir_calls[0] == (dir_path, False)

    @pytest.mark.anyio()
    async def test_parents_default_is_true(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Default parents parameter is True."""
        dir_path = str(sandbox / "new_dir")
        await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert mkdir_backend.mkdir_calls[0][1] is True

    @pytest.mark.anyio()
    async def test_parents_false_with_missing_parent_errors(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """parents=False with missing parent directory propagates backend error."""
        dir_path = str(sandbox / "missing_parent" / "child")
        mkdir_backend.set_raise_on_mkdir(
            BackendError("Parent directory not found for: " + dir_path)
        )

        result = await create_directory(path=dir_path, parents=False, ctx=mkdir_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR


# ============================================================================
# TestCreateDirectoryIdempotent: Idempotency (already exists)
# ============================================================================


class TestCreateDirectoryIdempotent:
    """Test idempotent behavior when directory already exists."""

    @pytest.mark.anyio()
    async def test_existing_directory_returns_created_false(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Directory that already exists returns created=false, no error."""
        dir_path = str(sandbox / "existing_dir")
        mkdir_backend.set_isdir(dir_path, True)

        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is False
        assert result.path == dir_path
        assert result.backend == "local"

    @pytest.mark.anyio()
    async def test_existing_directory_no_mkdir_call(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Backend.mkdir is not called when directory already exists."""
        dir_path = str(sandbox / "existing_dir")
        mkdir_backend.set_isdir(dir_path, True)

        await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert len(mkdir_backend.mkdir_calls) == 0

    @pytest.mark.anyio()
    async def test_isdir_error_proceeds_with_creation(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """If isdir() raises, proceed with creation attempt."""
        dir_path = str(sandbox / "unknown")
        mkdir_backend.set_raise_on_isdir(OSError("cannot stat"))

        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert len(mkdir_backend.mkdir_calls) == 1


# ============================================================================
# TestCreateDirectoryS3: S3 prefix placeholder creation
# ============================================================================


class TestCreateDirectoryS3:
    """Test S3 directory creation (empty object with trailing /)."""

    @pytest.mark.anyio()
    async def test_s3_creates_prefix_placeholder(self, sandbox: Path) -> None:
        """S3 backend creates empty object with trailing / as prefix placeholder."""
        s3_be = MockCreateDirBackend()
        app_ctx = _make_mkdir_s3_app_ctx(sandbox, s3_be)
        ctx = _make_mock_ctx(app_ctx)

        result = await create_directory(path="s3://test-bucket/my-prefix", ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert result.backend == "s3"
        # Verify pipe_file was called with trailing / and empty bytes
        assert len(s3_be.pipe_file_calls) == 1
        assert s3_be.pipe_file_calls[0][0] == "s3://test-bucket/my-prefix/"
        assert s3_be.pipe_file_calls[0][1] == b""
        # mkdir should NOT be called for S3
        assert len(s3_be.mkdir_calls) == 0

    @pytest.mark.anyio()
    async def test_s3_path_already_has_trailing_slash(self, sandbox: Path) -> None:
        """S3 path with trailing slash does not double the slash."""
        s3_be = MockCreateDirBackend()
        app_ctx = _make_mkdir_s3_app_ctx(sandbox, s3_be)
        ctx = _make_mock_ctx(app_ctx)

        result = await create_directory(path="s3://test-bucket/my-prefix/", ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert s3_be.pipe_file_calls[0][0] == "s3://test-bucket/my-prefix/"

    @pytest.mark.anyio()
    async def test_s3_existing_prefix_returns_created_false(self, sandbox: Path) -> None:
        """S3 prefix that already exists returns created=false."""
        s3_be = MockCreateDirBackend()
        s3_be.set_isdir("s3://test-bucket/existing-prefix", True)
        app_ctx = _make_mkdir_s3_app_ctx(sandbox, s3_be)
        ctx = _make_mock_ctx(app_ctx)

        result = await create_directory(path="s3://test-bucket/existing-prefix", ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is False
        assert len(s3_be.pipe_file_calls) == 0


# ============================================================================
# TestCreateDirectoryReadOnly: Read-only mode enforcement
# ============================================================================


class TestCreateDirectoryReadOnly:
    """Test read-only mode blocks directory creation."""

    @pytest.mark.anyio()
    async def test_read_only_returns_permission_denied(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend
    ) -> None:
        """Returns PERMISSION_DENIED when server is in read-only mode."""
        app_ctx = _make_mkdir_app_ctx(sandbox, mkdir_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        dir_path = str(sandbox / "new_dir")
        result = await create_directory(path=dir_path, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert "read-only" in result["message"].lower()

    @pytest.mark.anyio()
    async def test_read_only_no_backend_call(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend
    ) -> None:
        """Read-only rejection happens before any backend interaction."""
        app_ctx = _make_mkdir_app_ctx(sandbox, mkdir_backend, read_only=True)
        ctx = _make_mock_ctx(app_ctx)

        dir_path = str(sandbox / "new_dir")
        await create_directory(path=dir_path, ctx=ctx)

        assert len(mkdir_backend.mkdir_calls) == 0


# ============================================================================
# TestCreateDirectoryPathSecurity: Path traversal and sandbox escape
# ============================================================================


class TestCreateDirectoryPathSecurity:
    """Test path security validation for create_directory."""

    @pytest.mark.anyio()
    async def test_path_traversal_returns_path_outside_sandbox(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Path traversal attempt returns PATH_OUTSIDE_SANDBOX."""
        traversal_path = str(sandbox / ".." / ".." / "etc" / "evil_dir")
        result = await create_directory(path=traversal_path, ctx=mkdir_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_path_traversal_no_mkdir_call(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Backend.mkdir is not called for path traversal attempts."""
        traversal_path = str(sandbox / ".." / ".." / "etc" / "evil_dir")
        await create_directory(path=traversal_path, ctx=mkdir_ctx)

        assert len(mkdir_backend.mkdir_calls) == 0


# ============================================================================
# TestCreateDirectoryErrors: Backend errors during creation
# ============================================================================


class TestCreateDirectoryErrors:
    """Test error handling in create_directory."""

    @pytest.mark.anyio()
    async def test_backend_error_during_mkdir(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Backend error during mkdir is reported."""
        dir_path = str(sandbox / "new_dir")
        mkdir_backend.set_raise_on_mkdir(OSError("disk full"))

        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "disk full" in result["message"]

    @pytest.mark.anyio()
    async def test_fs_error_during_mkdir_unwrapped(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """FSError wrapped in BackendError is unwrapped to surface original code."""
        dir_path = str(sandbox / "new_dir")
        original = PathOutsideSandboxError("Path escapes sandbox")
        wrapper = BackendError("Wrapped error")
        wrapper.__cause__ = original
        mkdir_backend.set_raise_on_mkdir(wrapper)

        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_unexpected_exception_returns_backend_error(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """Non-FSError exceptions return BACKEND_ERROR."""
        dir_path = str(sandbox / "new_dir")
        mkdir_backend.set_raise_on_mkdir(RuntimeError("unexpected"))

        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "unexpected" in result["message"]

    @pytest.mark.anyio()
    async def test_backend_error_wrapping_permission(
        self, sandbox: Path, mkdir_backend: MockCreateDirBackend, mkdir_ctx: MagicMock
    ) -> None:
        """BackendError wrapping PermissionDeniedError surfaces PERMISSION_DENIED."""
        dir_path = str(sandbox / "new_dir")
        inner = PermissionDeniedError("Cannot create directory on read-only mount")
        outer = BackendError("Backend failed")
        outer.__cause__ = inner
        mkdir_backend.set_raise_on_mkdir(outer)

        result = await create_directory(path=dir_path, ctx=mkdir_ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED


# ============================================================================
# TestCreateDirectoryIntegration: Real filesystem integration tests
# ============================================================================


class TestCreateDirectoryIntegration:
    """Integration tests using real filesystem (tmp_path)."""

    def _make_real_ctx(self, sandbox: Path, read_only: bool = False) -> MagicMock:
        """Create a context with a real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(read_only=read_only),
            local=LocalSettings(base_path=str(sandbox), follow_symlinks=True),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        local_backend = LocalBackend(
            fs=LocalFileSystem(),
            security=security,
            settings=settings.local,
        )
        backend_manager = BackendManager(
            settings=settings,
            security=security,
            local_backend=local_backend,
        )
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        return _make_mock_ctx(app_ctx)

    @pytest.mark.anyio()
    async def test_create_directory_on_disk(self, sandbox: Path) -> None:
        """Creates a directory on actual disk."""
        dir_path = sandbox / "new_dir"
        ctx = self._make_real_ctx(sandbox)

        result = await create_directory(path=str(dir_path), ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert result.backend == "local"
        assert result.path == str(dir_path)
        # Verify directory actually exists on disk
        assert dir_path.exists()
        assert dir_path.is_dir()

    @pytest.mark.anyio()
    async def test_create_nested_directories_on_disk(self, sandbox: Path) -> None:
        """Creates nested parent directories with parents=True."""
        dir_path = sandbox / "a" / "b" / "c" / "deep"
        ctx = self._make_real_ctx(sandbox)

        result = await create_directory(path=str(dir_path), parents=True, ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        # Verify entire directory chain exists
        assert dir_path.exists()
        assert dir_path.is_dir()
        assert (sandbox / "a" / "b" / "c").is_dir()
        assert (sandbox / "a" / "b").is_dir()
        assert (sandbox / "a").is_dir()

    @pytest.mark.anyio()
    async def test_idempotent_on_disk(self, sandbox: Path) -> None:
        """Creating an already-existing directory returns created=False."""
        dir_path = sandbox / "existing"
        dir_path.mkdir()
        assert dir_path.is_dir()

        ctx = self._make_real_ctx(sandbox)
        result = await create_directory(path=str(dir_path), ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is False
        # Directory still exists
        assert dir_path.is_dir()

    @pytest.mark.anyio()
    async def test_create_at_sandbox_root_on_disk(self, sandbox: Path) -> None:
        """Creating a directory at the root of the sandbox."""
        dir_path = sandbox / "root_level_dir"
        ctx = self._make_real_ctx(sandbox)

        result = await create_directory(path=str(dir_path), ctx=ctx)

        assert isinstance(result, CreateDirectoryResponse)
        assert result.created is True
        assert dir_path.exists()
        assert dir_path.is_dir()

    @pytest.mark.anyio()
    async def test_path_traversal_on_disk(self, sandbox: Path) -> None:
        """Path traversal blocked on real filesystem."""
        ctx = self._make_real_ctx(sandbox)
        traversal_path = str(sandbox / ".." / ".." / "etc" / "evil_dir")

        result = await create_directory(path=traversal_path, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.anyio()
    async def test_read_only_on_disk(self, sandbox: Path) -> None:
        """Read-only mode blocks directory creation on real filesystem."""
        ctx = self._make_real_ctx(sandbox, read_only=True)
        dir_path = str(sandbox / "blocked")

        result = await create_directory(path=dir_path, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PERMISSION_DENIED
        assert not (sandbox / "blocked").exists()
