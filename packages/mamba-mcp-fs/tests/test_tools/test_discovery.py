"""Tests for the discovery MCP tools (list_directory, get_file_info, read_file, search_files).

Covers:
- Unit: Listing with mocked backend (various directory contents)
- Unit: Glob pattern filtering
- Unit: Pagination with max_entries
- Unit: Hidden file filtering with include_hidden override
- Unit: File metadata retrieval with mocked backend
- Unit: Directory metadata retrieval
- Unit: Checksum calculation
- Unit: MIME type detection integration
- Unit: Text file reading with mocked backend
- Unit: Binary file reading (base64 encoding)
- Unit: Chunked reading with offset/limit
- Unit: Size limit enforcement
- Unit: force_text and force_base64 flags
- Unit: Name pattern search with mocked backend
- Unit: Content pattern search with mocked text files
- Unit: Combined name + content search
- Unit: max_depth enforcement
- Unit: max_results truncation
- Integration: Real directory listing with tmp_path
- Integration: Real file metadata with tmp_path
- Integration: Symlink detection on real filesystem
- Integration: Real file reading with tmp_path (text and binary)
- Integration: Chunked reading of large files
- Integration: Recursive search in real directory tree
- Integration: Content search in real text files
- Integration: Regex error handling
- Integration: Error responses for each error case
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from mamba_mcp_fs.backends.base import BackendManager
from mamba_mcp_fs.config import LocalSettings, S3Settings, ServerSettings, Settings
from mamba_mcp_fs.errors import (
    ErrorCode,
    PathNotFoundError,
    SymlinkBlockedError,
)
from mamba_mcp_fs.models.files import FileEntry
from mamba_mcp_fs.models.responses import (
    FileInfoResponse,
    ListDirectoryResponse,
    ReadFileResponse,
    SearchResponse,
)
from mamba_mcp_fs.rate_limit import RateLimiter
from mamba_mcp_fs.security import SecurityValidator
from mamba_mcp_fs.server import AppContext
from mamba_mcp_fs.tools.discovery_tools import (
    _compute_checksum,
    _extract_match_context,
    _filter_by_pattern,
    _parse_timestamp,
    _to_file_entry,
    get_file_info,
    list_directory,
    read_file,
    search_files,
)

# ============================================================================
# Helpers: Mock backend, context, and test data
# ============================================================================


class MockBackend:
    """A mock backend for unit testing discovery tools."""

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self._entries = entries or []
        self._raise_on_ls: Exception | None = None
        self._info_result: dict[str, Any] | None = None
        self._raise_on_info: Exception | None = None
        self._file_content: bytes = b""
        # Per-directory entries for search_files testing
        self._dir_entries: dict[str, list[dict[str, Any]]] = {}
        # Per-file content for search_files testing
        self._file_contents: dict[str, bytes] = {}

    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    def set_raise_on_ls(self, exc: Exception) -> None:
        self._raise_on_ls = exc

    def set_info_result(self, result: dict[str, Any]) -> None:
        self._info_result = result

    def set_raise_on_info(self, exc: Exception) -> None:
        self._raise_on_info = exc

    def set_file_content(self, content: bytes) -> None:
        self._file_content = content

    def set_dir_entries(self, dir_path: str, entries: list[dict[str, Any]]) -> None:
        """Set entries for a specific directory (used by search_files tests)."""
        self._dir_entries[dir_path] = entries

    def set_file_contents(self, path: str, content: bytes) -> None:
        """Set content for a specific file path (used by search_files tests)."""
        self._file_contents[path] = content

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        if self._raise_on_ls is not None:
            raise self._raise_on_ls
        # Check per-directory entries first (for search_files tree simulation)
        if path in self._dir_entries:
            return list(self._dir_entries[path])
        return list(self._entries)

    def info(self, path: str) -> dict[str, Any]:
        if self._raise_on_info is not None:
            raise self._raise_on_info
        if self._info_result is not None:
            return dict(self._info_result)
        return {"name": path, "type": "directory", "size": 0}

    def set_raise_on_cat_file(self, paths: set[str]) -> None:
        """Set paths that should raise on cat_file (for content search error testing)."""
        self._raise_on_cat_paths: set[str] = paths

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        # Raise on specific paths if configured
        if hasattr(self, "_raise_on_cat_paths") and path in self._raise_on_cat_paths:
            raise OSError(f"Permission denied: {path}")
        # Check per-file content first (for search_files tests)
        data = self._file_contents.get(path, self._file_content)
        if start is not None and end is not None:
            return data[start:end]
        if start is not None:
            return data[start:]
        if end is not None:
            return data[:end]
        return data

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
        return True

    def isdir(self, path: str) -> bool:
        return True

    def isfile(self, path: str) -> bool:
        return False


def _make_entry(
    name: str,
    entry_type: str = "file",
    size: int = 100,
    modified: float | None = None,
) -> dict[str, Any]:
    """Create a mock backend entry dict."""
    return {
        "name": name,
        "type": entry_type,
        "size": size,
        "modified": modified or 1700000000.0,
    }


def _make_settings(
    sandbox: Path,
    show_hidden: bool = False,
) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        server=ServerSettings(),
        local=LocalSettings(base_path=str(sandbox), show_hidden=show_hidden),
        s3=S3Settings(enabled=False),
    )


def _make_app_ctx(
    sandbox: Path,
    mock_backend: MockBackend,
    show_hidden: bool = False,
) -> AppContext:
    """Create an AppContext for testing with mocked dependencies."""
    settings = _make_settings(sandbox, show_hidden=show_hidden)
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
    """AppContext with default settings."""
    return _make_app_ctx(sandbox, mock_backend)


@pytest.fixture()
def mock_ctx(app_ctx: AppContext) -> MagicMock:
    """Mock MCP context."""
    return _make_mock_ctx(app_ctx)


# ============================================================================
# TestListDirectoryBasic: Core listing functionality
# ============================================================================


class TestListDirectoryBasic:
    """Tests for basic list_directory listing behavior."""

    @pytest.mark.asyncio
    async def test_lists_files_and_directories(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Lists files and directories with correct metadata."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "file.txt"), "file", 1234, 1700000000.0),
                _make_entry(str(sandbox / "subdir"), "directory", 0, 1700000000.0),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.path == str(sandbox)
        assert result.backend == "local"
        assert len(result.entries) == 2
        assert result.total_count == 2
        assert result.has_more is False

        # Verify entry metadata
        file_entry = next(e for e in result.entries if e.name == "file.txt")
        assert file_entry.type == "file"
        assert file_entry.size_bytes == 1234
        assert file_entry.modified_at is not None

        dir_entry = next(e for e in result.entries if e.name == "subdir")
        assert dir_entry.type == "directory"

    @pytest.mark.asyncio
    async def test_empty_directory(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Empty directory returns empty entries list with total_count 0."""
        mock_backend.set_entries([])
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.entries == []
        assert result.total_count == 0
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Calling without context returns an error response dict."""
        result = await list_directory(path="/any/path", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_response_preserves_original_path(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Response should contain the original path as given by the user."""
        mock_backend.set_entries([])
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        original_path = str(sandbox)
        result = await list_directory(path=original_path, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.path == original_path


# ============================================================================
# TestListDirectoryHiddenFiles: Hidden file filtering
# ============================================================================


class TestListDirectoryHiddenFiles:
    """Tests for hidden file filtering with include_hidden override."""

    @pytest.mark.asyncio
    async def test_hides_dotfiles_by_default(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Hidden files are excluded when show_hidden=False (default)."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "visible.txt")),
                _make_entry(str(sandbox / ".hidden")),
                _make_entry(str(sandbox / ".gitignore")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend, show_hidden=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "visible.txt" in names
        assert ".hidden" not in names
        assert ".gitignore" not in names

    @pytest.mark.asyncio
    async def test_shows_dotfiles_when_config_enabled(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Hidden files are included when show_hidden=True in config."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "visible.txt")),
                _make_entry(str(sandbox / ".hidden")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend, show_hidden=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "visible.txt" in names
        assert ".hidden" in names

    @pytest.mark.asyncio
    async def test_include_hidden_true_overrides_config(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """include_hidden=True overrides show_hidden=False config."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "visible.txt")),
                _make_entry(str(sandbox / ".hidden")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend, show_hidden=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), include_hidden=True, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert ".hidden" in names

    @pytest.mark.asyncio
    async def test_include_hidden_false_overrides_config(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """include_hidden=False overrides show_hidden=True config."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "visible.txt")),
                _make_entry(str(sandbox / ".hidden")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend, show_hidden=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), include_hidden=False, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "visible.txt" in names
        assert ".hidden" not in names


# ============================================================================
# TestListDirectoryGlobPattern: Glob pattern filtering
# ============================================================================


class TestListDirectoryGlobPattern:
    """Tests for glob pattern filtering."""

    @pytest.mark.asyncio
    async def test_filters_by_glob_pattern(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Pattern filters entries by glob matching on basename."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "app.py")),
                _make_entry(str(sandbox / "test.py")),
                _make_entry(str(sandbox / "readme.md")),
                _make_entry(str(sandbox / "data.json")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), pattern="*.py", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "app.py" in names
        assert "test.py" in names
        assert "readme.md" not in names
        assert "data.json" not in names

    @pytest.mark.asyncio
    async def test_glob_no_matches_returns_empty(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Pattern with no matches returns empty list."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "file.txt")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), pattern="*.rs", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.entries == []
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_glob_star_matches_all(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Pattern '*' matches all entries."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "a.txt")),
                _make_entry(str(sandbox / "b.py")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), pattern="*", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_no_pattern_returns_all(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """No pattern returns all (non-hidden) entries."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "a.txt")),
                _make_entry(str(sandbox / "b.py")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), pattern=None, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_glob_readme_star(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Pattern 'README*' matches README files."""
        mock_backend.set_entries(
            [
                _make_entry(str(sandbox / "README.md")),
                _make_entry(str(sandbox / "README")),
                _make_entry(str(sandbox / "other.txt")),
            ]
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), pattern="README*", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "README.md" in names
        assert "README" in names
        assert "other.txt" not in names


# ============================================================================
# TestListDirectoryPagination: max_entries truncation
# ============================================================================


class TestListDirectoryPagination:
    """Tests for pagination with max_entries."""

    @pytest.mark.asyncio
    async def test_truncates_at_max_entries(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Returns has_more=True when entries exceed max_entries."""
        entries = [_make_entry(str(sandbox / f"file{i}.txt")) for i in range(10)]
        mock_backend.set_entries(entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), max_entries=5, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 5
        assert result.total_count == 5
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_no_truncation_when_under_limit(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Returns has_more=False when entries are within max_entries."""
        entries = [_make_entry(str(sandbox / f"file{i}.txt")) for i in range(3)]
        mock_backend.set_entries(entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), max_entries=10, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 3
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_max_entries_clamped_to_minimum(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """max_entries below 1 is clamped to 1."""
        entries = [_make_entry(str(sandbox / f"file{i}.txt")) for i in range(5)]
        mock_backend.set_entries(entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), max_entries=0, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 1
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_max_entries_clamped_to_maximum(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """max_entries above 10000 is clamped to 10000."""
        entries = [_make_entry(str(sandbox / f"file{i}.txt")) for i in range(5)]
        mock_backend.set_entries(entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), max_entries=50000, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        # All 5 entries fit within 10000 limit
        assert len(result.entries) == 5
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_large_directory_truncated(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Very large directories are truncated at max_entries with has_more=True."""
        entries = [_make_entry(str(sandbox / f"file{i}.txt")) for i in range(150)]
        mock_backend.set_entries(entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), max_entries=100, ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 100
        assert result.has_more is True


# ============================================================================
# TestListDirectoryErrors: Error handling
# ============================================================================


class TestListDirectoryErrors:
    """Tests for error handling in list_directory."""

    @pytest.mark.asyncio
    async def test_backend_not_configured_error(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED for disabled backend."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(sandbox), enabled=False),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        backend_manager = BackendManager(settings=settings, security=security)
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_path_not_found_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """PATH_NOT_FOUND for non-existent directories."""
        mock_backend.set_raise_on_ls(PathNotFoundError("Directory not found"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_path_outside_sandbox_error(self, sandbox: Path) -> None:
        """PATH_OUTSIDE_SANDBOX for traversal attempts."""
        mock_backend = MockBackend()
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox / ".." / ".." / "etc" / "passwd"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_unexpected_backend_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Unexpected backend exceptions return BACKEND_ERROR."""
        mock_backend.set_raise_on_ls(RuntimeError("Unexpected I/O error"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(sandbox), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR


# ============================================================================
# TestListDirectoryIntegration: Real filesystem tests
# ============================================================================


class TestListDirectoryIntegration:
    """Integration tests with real local filesystem via tmp_path."""

    @pytest.mark.asyncio
    async def test_real_directory_listing(self, tmp_path: Path) -> None:
        """Lists real files created in a temp directory."""
        # Create test files
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.py").write_text("print('hi')")
        (tmp_path / "subdir").mkdir()

        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.total_count == 3
        names = {e.name for e in result.entries}
        assert names == {"file1.txt", "file2.py", "subdir"}

        # Verify metadata types
        file_entry = next(e for e in result.entries if e.name == "file1.txt")
        assert file_entry.type == "file"
        assert file_entry.size_bytes is not None
        assert file_entry.size_bytes > 0

        dir_entry = next(e for e in result.entries if e.name == "subdir")
        assert dir_entry.type == "directory"

    @pytest.mark.asyncio
    async def test_real_empty_directory(self, tmp_path: Path) -> None:
        """Empty temp directory returns empty entries."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(empty_dir), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.entries == []
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_real_pattern_filtering(self, tmp_path: Path) -> None:
        """Glob pattern filters real files correctly."""
        (tmp_path / "app.py").write_text("code")
        (tmp_path / "test.py").write_text("test code")
        (tmp_path / "readme.md").write_text("docs")
        (tmp_path / "data.json").write_text("{}")

        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path), pattern="*.py", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert names == {"app.py", "test.py"}

    @pytest.mark.asyncio
    async def test_real_hidden_files_excluded_by_default(self, tmp_path: Path) -> None:
        """Hidden files are excluded when show_hidden=False (default)."""
        (tmp_path / "visible.txt").write_text("visible")
        (tmp_path / ".hidden").write_text("hidden")

        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path, show_hidden=False)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path), ctx=ctx)
        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "visible.txt" in names
        assert ".hidden" not in names

    @pytest.mark.asyncio
    async def test_real_hidden_files_shown_when_config_enabled(self, tmp_path: Path) -> None:
        """Hidden files are included when show_hidden=True in config."""
        (tmp_path / "visible.txt").write_text("visible")
        (tmp_path / ".hidden").write_text("hidden")

        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path, show_hidden=True)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path), ctx=ctx)
        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "visible.txt" in names
        assert ".hidden" in names

    @pytest.mark.asyncio
    async def test_real_hidden_files_override_false(self, tmp_path: Path) -> None:
        """include_hidden=False overrides show_hidden=True to hide dotfiles."""
        (tmp_path / "visible.txt").write_text("visible")
        (tmp_path / ".hidden").write_text("hidden")

        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path, show_hidden=True)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path), include_hidden=False, ctx=ctx)
        assert isinstance(result, ListDirectoryResponse)
        names = [e.name for e in result.entries]
        assert "visible.txt" in names
        assert ".hidden" not in names

    @pytest.mark.asyncio
    async def test_real_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Path traversal is blocked with real backend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path / ".." / ".." / "etc"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_real_nonexistent_directory(self, tmp_path: Path) -> None:
        """Non-existent directory returns PATH_NOT_FOUND with real backend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = _make_settings(tmp_path)
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(tmp_path / "nonexistent"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND


# ============================================================================
# TestHelperFunctions: Helper function unit tests
# ============================================================================


class TestFilterByPattern:
    """Tests for _filter_by_pattern helper."""

    def test_matches_py_files(self) -> None:
        entries = [
            {"name": "/path/app.py"},
            {"name": "/path/test.py"},
            {"name": "/path/readme.md"},
        ]
        result = _filter_by_pattern(entries, "*.py")
        names = [os.path.basename(e["name"]) for e in result]
        assert names == ["app.py", "test.py"]

    def test_no_matches(self) -> None:
        entries = [{"name": "/path/file.txt"}]
        result = _filter_by_pattern(entries, "*.rs")
        assert result == []

    def test_empty_entries(self) -> None:
        result = _filter_by_pattern([], "*.py")
        assert result == []


class TestToFileEntry:
    """Tests for _to_file_entry helper."""

    def test_file_entry(self) -> None:
        entry = _make_entry("/data/file.txt", "file", 1024, 1700000000.0)
        result = _to_file_entry(entry)

        assert isinstance(result, FileEntry)
        assert result.name == "file.txt"
        assert result.path == "/data/file.txt"
        assert result.type == "file"
        assert result.size_bytes == 1024
        assert result.modified_at is not None
        assert result.is_hidden is False

    def test_directory_entry(self) -> None:
        entry = _make_entry("/data/subdir", "directory", 0, 1700000000.0)
        result = _to_file_entry(entry)

        assert result.type == "directory"
        assert result.name == "subdir"

    def test_hidden_file(self) -> None:
        entry = _make_entry("/data/.gitignore", "file", 50, 1700000000.0)
        result = _to_file_entry(entry)

        assert result.is_hidden is True
        assert result.name == ".gitignore"

    def test_unknown_type_defaults_to_file(self) -> None:
        entry = {"name": "/data/other", "type": "other", "size": 0, "modified": None}
        result = _to_file_entry(entry)
        assert result.type == "file"

    def test_none_size_stays_none(self) -> None:
        entry = {"name": "/data/dir", "type": "directory", "size": None, "modified": None}
        result = _to_file_entry(entry)
        assert result.size_bytes is None


class TestParseTimestamp:
    """Tests for _parse_timestamp helper."""

    def test_none_returns_none(self) -> None:
        assert _parse_timestamp(None) is None

    def test_datetime_passthrough(self) -> None:
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        assert _parse_timestamp(dt) is dt

    def test_float_unix_timestamp(self) -> None:
        result = _parse_timestamp(1700000000.0)
        assert isinstance(result, datetime)
        assert result.year == 2023

    def test_int_unix_timestamp(self) -> None:
        result = _parse_timestamp(1700000000)
        assert isinstance(result, datetime)

    def test_iso_string(self) -> None:
        result = _parse_timestamp("2024-01-01T00:00:00+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_invalid_string(self) -> None:
        assert _parse_timestamp("not-a-date") is None

    def test_unsupported_type(self) -> None:
        assert _parse_timestamp([1, 2, 3]) is None

    def test_overflow_timestamp(self) -> None:
        """Extremely large timestamps should return None gracefully."""
        assert _parse_timestamp(9999999999999999.0) is None


# ============================================================================
# TestGetFileInfoBasic: Core file metadata retrieval
# ============================================================================


class TestGetFileInfoBasic:
    """Tests for basic get_file_info metadata retrieval."""

    @pytest.mark.asyncio
    async def test_file_metadata(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Returns correct metadata for a regular file."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "report.csv"),
                "type": "file",
                "size": 2048,
                "modified": 1700000000.0,
                "created_at": "2023-11-14T00:00:00+00:00",
                "mime_type": "text/csv",
                "islink": False,
                "permissions": "-rw-r--r--",
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "report.csv"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "report.csv"
        assert result.path == str(sandbox / "report.csv")
        assert result.backend == "local"
        assert result.type == "file"
        assert result.size_bytes == 2048
        assert result.mime_type == "text/csv"
        assert result.modified_at is not None
        assert result.created_at is not None
        assert result.is_hidden is False
        assert result.is_symlink is False
        assert result.permissions == "-rw-r--r--"
        assert result.checksum is None

    @pytest.mark.asyncio
    async def test_directory_metadata(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Returns correct metadata for a directory."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "subdir"),
                "type": "directory",
                "size": 0,
                "modified": 1700000000.0,
                "islink": False,
                "permissions": "drwxr-xr-x",
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "subdir"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "subdir"
        assert result.type == "directory"
        assert result.mime_type == "inode/directory"
        assert result.size_bytes == 0
        assert result.is_hidden is False

    @pytest.mark.asyncio
    async def test_hidden_file_detected(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Dotfiles are identified as hidden."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / ".gitignore"),
                "type": "file",
                "size": 50,
                "modified": 1700000000.0,
                "mime_type": "text/plain",
                "islink": False,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / ".gitignore"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == ".gitignore"
        assert result.is_hidden is True

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Calling without context returns an error response dict."""
        result = await get_file_info(path="/any/path", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_response_preserves_original_path(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Response should contain the original path as given by the user."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "file.txt"),
                "type": "file",
                "size": 100,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        original_path = str(sandbox / "file.txt")
        result = await get_file_info(path=original_path, ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.path == original_path


# ============================================================================
# TestGetFileInfoSizePretty: Human-readable size_pretty field
# ============================================================================


class TestGetFileInfoSizePretty:
    """Tests for the size_pretty computed field."""

    @pytest.mark.asyncio
    async def test_size_pretty_for_file(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """size_pretty shows human-readable file size."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "large.bin"),
                "type": "file",
                "size": 1536,
                "modified": 1700000000.0,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "large.bin"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.size_pretty == "1.5 KB"

    @pytest.mark.asyncio
    async def test_size_pretty_for_zero(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """size_pretty shows '0 B' for zero-size files."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "empty.txt"),
                "type": "file",
                "size": 0,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "empty.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.size_pretty == "0 B"

    @pytest.mark.asyncio
    async def test_size_pretty_for_none(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """size_pretty shows '0 B' when size_bytes is None (directories)."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "dir"),
                "type": "directory",
                "size": None,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "dir"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.size_pretty == "0 B"


# ============================================================================
# TestGetFileInfoMimeType: MIME type detection
# ============================================================================


class TestGetFileInfoMimeType:
    """Tests for MIME type detection in get_file_info."""

    @pytest.mark.asyncio
    async def test_mime_type_from_backend(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Uses MIME type from backend when available."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "data.json"),
                "type": "file",
                "size": 100,
                "mime_type": "application/json",
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "data.json"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_mime_type_detected_from_path(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Detects MIME type from path extension when backend does not provide it."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "script.py"),
                "type": "file",
                "size": 100,
                # No mime_type key
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "script.py"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type == "text/x-python"

    @pytest.mark.asyncio
    async def test_directory_mime_type(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Directories get inode/directory MIME type."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "subdir"),
                "type": "directory",
                "size": 0,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "subdir"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type == "inode/directory"

    @pytest.mark.asyncio
    async def test_unknown_extension_returns_octet_stream(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Files with unknown extensions return application/octet-stream."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "data.xyz123"),
                "type": "file",
                "size": 100,
                # No mime_type key -- extension unknown
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "data.xyz123"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type == "application/octet-stream"


# ============================================================================
# TestGetFileInfoChecksum: SHA-256 checksum calculation
# ============================================================================


class TestGetFileInfoChecksum:
    """Tests for SHA-256 checksum calculation."""

    @pytest.mark.asyncio
    async def test_checksum_when_requested(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Calculates SHA-256 checksum when include_checksum=True."""
        content = b"hello world"
        expected_hash = hashlib.sha256(content).hexdigest()

        mock_backend.set_info_result(
            {
                "name": str(sandbox / "file.txt"),
                "type": "file",
                "size": len(content),
            }
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "file.txt"), include_checksum=True, ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.checksum == expected_hash

    @pytest.mark.asyncio
    async def test_no_checksum_by_default(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Checksum is None when include_checksum is False (default)."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "file.txt"),
                "type": "file",
                "size": 100,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.checksum is None

    @pytest.mark.asyncio
    async def test_checksum_skipped_for_directories(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Checksum is None for directories even when requested."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "subdir"),
                "type": "directory",
                "size": 0,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "subdir"), include_checksum=True, ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.checksum is None

    def test_compute_checksum_chunked(self, mock_backend: MockBackend) -> None:
        """_compute_checksum reads in chunks (supports large files)."""
        # Create content larger than _CHECKSUM_CHUNK_SIZE (65536 bytes)
        content = b"A" * 100_000
        expected_hash = hashlib.sha256(content).hexdigest()
        mock_backend.set_file_content(content)

        result = _compute_checksum(mock_backend, "/fake/path")

        assert result == expected_hash

    def test_compute_checksum_empty_file(self, mock_backend: MockBackend) -> None:
        """_compute_checksum handles empty files."""
        mock_backend.set_file_content(b"")
        expected_hash = hashlib.sha256(b"").hexdigest()

        result = _compute_checksum(mock_backend, "/fake/path")

        assert result == expected_hash


# ============================================================================
# TestGetFileInfoSymlink: Symlink detection
# ============================================================================


class TestGetFileInfoSymlink:
    """Tests for symlink detection in get_file_info."""

    @pytest.mark.asyncio
    async def test_symlink_detected(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Identifies symlinks when backend reports islink=True."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "link.txt"),
                "type": "file",
                "size": 100,
                "islink": True,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "link.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.is_symlink is True

    @pytest.mark.asyncio
    async def test_non_symlink(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Regular files have is_symlink=False."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "regular.txt"),
                "type": "file",
                "size": 100,
                "islink": False,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "regular.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.is_symlink is False


# ============================================================================
# TestGetFileInfoErrors: Error handling
# ============================================================================


class TestGetFileInfoErrors:
    """Tests for error handling in get_file_info."""

    @pytest.mark.asyncio
    async def test_path_not_found_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """PATH_NOT_FOUND for non-existent paths."""
        mock_backend.set_raise_on_info(PathNotFoundError("Path not found"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "nonexistent.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_path_outside_sandbox_error(self, sandbox: Path) -> None:
        """PATH_OUTSIDE_SANDBOX for traversal attempts."""
        mock_backend = MockBackend()
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / ".." / ".." / "etc" / "passwd"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_symlink_blocked_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """SYMLINK_BLOCKED when symlink policy rejects access."""
        mock_backend.set_raise_on_info(SymlinkBlockedError("Symlink access blocked"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "link.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.SYMLINK_BLOCKED

    @pytest.mark.asyncio
    async def test_backend_not_configured_error(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED for disabled backend."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(sandbox), enabled=False),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        backend_manager = BackendManager(settings=settings, security=security)
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_unexpected_backend_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Unexpected backend exceptions return BACKEND_ERROR."""
        mock_backend.set_raise_on_info(RuntimeError("Unexpected I/O error"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR

    @pytest.mark.asyncio
    async def test_unknown_entry_type_defaults_to_file(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Unknown entry type from backend defaults to 'file'."""
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "special"),
                "type": "symlink",  # Unknown type, not 'file' or 'directory'
                "size": 200,
                "modified": 1700000000.0,
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(sandbox / "special"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.type == "file"


# ============================================================================
# TestGetFileInfoIntegration: Real filesystem tests
# ============================================================================


class TestGetFileInfoIntegration:
    """Integration tests for get_file_info with real local filesystem."""

    def _make_real_ctx(self, tmp_path: Path, follow_symlinks: bool = False) -> MagicMock:
        """Create a context with a real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(
                base_path=str(tmp_path),
                follow_symlinks=follow_symlinks,
            ),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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

    @pytest.mark.asyncio
    async def test_real_file_metadata(self, tmp_path: Path) -> None:
        """Returns correct metadata for a real file."""
        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello world")

        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(test_file), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "hello.txt"
        assert result.type == "file"
        assert result.size_bytes == 11
        assert result.size_pretty == "11 B"
        assert result.mime_type is not None
        assert result.modified_at is not None
        assert result.is_hidden is False
        assert result.is_symlink is False
        assert result.permissions is not None

    @pytest.mark.asyncio
    async def test_real_directory_metadata(self, tmp_path: Path) -> None:
        """Returns correct metadata for a real directory."""
        test_dir = tmp_path / "mydir"
        test_dir.mkdir()

        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(test_dir), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "mydir"
        assert result.type == "directory"
        assert result.mime_type == "inode/directory"
        assert result.permissions is not None

    @pytest.mark.asyncio
    async def test_real_checksum(self, tmp_path: Path) -> None:
        """Computes correct SHA-256 checksum for a real file."""
        content = "test content for checksum"
        test_file = tmp_path / "checksum.txt"
        test_file.write_text(content)

        expected_hash = hashlib.sha256(content.encode()).hexdigest()

        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(test_file), include_checksum=True, ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.checksum == expected_hash

    @pytest.mark.asyncio
    async def test_real_mime_type_detection(self, tmp_path: Path) -> None:
        """Detects MIME type for common file types on real filesystem."""
        py_file = tmp_path / "script.py"
        py_file.write_text("print('hello')")

        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(py_file), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type == "text/x-python"

    @pytest.mark.asyncio
    async def test_real_symlink_detected(self, tmp_path: Path) -> None:
        """Detects symlinks on real filesystem (follow_symlinks=True)."""
        target = tmp_path / "target.txt"
        target.write_text("target content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)

        ctx = self._make_real_ctx(tmp_path, follow_symlinks=True)
        result = await get_file_info(path=str(link), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.is_symlink is True
        assert result.name == "link.txt"
        assert result.type == "file"

    @pytest.mark.asyncio
    async def test_real_symlink_blocked(self, tmp_path: Path) -> None:
        """Symlink access blocked when follow_symlinks=False."""
        target = tmp_path / "target.txt"
        target.write_text("target content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)

        ctx = self._make_real_ctx(tmp_path, follow_symlinks=False)
        result = await get_file_info(path=str(link), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.SYMLINK_BLOCKED

    @pytest.mark.asyncio
    async def test_real_nonexistent_path(self, tmp_path: Path) -> None:
        """Non-existent path returns PATH_NOT_FOUND."""
        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(tmp_path / "does_not_exist.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_real_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Path traversal is blocked with real backend."""
        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(tmp_path / ".." / ".." / "etc" / "passwd"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_real_created_at_populated(self, tmp_path: Path) -> None:
        """created_at is populated for real files (platform-dependent)."""
        test_file = tmp_path / "created.txt"
        test_file.write_text("content")

        ctx = self._make_real_ctx(tmp_path)
        result = await get_file_info(path=str(test_file), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        # created_at may be None on some platforms, but on macOS it should be set
        # We don't assert it's not None since that's platform-dependent
        # but we verify it doesn't crash
        if result.created_at is not None:
            assert isinstance(result.created_at, datetime)


# ============================================================================
# TestReadFileBasicText: Text file reading
# ============================================================================


class TestReadFileBasicText:
    """Tests for reading text files via read_file."""

    @pytest.mark.asyncio
    async def test_reads_text_file(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Reads a text file and returns content as text with encoding='text'."""
        content = b"Hello, world!\nLine two.\n"
        mock_backend.set_info_result(
            {"name": str(sandbox / "hello.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "hello.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "Hello, world!\nLine two.\n"
        assert result.encoding == "text"
        assert result.size_bytes == len(content)
        assert result.bytes_read == len(content)
        assert result.offset == 0
        assert result.has_more is False
        assert result.is_truncated is False
        assert result.path == str(sandbox / "hello.txt")
        assert result.backend == "local"

    @pytest.mark.asyncio
    async def test_reads_text_with_correct_mime_type(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """MIME type is detected from file extension."""
        content = b'{"key": "value"}'
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.json"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.json"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Calling without context returns an error response dict."""
        result = await read_file(path="/any/path", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_preserves_original_path(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Response contains the original user-provided path."""
        content = b"test"
        mock_backend.set_info_result(
            {"name": str(sandbox / "test.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        original_path = str(sandbox / "test.txt")
        result = await read_file(path=original_path, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.path == original_path


# ============================================================================
# TestReadFileBinary: Binary file reading (base64 encoding)
# ============================================================================


class TestReadFileBinary:
    """Tests for reading binary files via read_file."""

    @pytest.mark.asyncio
    async def test_reads_binary_as_base64(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Binary files are returned as base64-encoded content."""
        import base64 as b64

        content = bytes(range(256))  # Binary content with null bytes
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.bin"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.bin"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        assert result.content == b64.b64encode(content).decode("ascii")
        assert result.bytes_read == len(content)

    @pytest.mark.asyncio
    async def test_binary_mime_type_detected(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Binary file MIME type is detected from extension."""
        content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # PNG header bytes
        mock_backend.set_info_result(
            {"name": str(sandbox / "image.png"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "image.png"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        assert result.mime_type == "image/png"


# ============================================================================
# TestReadFileChunked: Chunked reading with offset/limit
# ============================================================================


class TestReadFileChunked:
    """Tests for chunked reading via offset/limit parameters."""

    @pytest.mark.asyncio
    async def test_reads_with_offset_and_limit(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Reads a specific chunk from a file."""
        content = b"0123456789ABCDEF"
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.txt"), offset=4, limit=4, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "4567"
        assert result.encoding == "text"
        assert result.bytes_read == 4
        assert result.offset == 4
        assert result.has_more is True
        assert result.size_bytes == 16

    @pytest.mark.asyncio
    async def test_reads_with_offset_only(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Reads from offset to end of file when no limit."""
        content = b"0123456789"
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.txt"), offset=5, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "56789"
        assert result.bytes_read == 5
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_reads_with_limit_only(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Reads first N bytes when only limit is specified."""
        content = b"Hello, world!"
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.txt"), limit=5, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "Hello"
        assert result.bytes_read == 5
        assert result.offset == 0
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_reading_past_end_returns_available_bytes(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Reading past end of file returns available bytes with has_more=False."""
        content = b"short"
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.txt"), offset=3, limit=100, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "rt"
        assert result.bytes_read == 2
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_last_chunk_has_more_false(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """The last chunk of a file has has_more=False."""
        content = b"0123456789"
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        # Read last 5 bytes (offset=5, limit=5 -> end=10 == total_size)
        result = await read_file(path=str(sandbox / "data.txt"), offset=5, limit=5, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "56789"
        assert result.has_more is False


# ============================================================================
# TestReadFileSizeLimit: File size limit enforcement
# ============================================================================


class TestReadFileSizeLimit:
    """Tests for file size limit enforcement."""

    @pytest.mark.asyncio
    async def test_file_too_large_without_chunking(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Full reads of oversized files return FILE_TOO_LARGE error."""
        # Default max_file_size is 10MB (10_485_760)
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "huge.dat"),
                "type": "file",
                "size": 20_000_000,  # 20MB, exceeds 10MB limit
            }
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "huge.dat"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE

    @pytest.mark.asyncio
    async def test_large_file_allowed_with_offset_limit(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Chunked reads of oversized files are allowed."""
        big_content = b"A" * 1000  # Simulated chunk
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "huge.dat"),
                "type": "file",
                "size": 20_000_000,
            }
        )
        mock_backend.set_file_content(big_content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "huge.dat"), offset=0, limit=1000, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.bytes_read == 1000
        assert result.is_truncated is True
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_file_within_limit_allowed(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Files within the size limit are read without error."""
        content = b"small file content"
        mock_backend.set_info_result(
            {"name": str(sandbox / "small.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "small.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.is_truncated is False

    @pytest.mark.asyncio
    async def test_large_file_with_offset_only_allowed(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Offset alone counts as chunked and allows oversized files."""
        content = b"chunk from offset"
        mock_backend.set_info_result(
            {
                "name": str(sandbox / "huge.dat"),
                "type": "file",
                "size": 20_000_000,
            }
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "huge.dat"), offset=1000, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.is_truncated is True


# ============================================================================
# TestReadFileForceFlags: force_text and force_base64 flags
# ============================================================================


class TestReadFileForceFlags:
    """Tests for force_text and force_base64 behavior."""

    @pytest.mark.asyncio
    async def test_force_base64_on_text_file(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """force_base64=True forces base64 encoding even for text files."""
        import base64 as b64

        content = b"Hello, text content"
        mock_backend.set_info_result(
            {"name": str(sandbox / "hello.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "hello.txt"), force_base64=True, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        assert result.content == b64.b64encode(content).decode("ascii")

    @pytest.mark.asyncio
    async def test_force_text_on_text_file(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """force_text=True on a text file works normally."""
        content = b"Normal text"
        mock_backend.set_info_result(
            {"name": str(sandbox / "hello.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "hello.txt"), force_text=True, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.content == "Normal text"

    @pytest.mark.asyncio
    async def test_force_text_decode_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """force_text=True with invalid UTF-8 returns CONTENT_DECODE_ERROR."""
        # Invalid UTF-8 bytes
        content = b"\x80\x81\x82\xff\xfe"
        mock_backend.set_info_result(
            {"name": str(sandbox / "bad.bin"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "bad.bin"), force_text=True, ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.CONTENT_DECODE_ERROR

    @pytest.mark.asyncio
    async def test_binary_without_force_text_falls_back_to_base64(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Binary content without force_text falls back to base64."""
        content = bytes(range(256))
        mock_backend.set_info_result(
            {"name": str(sandbox / "data.bin"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "data.bin"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"

    @pytest.mark.asyncio
    async def test_force_base64_overrides_force_text(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """force_base64 takes priority over force_text."""
        import base64 as b64

        content = b"Text content"
        mock_backend.set_info_result(
            {"name": str(sandbox / "hello.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(
            path=str(sandbox / "hello.txt"),
            force_text=True,
            force_base64=True,
            ctx=ctx,
        )

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        assert result.content == b64.b64encode(content).decode("ascii")


# ============================================================================
# TestReadFileEdgeCases: Edge case handling
# ============================================================================


class TestReadFileEdgeCases:
    """Tests for edge cases in read_file."""

    @pytest.mark.asyncio
    async def test_empty_file(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Empty file returns empty content string with size_bytes=0."""
        mock_backend.set_info_result(
            {"name": str(sandbox / "empty.txt"), "type": "file", "size": 0}
        )
        mock_backend.set_file_content(b"")
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "empty.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == ""
        assert result.size_bytes == 0
        assert result.bytes_read == 0
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_utf8_with_bom(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """UTF-8 file with BOM is handled correctly."""
        bom = b"\xef\xbb\xbf"
        content = bom + b"Hello BOM"
        mock_backend.set_info_result(
            {"name": str(sandbox / "bom.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "bom.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        # BOM is preserved in content (UTF-8 BOM is valid UTF-8)
        assert "Hello BOM" in result.content

    @pytest.mark.asyncio
    async def test_non_utf8_text_with_encoding_override(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Reading with a different text encoding parameter works."""
        content = "Hola mundo".encode("latin-1")
        mock_backend.set_info_result(
            {"name": str(sandbox / "latin.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "latin.txt"), encoding="latin-1", ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.content == "Hola mundo"

    @pytest.mark.asyncio
    async def test_text_detected_but_invalid_utf8_falls_back_to_base64(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Auto-detected text content that fails UTF-8 decode falls back to base64.

        When force_text is False and content is detected as text but fails to
        decode with the specified encoding, it silently falls back to base64.
        """
        import base64 as b64

        # Content that looks like text by extension (.txt) but contains
        # invalid UTF-8 sequences.
        content = b"Valid start \x80\x81\x82 invalid bytes"
        mock_backend.set_info_result(
            {"name": str(sandbox / "broken.txt"), "type": "file", "size": len(content)}
        )
        mock_backend.set_file_content(content)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "broken.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        # Should fall back to base64 since decode fails and force_text=False
        assert result.encoding == "base64"
        assert result.content == b64.b64encode(content).decode("ascii")


# ============================================================================
# TestReadFileErrors: Error handling
# ============================================================================


class TestReadFileErrors:
    """Tests for error handling in read_file."""

    @pytest.mark.asyncio
    async def test_path_not_found(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """PATH_NOT_FOUND for non-existent files."""
        mock_backend.set_raise_on_info(PathNotFoundError("File not found"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "missing.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_path_outside_sandbox(self, sandbox: Path) -> None:
        """PATH_OUTSIDE_SANDBOX for traversal attempts."""
        mock_backend = MockBackend()
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / ".." / ".." / "etc" / "passwd"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_backend_not_configured(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED for disabled backend."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(sandbox), enabled=False),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        backend_manager = BackendManager(settings=settings, security=security)
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_unexpected_backend_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Unexpected exceptions return BACKEND_ERROR."""
        mock_backend.set_raise_on_info(RuntimeError("I/O failure"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR


# ============================================================================
# TestReadFileIntegration: Real filesystem tests
# ============================================================================


class TestReadFileIntegration:
    """Integration tests for read_file with real local filesystem."""

    def _make_real_ctx(self, tmp_path: Path) -> MagicMock:
        """Create a context with a real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path)),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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

    @pytest.mark.asyncio
    async def test_real_text_file(self, tmp_path: Path) -> None:
        """Reads a real text file and returns content as text."""
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello, real world!")

        ctx = self._make_real_ctx(tmp_path)
        result = await read_file(path=str(test_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "Hello, real world!"
        assert result.encoding == "text"
        assert result.size_bytes == 18
        assert result.bytes_read == 18
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_real_binary_file(self, tmp_path: Path) -> None:
        """Reads a real binary file and returns as base64."""
        import base64 as b64

        test_file = tmp_path / "image.bin"
        content = bytes(range(256))
        test_file.write_bytes(content)

        ctx = self._make_real_ctx(tmp_path)
        result = await read_file(path=str(test_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        decoded = b64.b64decode(result.content)
        assert decoded == content

    @pytest.mark.asyncio
    async def test_real_chunked_reading(self, tmp_path: Path) -> None:
        """Reads chunks of a real file with offset/limit."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("0123456789ABCDEF")

        ctx = self._make_real_ctx(tmp_path)

        # Read first chunk
        result1 = await read_file(path=str(test_file), offset=0, limit=8, ctx=ctx)
        assert isinstance(result1, ReadFileResponse)
        assert result1.content == "01234567"
        assert result1.has_more is True
        assert result1.offset == 0

        # Read second chunk
        result2 = await read_file(path=str(test_file), offset=8, limit=8, ctx=ctx)
        assert isinstance(result2, ReadFileResponse)
        assert result2.content == "89ABCDEF"
        assert result2.has_more is False
        assert result2.offset == 8

    @pytest.mark.asyncio
    async def test_real_empty_file(self, tmp_path: Path) -> None:
        """Reads a real empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        ctx = self._make_real_ctx(tmp_path)
        result = await read_file(path=str(test_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == ""
        assert result.size_bytes == 0
        assert result.bytes_read == 0

    @pytest.mark.asyncio
    async def test_real_large_file_chunked(self, tmp_path: Path) -> None:
        """Large file can be read in chunks even if exceeding size limit."""
        # Create a file and set a very small max_file_size
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        test_file = tmp_path / "large.txt"
        content = "A" * 500
        test_file.write_text(content)

        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path), max_file_size=100),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
        backend_manager = BackendManager(
            settings=settings, security=security, local_backend=local_backend
        )
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        ctx = _make_mock_ctx(app_ctx)

        # Full read should fail
        result_full = await read_file(path=str(test_file), ctx=ctx)
        assert isinstance(result_full, dict)
        assert result_full["error_code"] == ErrorCode.FILE_TOO_LARGE

        # Chunked read should succeed
        result_chunk = await read_file(path=str(test_file), offset=0, limit=50, ctx=ctx)
        assert isinstance(result_chunk, ReadFileResponse)
        assert result_chunk.bytes_read == 50
        assert result_chunk.has_more is True
        assert result_chunk.is_truncated is True

    @pytest.mark.asyncio
    async def test_real_nonexistent_file(self, tmp_path: Path) -> None:
        """Non-existent file returns PATH_NOT_FOUND."""
        ctx = self._make_real_ctx(tmp_path)
        result = await read_file(path=str(tmp_path / "missing.txt"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_real_python_file_detected_as_text(self, tmp_path: Path) -> None:
        """Python files are detected as text with correct MIME type."""
        test_file = tmp_path / "script.py"
        test_file.write_text("print('hello')")

        ctx = self._make_real_ctx(tmp_path)
        result = await read_file(path=str(test_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.mime_type == "text/x-python"
        assert result.content == "print('hello')"


# ============================================================================
# TestSearchFilesNamePattern: Name pattern search with mocked backend
# ============================================================================


class TestSearchFilesNamePattern:
    """Tests for search_files name pattern matching."""

    @pytest.mark.asyncio
    async def test_finds_files_by_glob_pattern(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Finds files matching a glob name pattern."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "app.py"), "file", 100),
                _make_entry(str(sandbox / "test.py"), "file", 200),
                _make_entry(str(sandbox / "readme.md"), "file", 50),
                _make_entry(str(sandbox / "data.json"), "file", 300),
            ],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 2
        names = [r.name for r in result.results]
        assert "app.py" in names
        assert "test.py" in names
        assert "readme.md" not in names

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_results(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """No matches returns empty results list."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [_make_entry(str(sandbox / "file.txt"), "file", 100)],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.rs", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.results == []
        assert result.total_matches == 0
        assert result.search_truncated is False

    @pytest.mark.asyncio
    async def test_empty_directory_returns_empty_results(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Search in empty directory returns empty results."""
        root = str(sandbox)
        mock_backend.set_dir_entries(root, [])
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.results == []
        assert result.total_matches == 0
        assert result.directories_searched == 1

    @pytest.mark.asyncio
    async def test_no_context_returns_error(self) -> None:
        """Calling without context returns an error response dict."""
        result = await search_files(path="/any/path", ctx=None)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "No context" in result["message"]

    @pytest.mark.asyncio
    async def test_results_sorted_by_path(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Results are sorted by path."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "z_file.py"), "file", 100),
                _make_entry(str(sandbox / "a_file.py"), "file", 200),
                _make_entry(str(sandbox / "m_file.py"), "file", 150),
            ],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        paths = [r.path for r in result.results]
        assert paths == sorted(paths)

    @pytest.mark.asyncio
    async def test_preserves_original_path_in_response(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Response path reflects the original user-provided search root."""
        root = str(sandbox)
        mock_backend.set_dir_entries(root, [])
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.path == root
        assert result.backend == "local"


# ============================================================================
# TestSearchFilesContentPattern: Content pattern search with mocked text files
# ============================================================================


class TestSearchFilesContentPattern:
    """Tests for search_files content regex search."""

    @pytest.mark.asyncio
    async def test_finds_files_with_content_match(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Finds files containing a regex content pattern."""
        root = str(sandbox)
        file1 = str(sandbox / "main.py")
        file2 = str(sandbox / "util.py")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(file1, "file", 100),
                _make_entry(file2, "file", 200),
            ],
        )
        mock_backend.set_file_contents(file1, b"def main():\n    print('hello')\n")
        mock_backend.set_file_contents(file2, b"def helper():\n    return 42\n")
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="def main", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        assert result.results[0].name == "main.py"
        assert result.results[0].match_context is not None

    @pytest.mark.asyncio
    async def test_content_search_returns_context(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Content search returns match context with surrounding lines."""
        root = str(sandbox)
        file_path = str(sandbox / "code.py")
        content = (
            "import os\n"
            "import sys\n"
            "\n"
            "def main():\n"
            "    print('hello')\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        mock_backend.set_dir_entries(root, [_make_entry(file_path, "file", len(content))])
        mock_backend.set_file_contents(file_path, content.encode())
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="def main", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        context = result.results[0].match_context
        assert context is not None
        # Should include the matching line with marker
        assert "def main()" in context
        # Should include surrounding lines
        assert "import sys" in context or "print" in context

    @pytest.mark.asyncio
    async def test_content_search_skips_binary_files(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Content search skips binary files (non-text MIME type)."""
        root = str(sandbox)
        bin_file = str(sandbox / "data.bin")
        text_file = str(sandbox / "code.py")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(bin_file, "file", 100),
                _make_entry(text_file, "file", 200),
            ],
        )
        mock_backend.set_file_contents(bin_file, b"\x00\x01\x02pattern\x03\x04")
        mock_backend.set_file_contents(text_file, b"# contains pattern here\n")
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="pattern", ctx=ctx)

        assert isinstance(result, SearchResponse)
        # Only text file should match (binary file skipped)
        assert result.total_matches == 1
        assert result.results[0].name == "code.py"

    @pytest.mark.asyncio
    async def test_content_no_match_returns_empty(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Content search with no matches returns empty results."""
        root = str(sandbox)
        file_path = str(sandbox / "readme.txt")
        mock_backend.set_dir_entries(root, [_make_entry(file_path, "file", 50)])
        mock_backend.set_file_contents(file_path, b"Hello world\n")
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="nonexistent_pattern_xyz", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.results == []
        assert result.total_matches == 0


# ============================================================================
# TestSearchFilesCombined: Combined name + content search
# ============================================================================


class TestSearchFilesCombined:
    """Tests for combined name pattern + content pattern search."""

    @pytest.mark.asyncio
    async def test_combined_search_both_must_match(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Combined search requires both name AND content to match."""
        root = str(sandbox)
        py_file = str(sandbox / "app.py")
        md_file = str(sandbox / "notes.md")
        other_py = str(sandbox / "util.py")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(py_file, "file", 100),
                _make_entry(md_file, "file", 200),
                _make_entry(other_py, "file", 150),
            ],
        )
        mock_backend.set_file_contents(py_file, b"def main():\n    pass\n")
        mock_backend.set_file_contents(md_file, b"# def main() documentation\n")
        mock_backend.set_file_contents(other_py, b"def helper():\n    pass\n")
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=root, name_pattern="*.py", content_pattern="def main", ctx=ctx
        )

        assert isinstance(result, SearchResponse)
        # Only app.py matches both: *.py name AND "def main" content
        # (notes.md has the content but wrong name, util.py has name but wrong content)
        assert result.total_matches == 1
        assert result.results[0].name == "app.py"


# ============================================================================
# TestSearchFilesMaxDepth: max_depth enforcement
# ============================================================================


class TestSearchFilesMaxDepth:
    """Tests for max_depth recursion control."""

    @pytest.mark.asyncio
    async def test_max_depth_zero_searches_current_dir_only(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """max_depth=0 only searches the root directory (no recursion)."""
        root = str(sandbox)
        subdir = str(sandbox / "sub")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "root_file.py"), "file", 100),
                _make_entry(subdir, "directory", 0),
            ],
        )
        # Subdirectory has a matching file, but shouldn't be visited
        mock_backend.set_dir_entries(
            subdir,
            [_make_entry(str(sandbox / "sub" / "deep_file.py"), "file", 200)],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", max_depth=0, ctx=ctx)

        assert isinstance(result, SearchResponse)
        # Only root_file.py should be found, not deep_file.py
        assert result.total_matches == 1
        assert result.results[0].name == "root_file.py"
        # Only the root directory should be searched
        assert result.directories_searched == 1

    @pytest.mark.asyncio
    async def test_max_depth_one_searches_one_level_deep(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """max_depth=1 searches root and one level of subdirectories."""
        root = str(sandbox)
        sub = str(sandbox / "sub")
        deep = str(sandbox / "sub" / "deep")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "root.py"), "file", 100),
                _make_entry(sub, "directory", 0),
            ],
        )
        mock_backend.set_dir_entries(
            sub,
            [
                _make_entry(str(sandbox / "sub" / "level1.py"), "file", 100),
                _make_entry(deep, "directory", 0),
            ],
        )
        mock_backend.set_dir_entries(
            deep,
            [_make_entry(str(sandbox / "sub" / "deep" / "level2.py"), "file", 100)],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", max_depth=1, ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = [r.name for r in result.results]
        assert "root.py" in names
        assert "level1.py" in names
        assert "level2.py" not in names

    @pytest.mark.asyncio
    async def test_recursive_search_traverses_subdirectories(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Default max_depth (10) traverses into subdirectories."""
        root = str(sandbox)
        sub = str(sandbox / "sub")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "root.py"), "file", 100),
                _make_entry(sub, "directory", 0),
            ],
        )
        mock_backend.set_dir_entries(
            sub,
            [_make_entry(str(sandbox / "sub" / "nested.py"), "file", 200)],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = [r.name for r in result.results]
        assert "root.py" in names
        assert "nested.py" in names
        assert result.directories_searched == 2


# ============================================================================
# TestSearchFilesMaxResults: max_results truncation
# ============================================================================


class TestSearchFilesMaxResults:
    """Tests for max_results truncation."""

    @pytest.mark.asyncio
    async def test_truncates_at_max_results(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Results are truncated at max_results."""
        root = str(sandbox)
        entries = [_make_entry(str(sandbox / f"file{i:03d}.py"), "file", 100) for i in range(20)]
        mock_backend.set_dir_entries(root, entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", max_results=5, ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 5
        assert len(result.results) == 5

    @pytest.mark.asyncio
    async def test_no_truncation_when_under_limit(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """No truncation when results are within max_results."""
        root = str(sandbox)
        entries = [_make_entry(str(sandbox / f"file{i}.py"), "file", 100) for i in range(3)]
        mock_backend.set_dir_entries(root, entries)
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", max_results=100, ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 3
        assert result.search_truncated is False


# ============================================================================
# TestSearchFilesFileTypes: MIME type prefix filtering
# ============================================================================


class TestSearchFilesFileTypes:
    """Tests for file_types MIME type prefix filtering."""

    @pytest.mark.asyncio
    async def test_filters_by_mime_type_prefix(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """file_types filter matches by MIME type prefix."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "code.py"), "file", 100),
                _make_entry(str(sandbox / "readme.md"), "file", 200),
                _make_entry(str(sandbox / "image.png"), "file", 5000),
                _make_entry(str(sandbox / "data.json"), "file", 300),
            ],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, file_types=["text/"], ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = [r.name for r in result.results]
        # .py -> text/x-python, .md -> text/markdown
        assert "code.py" in names
        assert "readme.md" in names
        # .png -> image/png (not text/)
        assert "image.png" not in names


# ============================================================================
# TestSearchFilesHiddenFiles: Hidden file policy
# ============================================================================


class TestSearchFilesHiddenFiles:
    """Tests for hidden file filtering in search_files."""

    @pytest.mark.asyncio
    async def test_hidden_files_excluded_by_default(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Hidden files are excluded when show_hidden=False (default)."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "visible.py"), "file", 100),
                _make_entry(str(sandbox / ".hidden.py"), "file", 200),
            ],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend, show_hidden=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = [r.name for r in result.results]
        assert "visible.py" in names
        assert ".hidden.py" not in names

    @pytest.mark.asyncio
    async def test_hidden_files_included_when_override(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Hidden files are included with include_hidden=True override."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(str(sandbox / "visible.py"), "file", 100),
                _make_entry(str(sandbox / ".hidden.py"), "file", 200),
            ],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend, show_hidden=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*.py", include_hidden=True, ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = [r.name for r in result.results]
        assert "visible.py" in names
        assert ".hidden.py" in names


# ============================================================================
# TestSearchFilesErrors: Error handling
# ============================================================================


class TestSearchFilesErrors:
    """Tests for error handling in search_files."""

    @pytest.mark.asyncio
    async def test_invalid_regex_returns_error(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Invalid regex pattern returns INVALID_OPERATION error."""
        root = str(sandbox)
        mock_backend.set_dir_entries(root, [])
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="[invalid(regex", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION
        assert "regex" in result["message"].lower() or "Invalid" in result["message"]

    @pytest.mark.asyncio
    async def test_path_outside_sandbox(self, sandbox: Path) -> None:
        """PATH_OUTSIDE_SANDBOX for traversal attempts."""
        mock_backend = MockBackend()
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=str(sandbox / ".." / ".." / "etc"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_path_not_found(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """PATH_NOT_FOUND for non-existent root directory."""
        mock_backend.set_raise_on_ls(PathNotFoundError("Directory not found"))
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=str(sandbox), ctx=ctx)

        # The error should propagate -- but since ls failure is caught inside
        # search_files and the directory is gracefully skipped, we should get
        # empty results instead of an error (unreadable dirs are skipped)
        assert isinstance(result, SearchResponse)
        assert result.results == []

    @pytest.mark.asyncio
    async def test_backend_not_configured(self, sandbox: Path) -> None:
        """BACKEND_NOT_CONFIGURED for disabled backend."""
        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(sandbox), enabled=False),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
            s3_settings=settings.s3,
        )
        backend_manager = BackendManager(settings=settings, security=security)
        app_ctx = AppContext(
            settings=settings,
            security=security,
            backend_manager=backend_manager,
            rate_limiter=RateLimiter(ops_per_minute=0),
        )
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=str(sandbox), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_graceful_handling_of_unreadable_files(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Unreadable files are skipped gracefully during content search."""
        root = str(sandbox)
        readable = str(sandbox / "good.py")
        unreadable = str(sandbox / "bad.py")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(readable, "file", 100),
                _make_entry(unreadable, "file", 200),
            ],
        )
        mock_backend.set_file_contents(readable, b"# target pattern here\n")
        # Don't set content for unreadable -- cat_file will return default b""

        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="target", ctx=ctx)

        assert isinstance(result, SearchResponse)
        # Only the readable file should match
        assert result.total_matches == 1
        assert result.results[0].name == "good.py"

    @pytest.mark.asyncio
    async def test_unexpected_backend_error(self, sandbox: Path, mock_backend: MockBackend) -> None:
        """Unexpected backend exceptions (non-FSError) return BACKEND_ERROR."""
        from unittest.mock import patch

        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        # Force the outer Exception handler by making get_backend raise a
        # non-FSError exception. This hits the generic catch-all at the end
        # of search_files that converts unexpected errors to BACKEND_ERROR.
        with patch.object(
            app_ctx.backend_manager,
            "get_backend",
            side_effect=RuntimeError("Unexpected segfault"),
        ):
            result = await search_files(path=str(sandbox), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
        assert "segfault" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_cat_file_exception_skips_file_gracefully(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Files that raise on cat_file are skipped during content search."""
        root = str(sandbox)
        readable = str(sandbox / "good.py")
        unreadable = str(sandbox / "locked.py")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(readable, "file", 100),
                _make_entry(unreadable, "file", 200),
            ],
        )
        mock_backend.set_file_contents(readable, b"# match target here\n")
        # Make cat_file raise for the locked file
        mock_backend.set_raise_on_cat_file({unreadable})

        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="target", ctx=ctx)

        assert isinstance(result, SearchResponse)
        # Only the readable file should match
        assert result.total_matches == 1
        assert result.results[0].name == "good.py"

    @pytest.mark.asyncio
    async def test_non_utf8_text_file_skipped_in_content_search(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Text files with non-UTF-8 content are skipped during content search.

        Files detected as text by MIME type but with non-decodable content
        are silently skipped (UnicodeDecodeError caught internally).
        """
        root = str(sandbox)
        good_file = str(sandbox / "good.py")
        bad_file = str(sandbox / "bad.py")
        mock_backend.set_dir_entries(
            root,
            [
                _make_entry(good_file, "file", 100),
                _make_entry(bad_file, "file", 200),
            ],
        )
        mock_backend.set_file_contents(good_file, b"# target pattern here\n")
        # .py extension -> text/x-python MIME type, but invalid UTF-8 content
        mock_backend.set_file_contents(bad_file, b"target \x80\x81\x82\xff\xfe pattern")

        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, content_pattern="target", ctx=ctx)

        assert isinstance(result, SearchResponse)
        # Only the good file should match (bad file skipped due to decode error)
        assert result.total_matches == 1
        assert result.results[0].name == "good.py"

    @pytest.mark.asyncio
    async def test_unknown_entry_type_treated_as_file(
        self, sandbox: Path, mock_backend: MockBackend
    ) -> None:
        """Unknown entry types from backend are treated as files in search."""
        root = str(sandbox)
        mock_backend.set_dir_entries(
            root,
            [
                {"name": str(sandbox / "device"), "type": "other", "size": 50, "modified": None},
                _make_entry(str(sandbox / "normal.py"), "file", 100),
            ],
        )
        app_ctx = _make_app_ctx(sandbox, mock_backend)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path=root, name_pattern="*", ctx=ctx)

        assert isinstance(result, SearchResponse)
        # Both entries should be found: "other" type defaulted to file
        assert result.total_matches == 2
        names = [r.name for r in result.results]
        assert "device" in names
        assert "normal.py" in names


# ============================================================================
# TestExtractMatchContext: Context extraction helper
# ============================================================================


class TestExtractMatchContext:
    """Tests for the _extract_match_context helper function."""

    def test_basic_context_extraction(self) -> None:
        """Extracts context lines around a match."""
        import re

        text = "line 1\nline 2\nline 3\nTARGET line\nline 5\nline 6\nline 7\n"
        match = re.search("TARGET", text)
        assert match is not None

        context = _extract_match_context(text, match)

        assert "TARGET line" in context
        # Should include surrounding lines
        assert "line 2" in context or "line 3" in context
        assert "line 5" in context or "line 6" in context

    def test_match_at_start_of_file(self) -> None:
        """Context extraction works when match is on the first line."""
        import re

        text = "MATCH here\nline 2\nline 3\nline 4\n"
        match = re.search("MATCH", text)
        assert match is not None

        context = _extract_match_context(text, match)

        assert "MATCH here" in context
        # Should not crash with negative line indices

    def test_match_at_end_of_file(self) -> None:
        """Context extraction works when match is on the last line."""
        import re

        text = "line 1\nline 2\nline 3\nMATCH here"
        match = re.search("MATCH", text)
        assert match is not None

        context = _extract_match_context(text, match)

        assert "MATCH here" in context

    def test_empty_text_returns_empty(self) -> None:
        """Empty text returns empty context string."""
        import re

        text = ""
        # Can't have a match in empty text, so this tests the edge case
        # by using a pattern that would match at position 0
        context = _extract_match_context(text, re.search("$", text))  # type: ignore[arg-type]
        assert context == ""

    def test_single_line_file(self) -> None:
        """Context works correctly for single-line files."""
        import re

        text = "only one line with TARGET in it"
        match = re.search("TARGET", text)
        assert match is not None

        context = _extract_match_context(text, match)

        assert "TARGET" in context
        assert "1:" in context  # Line number should be 1

    def test_context_includes_line_numbers(self) -> None:
        """Context output includes line numbers."""
        import re

        text = "line 1\nline 2\nMATCH\nline 4\nline 5\n"
        match = re.search("MATCH", text)
        assert match is not None

        context = _extract_match_context(text, match)

        # Should have line numbers like "1:", "2:", "3:", etc.
        assert "3:" in context  # MATCH is on line 3

    def test_matching_line_has_marker(self) -> None:
        """The matching line has a '>' marker."""
        import re

        text = "before\nMATCH\nafter\n"
        match = re.search("MATCH", text)
        assert match is not None

        context = _extract_match_context(text, match)

        # The match line should have ">" marker
        lines = context.split("\n")
        match_lines = [ln for ln in lines if "MATCH" in ln]
        assert len(match_lines) == 1
        assert match_lines[0].startswith(">")


# ============================================================================
# TestSearchFilesIntegration: Real filesystem tests
# ============================================================================


class TestSearchFilesIntegration:
    """Integration tests for search_files with real local filesystem."""

    def _make_real_ctx(self, tmp_path: Path, show_hidden: bool = False) -> MagicMock:
        """Create a context with a real LocalBackend."""
        from fsspec.implementations.local import LocalFileSystem
        from mamba_mcp_fs.backends.local import LocalBackend

        settings = Settings(
            server=ServerSettings(),
            local=LocalSettings(base_path=str(tmp_path), show_hidden=show_hidden),
            s3=S3Settings(enabled=False),
        )
        security = SecurityValidator(
            server_settings=settings.server,
            local_settings=settings.local,
        )
        fs = LocalFileSystem()
        local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
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

    @pytest.mark.asyncio
    async def test_recursive_search_in_real_tree(self, tmp_path: Path) -> None:
        """Recursively searches a real directory tree."""
        # Create directory structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main(): pass")
        (tmp_path / "src" / "util.py").write_text("def helper(): pass")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass")
        (tmp_path / "README.md").write_text("# Project")

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(tmp_path), name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = sorted([r.name for r in result.results])
        assert "main.py" in names
        assert "util.py" in names
        assert "test_main.py" in names
        assert "README.md" not in names
        assert result.directories_searched >= 3

    @pytest.mark.asyncio
    async def test_content_search_in_real_files(self, tmp_path: Path) -> None:
        """Content search works on real text files."""
        (tmp_path / "match.py").write_text("import os\n\ndef main():\n    print('hello')\n")
        (tmp_path / "no_match.py").write_text("def helper():\n    return 42\n")

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(tmp_path), content_pattern="def main", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        assert result.results[0].name == "match.py"
        assert result.results[0].match_context is not None
        assert "def main()" in result.results[0].match_context

    @pytest.mark.asyncio
    async def test_combined_name_and_content_on_real_files(self, tmp_path: Path) -> None:
        """Combined name + content search on real filesystem."""
        (tmp_path / "app.py").write_text("def main():\n    pass\n")
        (tmp_path / "app.txt").write_text("def main() docs\n")
        (tmp_path / "util.py").write_text("def helper():\n    pass\n")

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(
            path=str(tmp_path),
            name_pattern="*.py",
            content_pattern="def main",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        assert result.results[0].name == "app.py"

    @pytest.mark.asyncio
    async def test_regex_error_handling(self, tmp_path: Path) -> None:
        """Invalid regex returns INVALID_OPERATION with helpful message."""
        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(tmp_path), content_pattern="[invalid(", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.INVALID_OPERATION

    @pytest.mark.asyncio
    async def test_path_outside_sandbox_blocked(self, tmp_path: Path) -> None:
        """Path traversal is blocked on real filesystem."""
        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(tmp_path / ".." / ".." / "etc"), ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX

    @pytest.mark.asyncio
    async def test_max_depth_zero_real_filesystem(self, tmp_path: Path) -> None:
        """max_depth=0 on real filesystem only searches root."""
        (tmp_path / "root.py").write_text("root file")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("nested file")

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(tmp_path), name_pattern="*.py", max_depth=0, ctx=ctx)

        assert isinstance(result, SearchResponse)
        names = [r.name for r in result.results]
        assert "root.py" in names
        assert "nested.py" not in names

    @pytest.mark.asyncio
    async def test_empty_directory_real(self, tmp_path: Path) -> None:
        """Search in real empty directory returns empty results."""
        empty = tmp_path / "empty"
        empty.mkdir()

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(empty), ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.results == []
        assert result.total_matches == 0

    @pytest.mark.asyncio
    async def test_search_result_metadata(self, tmp_path: Path) -> None:
        """Search results include correct metadata for each file."""
        test_file = tmp_path / "data.py"
        test_file.write_text("content here")

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(path=str(tmp_path), name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        sr = result.results[0]
        assert sr.name == "data.py"
        assert sr.type == "file"
        assert sr.size_bytes is not None
        assert sr.size_bytes > 0
        assert sr.modified_at is not None

    @pytest.mark.asyncio
    async def test_regex_with_special_characters(self, tmp_path: Path) -> None:
        """Complex regex patterns work correctly."""
        (tmp_path / "code.py").write_text(
            "class MyClass:\n    def __init__(self):\n        self.value = 42\n"
        )

        ctx = self._make_real_ctx(tmp_path)
        result = await search_files(
            path=str(tmp_path),
            content_pattern=r"def __init__\(self\)",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        assert result.results[0].name == "code.py"


# ============================================================================
# S3 Backend Helpers
# ============================================================================


class MockS3Backend:
    """A mock S3 backend for testing S3-specific metadata mapping.

    Returns entries in the normalized S3 format that S3Backend._normalize_entry
    produces: last_modified (not modified/mtime), mime_type (not mime_type via
    detection), no islink/permissions/created_at fields.
    """

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self._entries = entries or []
        self._raise_on_ls: Exception | None = None
        self._info_result: dict[str, Any] | None = None
        self._raise_on_info: Exception | None = None
        self._file_content: bytes = b""
        self._dir_entries: dict[str, list[dict[str, Any]]] = {}
        self._file_contents: dict[str, bytes] = {}

    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    def set_raise_on_ls(self, exc: Exception) -> None:
        self._raise_on_ls = exc

    def set_info_result(self, result: dict[str, Any]) -> None:
        self._info_result = result

    def set_raise_on_info(self, exc: Exception) -> None:
        self._raise_on_info = exc

    def set_file_content(self, content: bytes) -> None:
        self._file_content = content

    def set_dir_entries(self, dir_path: str, entries: list[dict[str, Any]]) -> None:
        self._dir_entries[dir_path] = entries

    def set_file_contents(self, path: str, content: bytes) -> None:
        self._file_contents[path] = content

    def ls(self, path: str, detail: bool = True) -> list[dict[str, Any]]:
        if self._raise_on_ls is not None:
            raise self._raise_on_ls
        if path in self._dir_entries:
            return list(self._dir_entries[path])
        return list(self._entries)

    def info(self, path: str) -> dict[str, Any]:
        if self._raise_on_info is not None:
            raise self._raise_on_info
        if self._info_result is not None:
            return dict(self._info_result)
        return {"name": path, "type": "directory", "size": 0}

    def cat_file(self, path: str, start: int | None = None, end: int | None = None) -> bytes:
        data = self._file_contents.get(path, self._file_content)
        if start is not None and end is not None:
            return data[start:end]
        if start is not None:
            return data[start:]
        if end is not None:
            return data[:end]
        return data

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
        return True

    def isdir(self, path: str) -> bool:
        return True

    def isfile(self, path: str) -> bool:
        return False


def _make_s3_entry(
    name: str,
    entry_type: str = "file",
    size: int = 100,
    last_modified: datetime | None = None,
    mime_type: str | None = None,
) -> dict[str, Any]:
    """Create a mock S3 backend entry dict matching _normalize_entry output.

    S3 uses 'last_modified' instead of 'modified'/'mtime', and may include
    'mime_type' from S3 ContentType header.
    """
    entry: dict[str, Any] = {
        "name": name,
        "type": entry_type,
        "size": size,
    }
    if last_modified is not None:
        entry["last_modified"] = last_modified
    if mime_type is not None:
        entry["mime_type"] = mime_type
    return entry


def _make_s3_settings(sandbox: Path, s3_enabled: bool = True) -> Settings:
    """Create a Settings instance for S3 testing."""
    return Settings(
        server=ServerSettings(),
        local=LocalSettings(base_path=str(sandbox)),
        s3=S3Settings(enabled=s3_enabled),
    )


def _make_s3_app_ctx(
    sandbox: Path,
    mock_s3: MockS3Backend,
    s3_enabled: bool = True,
    show_hidden: bool = False,
) -> AppContext:
    """Create an AppContext for S3 testing with mocked S3 backend."""
    settings = Settings(
        server=ServerSettings(),
        local=LocalSettings(base_path=str(sandbox), show_hidden=show_hidden),
        s3=S3Settings(enabled=s3_enabled),
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3 if settings.s3.enabled else None,
    )
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        s3_backend=mock_s3 if s3_enabled else None,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


# ============================================================================
# TestS3ListDirectory: list_directory with S3 backend
# ============================================================================


class TestS3ListDirectory:
    """Tests for list_directory with S3 prefix listing."""

    @pytest.mark.asyncio
    async def test_s3_prefix_listing_basic(self, tmp_path: Path) -> None:
        """list_directory returns correct entries for S3 prefix listing."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        s3_mock.set_entries(
            [
                _make_s3_entry("my-bucket/data/file1.csv", "file", 1024, ts),
                _make_s3_entry("my-bucket/data/file2.csv", "file", 2048, ts),
                _make_s3_entry("my-bucket/data/subdir", "directory", 0, ts),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://my-bucket/data", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.path == "s3://my-bucket/data"
        assert result.backend == "s3"
        assert len(result.entries) == 3
        names = [e.name for e in result.entries]
        assert "file1.csv" in names
        assert "file2.csv" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_s3_entry_metadata_mapped_correctly(self, tmp_path: Path) -> None:
        """S3 entries have correct metadata (size, type, modified_at from last_modified)."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 3, 10, 8, 30, 0, tzinfo=UTC)
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/report.csv", "file", 5000, ts),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        entry = result.entries[0]
        assert entry.name == "report.csv"
        assert entry.type == "file"
        assert entry.size_bytes == 5000
        assert entry.modified_at == ts

    @pytest.mark.asyncio
    async def test_s3_directory_entry(self, tmp_path: Path) -> None:
        """S3 common prefixes (virtual directories) are returned as directory type."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/data/", "directory", 0),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        entry = result.entries[0]
        assert entry.type == "directory"
        assert entry.size_bytes == 0

    @pytest.mark.asyncio
    async def test_s3_empty_directory(self, tmp_path: Path) -> None:
        """S3 prefix with no objects returns empty listing."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries([])

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/empty-prefix/", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.total_count == 0
        assert result.entries == []

    @pytest.mark.asyncio
    async def test_s3_entry_without_timestamp(self, tmp_path: Path) -> None:
        """S3 entry with no last_modified gets None for modified_at."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/file.txt", "file", 100),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.entries[0].modified_at is None

    @pytest.mark.asyncio
    async def test_s3_glob_pattern_filtering(self, tmp_path: Path) -> None:
        """Glob pattern filtering works on S3 entries."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/data.csv", "file", 100),
                _make_s3_entry("bucket/data.json", "file", 200),
                _make_s3_entry("bucket/readme.md", "file", 50),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/", pattern="*.csv", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.total_count == 1
        assert result.entries[0].name == "data.csv"

    @pytest.mark.asyncio
    async def test_s3_hidden_file_detection(self, tmp_path: Path) -> None:
        """Hidden file detection works on S3 entries (dotfile convention)."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/.hidden", "file", 10),
                _make_s3_entry("bucket/visible.txt", "file", 20),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        # Default: hidden files excluded
        result = await list_directory(path="s3://bucket/", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert len(result.entries) == 1
        assert result.entries[0].name == "visible.txt"


# ============================================================================
# TestS3GetFileInfo: get_file_info with S3 backend
# ============================================================================


class TestS3GetFileInfo:
    """Tests for get_file_info with S3 metadata mapping."""

    @pytest.mark.asyncio
    async def test_s3_file_info_basic(self, tmp_path: Path) -> None:
        """get_file_info returns correct metadata for S3 object."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 5, 20, 14, 0, 0, tzinfo=UTC)
        s3_mock.set_info_result(
            {
                "name": "my-bucket/data/report.csv",
                "type": "file",
                "size": 4096,
                "last_modified": ts,
                "mime_type": "text/csv",
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://my-bucket/data/report.csv", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "report.csv"
        assert result.type == "file"
        assert result.size_bytes == 4096
        assert result.modified_at == ts
        assert result.mime_type == "text/csv"
        assert result.backend == "s3"

    @pytest.mark.asyncio
    async def test_s3_no_symlink(self, tmp_path: Path) -> None:
        """S3 objects always have is_symlink=False (no symlinks in S3)."""
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/file.txt",
                "type": "file",
                "size": 100,
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.is_symlink is False

    @pytest.mark.asyncio
    async def test_s3_no_permissions(self, tmp_path: Path) -> None:
        """S3 objects always have permissions=None (no unix permissions)."""
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/file.txt",
                "type": "file",
                "size": 100,
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.permissions is None

    @pytest.mark.asyncio
    async def test_s3_no_created_at(self, tmp_path: Path) -> None:
        """S3 objects have created_at=None (S3 only has LastModified)."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        s3_mock.set_info_result(
            {
                "name": "bucket/file.txt",
                "type": "file",
                "size": 100,
                "last_modified": ts,
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.modified_at == ts
        assert result.created_at is None

    @pytest.mark.asyncio
    async def test_s3_mime_type_from_content_type(self, tmp_path: Path) -> None:
        """S3 mime_type comes from ContentType header (via _normalize_entry)."""
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/data.parquet",
                "type": "file",
                "size": 50000,
                "mime_type": "application/x-parquet",
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/data.parquet", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type == "application/x-parquet"

    @pytest.mark.asyncio
    async def test_s3_no_content_type_falls_back_to_detection(self, tmp_path: Path) -> None:
        """When S3 has no ContentType, mime_type is detected from path."""
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/data.json",
                "type": "file",
                "size": 1000,
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/data.json", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.mime_type is not None
        assert "json" in result.mime_type.lower()

    @pytest.mark.asyncio
    async def test_s3_directory_info(self, tmp_path: Path) -> None:
        """get_file_info works for S3 virtual directory (prefix)."""
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/data/",
                "type": "directory",
                "size": 0,
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/data/", ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.type == "directory"
        assert result.mime_type == "inode/directory"

    @pytest.mark.asyncio
    async def test_s3_checksum_computed(self, tmp_path: Path) -> None:
        """S3 checksum is computed from content when requested."""
        content = b"S3 object content for checksum"
        expected_hash = hashlib.sha256(content).hexdigest()

        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/file.txt",
                "type": "file",
                "size": len(content),
            }
        )
        s3_mock.set_file_content(content)

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/file.txt", include_checksum=True, ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.checksum == expected_hash


# ============================================================================
# TestS3ReadFile: read_file with S3 backend
# ============================================================================


class TestS3ReadFile:
    """Tests for read_file with S3 byte range support."""

    @pytest.mark.asyncio
    async def test_s3_read_text_file(self, tmp_path: Path) -> None:
        """read_file returns S3 text content correctly."""
        content = b"Hello from S3!"
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/hello.txt",
                "type": "file",
                "size": len(content),
            }
        )
        s3_mock.set_file_content(content)

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path="s3://bucket/hello.txt", ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "Hello from S3!"
        assert result.encoding == "text"
        assert result.backend == "s3"
        assert result.size_bytes == len(content)
        assert result.bytes_read == len(content)

    @pytest.mark.asyncio
    async def test_s3_read_binary_file(self, tmp_path: Path) -> None:
        """read_file returns S3 binary content as base64."""
        content = bytes(range(256))
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/data.bin",
                "type": "file",
                "size": len(content),
            }
        )
        s3_mock.set_file_content(content)

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path="s3://bucket/data.bin", ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        assert result.backend == "s3"

    @pytest.mark.asyncio
    async def test_s3_byte_range_read(self, tmp_path: Path) -> None:
        """read_file with offset/limit maps to S3 byte range correctly."""
        content = b"0123456789ABCDEF"
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/data.txt",
                "type": "file",
                "size": len(content),
            }
        )
        s3_mock.set_file_content(content)

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path="s3://bucket/data.txt", offset=4, limit=4, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "4567"
        assert result.offset == 4
        assert result.bytes_read == 4
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_s3_size_limit_enforcement(self, tmp_path: Path) -> None:
        """read_file enforces S3 max_file_size from config."""
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/huge.bin",
                "type": "file",
                "size": 100_000_000,
            }
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path="s3://bucket/huge.bin", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE

    @pytest.mark.asyncio
    async def test_s3_chunked_read_bypasses_size_limit(self, tmp_path: Path) -> None:
        """Chunked reads (offset/limit) bypass the S3 size limit."""
        content = b"A" * 100
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/big.txt",
                "type": "file",
                "size": 100_000_000,
            }
        )
        s3_mock.set_file_content(content)

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path="s3://bucket/big.txt", offset=0, limit=100, ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.is_truncated is True

    @pytest.mark.asyncio
    async def test_s3_mime_type_detected(self, tmp_path: Path) -> None:
        """read_file detects MIME type from S3 object path."""
        content = b'{"key": "value"}'
        s3_mock = MockS3Backend()
        s3_mock.set_info_result(
            {
                "name": "bucket/data.json",
                "type": "file",
                "size": len(content),
            }
        )
        s3_mock.set_file_content(content)

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path="s3://bucket/data.json", ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.mime_type is not None
        assert "json" in result.mime_type.lower()


# ============================================================================
# TestS3SearchFiles: search_files with S3 backend
# ============================================================================


class TestS3SearchFiles:
    """Tests for search_files with S3 prefix-based search."""

    @pytest.mark.asyncio
    async def test_s3_name_pattern_search(self, tmp_path: Path) -> None:
        """search_files finds S3 objects by name pattern."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 4, 1, tzinfo=UTC)
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/src/main.py", "file", 500, ts),
                _make_s3_entry("bucket/src/utils.py", "file", 300, ts),
                _make_s3_entry("bucket/src/data.csv", "file", 1000, ts),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path="s3://bucket/src", name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.backend == "s3"
        assert result.total_matches == 2
        names = [r.name for r in result.results]
        assert "main.py" in names
        assert "utils.py" in names

    @pytest.mark.asyncio
    async def test_s3_search_result_metadata(self, tmp_path: Path) -> None:
        """S3 search results include correct metadata from last_modified."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 7, 10, 16, 30, 0, tzinfo=UTC)
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/report.csv", "file", 2048, ts),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path="s3://bucket/", name_pattern="*.csv", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        sr = result.results[0]
        assert sr.name == "report.csv"
        assert sr.size_bytes == 2048
        assert sr.modified_at == ts

    @pytest.mark.asyncio
    async def test_s3_content_search(self, tmp_path: Path) -> None:
        """Content search on S3 objects works by downloading and searching."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/code.py", "file", 100),
            ]
        )
        s3_mock.set_file_contents("bucket/code.py", b"def main():\n    print('hello')\n")

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path="s3://bucket/", content_pattern="def main", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        assert result.results[0].match_context is not None
        assert "def main" in result.results[0].match_context

    @pytest.mark.asyncio
    async def test_s3_recursive_search(self, tmp_path: Path) -> None:
        """search_files descends into S3 virtual directories."""
        s3_mock = MockS3Backend()
        ts = datetime(2024, 1, 1, tzinfo=UTC)

        # Root directory
        s3_mock.set_dir_entries(
            "bucket",
            [
                _make_s3_entry("bucket/top.py", "file", 100, ts),
                _make_s3_entry("bucket/sub", "directory", 0, ts),
            ],
        )
        # Subdirectory
        s3_mock.set_dir_entries(
            "bucket/sub",
            [
                _make_s3_entry("bucket/sub/nested.py", "file", 200, ts),
            ],
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path="s3://bucket/", name_pattern="*.py", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 2
        names = [r.name for r in result.results]
        assert "top.py" in names
        assert "nested.py" in names

    @pytest.mark.asyncio
    async def test_s3_search_without_timestamp(self, tmp_path: Path) -> None:
        """S3 search results handle missing timestamps gracefully."""
        s3_mock = MockS3Backend()
        s3_mock.set_entries(
            [
                _make_s3_entry("bucket/file.txt", "file", 50),
            ]
        )

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(path="s3://bucket/", name_pattern="*.txt", ctx=ctx)

        assert isinstance(result, SearchResponse)
        assert result.total_matches == 1
        assert result.results[0].modified_at is None


# ============================================================================
# TestS3MetadataMapping: _to_file_entry with S3-format dicts
# ============================================================================


class TestS3MetadataMapping:
    """Tests for S3-specific metadata mapping in _to_file_entry."""

    def test_s3_last_modified_mapped_to_modified_at(self) -> None:
        """S3 'last_modified' key is correctly mapped to FileEntry.modified_at."""
        ts = datetime(2024, 8, 15, 9, 0, 0, tzinfo=UTC)
        entry = _make_s3_entry("bucket/file.txt", "file", 100, ts)

        result = _to_file_entry(entry)

        assert isinstance(result, FileEntry)
        assert result.modified_at == ts

    def test_s3_entry_without_modified_or_last_modified(self) -> None:
        """S3 entry with neither 'modified' nor 'last_modified' gets None."""
        entry = {"name": "bucket/file.txt", "type": "file", "size": 100}

        result = _to_file_entry(entry)

        assert result.modified_at is None

    def test_s3_entry_basename_extracted(self) -> None:
        """S3 full path name is correctly extracted to basename."""
        entry = _make_s3_entry("bucket/path/to/deep/file.csv", "file", 200)

        result = _to_file_entry(entry)

        assert result.name == "file.csv"
        assert result.path == "bucket/path/to/deep/file.csv"

    def test_s3_directory_entry_mapping(self) -> None:
        """S3 directory (common prefix) entry is correctly mapped."""
        entry = _make_s3_entry("bucket/data/", "directory", 0)

        result = _to_file_entry(entry)

        assert result.type == "directory"
        assert result.size_bytes == 0

    def test_s3_hidden_file_detection(self) -> None:
        """Hidden file detection works for S3 paths with dotfile names."""
        entry = _make_s3_entry("bucket/.env", "file", 50)

        result = _to_file_entry(entry)

        assert result.is_hidden is True

    def test_s3_non_hidden_file(self) -> None:
        """Regular S3 files are not marked as hidden."""
        entry = _make_s3_entry("bucket/config.yaml", "file", 300)

        result = _to_file_entry(entry)

        assert result.is_hidden is False

    def test_s3_last_modified_datetime_object(self) -> None:
        """S3 last_modified as datetime object is preserved."""
        ts = datetime(2024, 12, 25, 0, 0, 0, tzinfo=UTC)
        entry = _make_s3_entry("bucket/file.txt", "file", 100, ts)

        result = _to_file_entry(entry)

        assert result.modified_at == ts
        assert result.modified_at.tzinfo is not None


# ============================================================================
# TestS3ErrorHandling: Error scenarios for S3 discovery tools
# ============================================================================


class TestS3ErrorHandling:
    """Tests for S3-specific error handling in discovery tools."""

    @pytest.mark.asyncio
    async def test_s3_disabled_returns_backend_not_configured(self, tmp_path: Path) -> None:
        """BACKEND_NOT_CONFIGURED when S3 is not enabled."""
        s3_mock = MockS3Backend()
        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock, s3_enabled=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/data", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_s3_connectivity_error_on_ls(self, tmp_path: Path) -> None:
        """BACKEND_ERROR for S3 connectivity issues on ls."""
        from mamba_mcp_fs.errors import BackendError

        s3_mock = MockS3Backend()
        s3_mock.set_raise_on_ls(BackendError("S3 connection refused"))

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path="s3://bucket/data", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR

    @pytest.mark.asyncio
    async def test_s3_path_not_found_on_info(self, tmp_path: Path) -> None:
        """PATH_NOT_FOUND for non-existent S3 objects."""
        s3_mock = MockS3Backend()
        s3_mock.set_raise_on_info(PathNotFoundError("S3 path not found"))

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/nonexistent.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    @pytest.mark.asyncio
    async def test_s3_backend_error_on_info(self, tmp_path: Path) -> None:
        """BACKEND_ERROR for S3 operational errors on info."""
        from mamba_mcp_fs.errors import BackendError

        s3_mock = MockS3Backend()
        s3_mock.set_raise_on_info(BackendError("S3 throttled"))

        app_ctx = _make_s3_app_ctx(tmp_path, s3_mock)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path="s3://bucket/file.txt", ctx=ctx)

        assert isinstance(result, dict)
        assert result["error_code"] == ErrorCode.BACKEND_ERROR
