"""Phase 2 integration tests: discovery tools against a real local filesystem.

Exercises list_directory, get_file_info, read_file, and search_files
against a real temp directory tree created via pytest's tmp_path fixture.

Covers:
- Local backend operations with real files (metadata accuracy, MIME, permissions)
- Glob pattern filtering, nested search, content search
- Hidden file filtering with real dotfiles
- Symlink handling with real symlinks
- Edge cases: empty dirs, special characters, long paths
- End-to-end tool invocations with real LocalBackend
- Response model serialization verification
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fsspec.implementations.local import LocalFileSystem
from mamba_mcp_fs.backends.base import BackendManager
from mamba_mcp_fs.backends.local import LocalBackend
from mamba_mcp_fs.config import LocalSettings, S3Settings, ServerSettings, Settings
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
    get_file_info,
    list_directory,
    read_file,
    search_files,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_settings(
    sandbox: Path,
    show_hidden: bool = False,
    follow_symlinks: bool = False,
    max_file_size: int = 10_485_760,
) -> Settings:
    """Create a Settings instance with local backend pointing at sandbox."""
    return Settings(
        server=ServerSettings(),
        local=LocalSettings(
            base_path=str(sandbox),
            show_hidden=show_hidden,
            follow_symlinks=follow_symlinks,
            max_file_size=max_file_size,
        ),
        s3=S3Settings(enabled=False),
    )


def _make_real_app_ctx(
    sandbox: Path,
    show_hidden: bool = False,
    follow_symlinks: bool = False,
    max_file_size: int = 10_485_760,
) -> AppContext:
    """Create an AppContext with a real LocalBackend for integration tests."""
    settings = _make_settings(
        sandbox,
        show_hidden=show_hidden,
        follow_symlinks=follow_symlinks,
        max_file_size=max_file_size,
    )
    security = SecurityValidator(
        server_settings=settings.server,
        local_settings=settings.local,
        s3_settings=settings.s3,
    )
    fs = LocalFileSystem()
    local_backend = LocalBackend(fs=fs, security=security, settings=settings.local)
    backend_manager = BackendManager(
        settings=settings,
        security=security,
        local_backend=local_backend,
    )
    return AppContext(
        settings=settings,
        security=security,
        backend_manager=backend_manager,
        rate_limiter=RateLimiter(ops_per_minute=0),
    )


def _make_mock_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock MCP Context that provides AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def temp_sandbox(tmp_path: Path) -> Path:
    """Real temp directory with test files for integration tests.

    Creates:
        sandbox/
          file.txt         (text content)
          data.json        (JSON content)
          image.png        (binary content)
          .hidden_file     (dotfile)
          subdir/
            nested.py      (Python file)
            deep/
              deep_file.md (Markdown file)
          empty_dir/
    """
    # Text file
    (tmp_path / "file.txt").write_text("Hello, world!")

    # JSON file
    (tmp_path / "data.json").write_text('{"key": "value", "count": 42}')

    # Binary file (minimal PNG header bytes)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"  # PNG signature
        b"\x00\x00\x00\rIHDR"  # IHDR chunk
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"  # 1x1 RGB
        b"\x00\x00\x00\x90wS\xde"
    )
    (tmp_path / "image.png").write_bytes(png_bytes)

    # Hidden file (dotfile)
    (tmp_path / ".hidden_file").write_text("secret data")

    # Nested directory structure
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "nested.py").write_text('def hello():\n    print("hello")\n')

    deep = subdir / "deep"
    deep.mkdir()
    (deep / "deep_file.md").write_text("# Deep File\n\nNested markdown content.\n")

    # Empty directory
    (tmp_path / "empty_dir").mkdir()

    return tmp_path


# ============================================================================
# TestListDirectoryLocal: Real directory listing
# ============================================================================


class TestListDirectoryLocal:
    """Integration tests for list_directory against real filesystem."""

    @pytest.mark.asyncio
    async def test_list_real_files(self, temp_sandbox: Path) -> None:
        """Lists real files and verifies entry metadata accuracy."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.backend == "local"
        names = {e.name for e in result.entries}
        # Hidden file excluded by default; visible files + dirs included
        assert "file.txt" in names
        assert "data.json" in names
        assert "image.png" in names
        assert "subdir" in names
        assert "empty_dir" in names
        # Hidden file excluded
        assert ".hidden_file" not in names

    @pytest.mark.asyncio
    async def test_list_with_glob_pattern(self, temp_sandbox: Path) -> None:
        """Glob pattern filters real files correctly."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), pattern="*.json", ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert names == {"data.json"}

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, temp_sandbox: Path) -> None:
        """Empty directory returns zero entries."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox / "empty_dir"), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.entries == []
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_list_metadata_accuracy(self, temp_sandbox: Path) -> None:
        """File entry metadata (size, type, modified_at) is accurate."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)

        # Check text file metadata
        file_entry = next(e for e in result.entries if e.name == "file.txt")
        assert file_entry.type == "file"
        assert file_entry.size_bytes == len("Hello, world!")
        assert file_entry.modified_at is not None

        # Check directory metadata
        dir_entry = next(e for e in result.entries if e.name == "subdir")
        assert dir_entry.type == "directory"


# ============================================================================
# TestGetFileInfoLocal: Real file info
# ============================================================================


class TestGetFileInfoLocal:
    """Integration tests for get_file_info against real filesystem."""

    @pytest.mark.asyncio
    async def test_text_file_info(self, temp_sandbox: Path) -> None:
        """Verifies MIME type, size, and permissions for a text file."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "file.txt"
        assert result.type == "file"
        assert result.backend == "local"
        assert result.size_bytes == len("Hello, world!")
        assert result.mime_type is not None
        assert "text" in result.mime_type
        assert result.permissions is not None
        # Permission string should be 10 chars like "-rw-r--r--"
        assert len(result.permissions) == 10
        assert result.is_symlink is False

    @pytest.mark.asyncio
    async def test_binary_file_info(self, temp_sandbox: Path) -> None:
        """Verifies info for a binary (PNG) file."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / "image.png"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "image.png"
        assert result.type == "file"
        assert result.size_bytes is not None
        assert result.size_bytes > 0
        assert result.mime_type is not None
        assert "png" in result.mime_type.lower() or "image" in result.mime_type.lower()

    @pytest.mark.asyncio
    async def test_directory_info(self, temp_sandbox: Path) -> None:
        """Verifies info for a directory."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / "subdir"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "subdir"
        assert result.type == "directory"
        assert result.mime_type == "inode/directory"

    @pytest.mark.asyncio
    async def test_json_file_info(self, temp_sandbox: Path) -> None:
        """Verifies info for a JSON file has appropriate MIME type."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / "data.json"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "data.json"
        assert result.mime_type is not None
        assert "json" in result.mime_type

    @pytest.mark.asyncio
    async def test_file_info_with_checksum(self, temp_sandbox: Path) -> None:
        """Checksum is computed correctly for a real file."""
        import hashlib

        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(
            path=str(temp_sandbox / "file.txt"),
            include_checksum=True,
            ctx=ctx,
        )

        assert isinstance(result, FileInfoResponse)
        assert result.checksum is not None
        expected = hashlib.sha256(b"Hello, world!").hexdigest()
        assert result.checksum == expected

    @pytest.mark.asyncio
    async def test_file_info_modified_at(self, temp_sandbox: Path) -> None:
        """Modified timestamp is populated for a real file."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.modified_at is not None


# ============================================================================
# TestReadFileLocal: Real file reading
# ============================================================================


class TestReadFileLocal:
    """Integration tests for read_file against real filesystem."""

    @pytest.mark.asyncio
    async def test_read_text_file(self, temp_sandbox: Path) -> None:
        """Reads a text file and verifies content and encoding."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(temp_sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.content == "Hello, world!"
        assert result.size_bytes == len("Hello, world!")
        assert result.bytes_read == len("Hello, world!")
        assert result.has_more is False
        assert result.is_truncated is False

    @pytest.mark.asyncio
    async def test_read_binary_file(self, temp_sandbox: Path) -> None:
        """Reads a binary file and verifies base64 encoding."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(temp_sandbox / "image.png"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "base64"
        # Verify base64 decodes back to original bytes
        original_bytes = (temp_sandbox / "image.png").read_bytes()
        decoded = base64.b64decode(result.content)
        assert decoded == original_bytes

    @pytest.mark.asyncio
    async def test_read_json_file(self, temp_sandbox: Path) -> None:
        """Reads a JSON file as text."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(temp_sandbox / "data.json"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert '"key"' in result.content
        assert '"value"' in result.content

    @pytest.mark.asyncio
    async def test_chunked_read(self, temp_sandbox: Path) -> None:
        """Reads a portion of a file using offset and limit."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(
            path=str(temp_sandbox / "file.txt"),
            offset=0,
            limit=5,
            ctx=ctx,
        )

        assert isinstance(result, ReadFileResponse)
        assert result.bytes_read == 5
        assert result.has_more is True
        assert result.offset == 0

    @pytest.mark.asyncio
    async def test_chunked_read_with_offset(self, temp_sandbox: Path) -> None:
        """Reads from a specific offset in the file."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        # "Hello, world!" -- offset 7 should give "world!"
        result = await read_file(
            path=str(temp_sandbox / "file.txt"),
            offset=7,
            limit=6,
            ctx=ctx,
        )

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert result.content == "world!"
        assert result.offset == 7

    @pytest.mark.asyncio
    async def test_read_python_file(self, temp_sandbox: Path) -> None:
        """Reads a Python file in a subdirectory."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(temp_sandbox / "subdir" / "nested.py"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.encoding == "text"
        assert "def hello():" in result.content


# ============================================================================
# TestSearchFilesLocal: Real recursive search
# ============================================================================


class TestSearchFilesLocal:
    """Integration tests for search_files against real filesystem."""

    @pytest.mark.asyncio
    async def test_search_by_name_pattern(self, temp_sandbox: Path) -> None:
        """Finds files matching a name pattern in nested directories."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            name_pattern="*.py",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        assert result.total_matches >= 1
        names = {r.name for r in result.results}
        assert "nested.py" in names

    @pytest.mark.asyncio
    async def test_search_by_content_pattern(self, temp_sandbox: Path) -> None:
        """Finds files containing a regex pattern."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            content_pattern="def hello",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        assert result.total_matches >= 1
        names = {r.name for r in result.results}
        assert "nested.py" in names
        # The match should have context
        match_result = next(r for r in result.results if r.name == "nested.py")
        assert match_result.match_context is not None
        assert "def hello" in match_result.match_context

    @pytest.mark.asyncio
    async def test_search_content_in_deep_nested(self, temp_sandbox: Path) -> None:
        """Finds content matches in deeply nested files."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            content_pattern="Nested markdown",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        assert result.total_matches >= 1
        names = {r.name for r in result.results}
        assert "deep_file.md" in names

    @pytest.mark.asyncio
    async def test_search_with_max_depth(self, temp_sandbox: Path) -> None:
        """max_depth limits search to specified depth."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        # depth=0 searches only the root directory (no recursion into subdirs)
        result = await search_files(
            path=str(temp_sandbox),
            name_pattern="*.py",
            max_depth=0,
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        # nested.py is in subdir/ so depth=0 should not find it
        names = {r.name for r in result.results}
        assert "nested.py" not in names

    @pytest.mark.asyncio
    async def test_search_finds_multiple_extensions(self, temp_sandbox: Path) -> None:
        """Name pattern search across different file types."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            name_pattern="*.md",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        names = {r.name for r in result.results}
        assert "deep_file.md" in names


# ============================================================================
# TestHiddenFileFiltering: Real dotfiles
# ============================================================================


class TestHiddenFileFiltering:
    """Integration tests for hidden file handling with real dotfiles."""

    @pytest.mark.asyncio
    async def test_hidden_excluded_by_default(self, temp_sandbox: Path) -> None:
        """Hidden files are excluded by default in list_directory."""
        app_ctx = _make_real_app_ctx(temp_sandbox, show_hidden=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert ".hidden_file" not in names

    @pytest.mark.asyncio
    async def test_hidden_included_with_config(self, temp_sandbox: Path) -> None:
        """Hidden files are included when show_hidden=True in config."""
        app_ctx = _make_real_app_ctx(temp_sandbox, show_hidden=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert ".hidden_file" in names

    @pytest.mark.asyncio
    async def test_hidden_file_info(self, temp_sandbox: Path) -> None:
        """get_file_info correctly identifies hidden file."""
        app_ctx = _make_real_app_ctx(temp_sandbox, show_hidden=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / ".hidden_file"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.is_hidden is True
        assert result.name == ".hidden_file"

    @pytest.mark.asyncio
    async def test_hidden_excluded_from_search(self, temp_sandbox: Path) -> None:
        """Hidden files are excluded from search results by default."""
        app_ctx = _make_real_app_ctx(temp_sandbox, show_hidden=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            content_pattern="secret data",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        names = {r.name for r in result.results}
        assert ".hidden_file" not in names

    @pytest.mark.asyncio
    async def test_hidden_included_in_search_when_enabled(self, temp_sandbox: Path) -> None:
        """Hidden files appear in search results with include_hidden=True.

        Uses name pattern search instead of content search because
        .hidden_file has no extension and MIME detection returns
        application/octet-stream (not text), so content search skips it.
        """
        app_ctx = _make_real_app_ctx(temp_sandbox, show_hidden=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            name_pattern=".hidden_file",
            include_hidden=True,
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        names = {r.name for r in result.results}
        assert ".hidden_file" in names


# ============================================================================
# TestSymlinkHandling: Real symlinks
# ============================================================================

# Skip symlink tests on platforms without symlink support
_symlink_supported = hasattr(os, "symlink")


@pytest.mark.skipif(not _symlink_supported, reason="Symlinks not supported on this platform")
class TestSymlinkHandling:
    """Integration tests for symlink handling with real symlinks."""

    @pytest.mark.asyncio
    async def test_symlink_detection_in_info(self, temp_sandbox: Path) -> None:
        """get_file_info detects a symlink correctly."""
        link = temp_sandbox / "link_to_file.txt"
        link.symlink_to(temp_sandbox / "file.txt")

        app_ctx = _make_real_app_ctx(temp_sandbox, follow_symlinks=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(link), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.is_symlink is True
        assert result.name == "link_to_file.txt"

    @pytest.mark.asyncio
    async def test_symlink_in_listing_when_following(self, temp_sandbox: Path) -> None:
        """Symlinks appear in list_directory when follow_symlinks=True."""
        link = temp_sandbox / "link_to_file.txt"
        link.symlink_to(temp_sandbox / "file.txt")

        app_ctx = _make_real_app_ctx(temp_sandbox, follow_symlinks=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert "link_to_file.txt" in names

    @pytest.mark.asyncio
    async def test_symlink_excluded_when_not_following(self, temp_sandbox: Path) -> None:
        """Symlinks are excluded from list_directory when follow_symlinks=False."""
        link = temp_sandbox / "link_to_file.txt"
        link.symlink_to(temp_sandbox / "file.txt")

        app_ctx = _make_real_app_ctx(temp_sandbox, follow_symlinks=False)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert "link_to_file.txt" not in names

    @pytest.mark.asyncio
    async def test_read_through_symlink(self, temp_sandbox: Path) -> None:
        """read_file through a symlink returns the target file content."""
        link = temp_sandbox / "link_to_file.txt"
        link.symlink_to(temp_sandbox / "file.txt")

        app_ctx = _make_real_app_ctx(temp_sandbox, follow_symlinks=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(link), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "Hello, world!"

    @pytest.mark.asyncio
    async def test_symlink_to_directory(self, temp_sandbox: Path) -> None:
        """Symlink to a directory works with list_directory."""
        dir_link = temp_sandbox / "link_to_subdir"
        dir_link.symlink_to(temp_sandbox / "subdir")

        app_ctx = _make_real_app_ctx(temp_sandbox, follow_symlinks=True)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(dir_link), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        names = {e.name for e in result.entries}
        assert "nested.py" in names


# ============================================================================
# TestEdgeCases: Special characters, empty dirs, long paths
# ============================================================================


class TestEdgeCases:
    """Edge case tests with real filesystem."""

    @pytest.mark.asyncio
    async def test_empty_directory_handling(self, temp_sandbox: Path) -> None:
        """Empty directory returns empty entries and zero count."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox / "empty_dir"), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        assert result.entries == []
        assert result.total_count == 0
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_file_with_spaces_in_name(self, temp_sandbox: Path) -> None:
        """Files with spaces in names are handled correctly."""
        spaced_file = temp_sandbox / "file with spaces.txt"
        spaced_file.write_text("content with spaces")

        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(spaced_file), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.name == "file with spaces.txt"
        assert result.size_bytes == len("content with spaces")

    @pytest.mark.asyncio
    async def test_file_with_special_characters(self, temp_sandbox: Path) -> None:
        """Files with special characters (parens, hyphens, underscores)."""
        special_file = temp_sandbox / "report-v2_final (1).txt"
        special_file.write_text("special content")

        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(special_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "special content"
        assert result.encoding == "text"

    @pytest.mark.asyncio
    async def test_file_with_unicode_name(self, temp_sandbox: Path) -> None:
        """Files with unicode characters in names."""
        unicode_file = temp_sandbox / "caf\u00e9.txt"
        unicode_file.write_text("unicode content")

        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(unicode_file), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        assert result.size_bytes == len("unicode content")

    @pytest.mark.asyncio
    async def test_very_long_file_path(self, temp_sandbox: Path) -> None:
        """Very long (but valid) file paths are handled."""
        # Create a moderately nested directory structure
        current = temp_sandbox
        for i in range(10):
            current = current / f"level_{i}"
            current.mkdir()
        deep_file = current / "deep.txt"
        deep_file.write_text("deep content")

        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(deep_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.content == "deep content"

    @pytest.mark.asyncio
    async def test_empty_file_read(self, temp_sandbox: Path) -> None:
        """Reading an empty file returns empty content."""
        empty_file = temp_sandbox / "empty.txt"
        empty_file.write_bytes(b"")

        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(empty_file), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        assert result.bytes_read == 0
        assert result.size_bytes == 0


# ============================================================================
# TestEndToEndToolInvocations: Tool function -> response model
# ============================================================================


class TestEndToEndToolInvocations:
    """End-to-end tests invoking tool functions directly with real backend."""

    @pytest.mark.asyncio
    async def test_list_directory_response_serialization(self, temp_sandbox: Path) -> None:
        """list_directory response serializes to dict/JSON correctly."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await list_directory(path=str(temp_sandbox), ctx=ctx)

        assert isinstance(result, ListDirectoryResponse)
        # Verify JSON serialization round-trip
        json_dict = result.model_dump()
        assert "path" in json_dict
        assert "entries" in json_dict
        assert "total_count" in json_dict
        assert "has_more" in json_dict
        assert isinstance(json_dict["entries"], list)
        for entry in json_dict["entries"]:
            assert "name" in entry
            assert "type" in entry

    @pytest.mark.asyncio
    async def test_get_file_info_response_serialization(self, temp_sandbox: Path) -> None:
        """get_file_info response serializes to dict/JSON correctly."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await get_file_info(path=str(temp_sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, FileInfoResponse)
        json_dict = result.model_dump()
        assert json_dict["name"] == "file.txt"
        assert json_dict["type"] == "file"
        assert "size_bytes" in json_dict
        assert "mime_type" in json_dict
        assert "size_pretty" in json_dict
        assert "permissions" in json_dict
        assert "is_symlink" in json_dict
        assert "is_hidden" in json_dict

    @pytest.mark.asyncio
    async def test_read_file_response_serialization(self, temp_sandbox: Path) -> None:
        """read_file response serializes to dict/JSON correctly."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await read_file(path=str(temp_sandbox / "file.txt"), ctx=ctx)

        assert isinstance(result, ReadFileResponse)
        json_dict = result.model_dump()
        assert json_dict["encoding"] == "text"
        assert json_dict["content"] == "Hello, world!"
        assert "size_bytes" in json_dict
        assert "bytes_read" in json_dict
        assert "has_more" in json_dict
        assert "is_truncated" in json_dict

    @pytest.mark.asyncio
    async def test_search_files_response_serialization(self, temp_sandbox: Path) -> None:
        """search_files response serializes to dict/JSON correctly."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        result = await search_files(
            path=str(temp_sandbox),
            name_pattern="*.txt",
            ctx=ctx,
        )

        assert isinstance(result, SearchResponse)
        json_dict = result.model_dump()
        assert "results" in json_dict
        assert "total_matches" in json_dict
        assert "search_truncated" in json_dict
        assert "directories_searched" in json_dict
        assert isinstance(json_dict["results"], list)

    @pytest.mark.asyncio
    async def test_full_workflow_list_then_read(self, temp_sandbox: Path) -> None:
        """End-to-end: list directory then read discovered file."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        # Step 1: List directory
        list_result = await list_directory(path=str(temp_sandbox), ctx=ctx)
        assert isinstance(list_result, ListDirectoryResponse)

        # Step 2: Find the text file entry
        txt_entry = next((e for e in list_result.entries if e.name == "file.txt"), None)
        assert txt_entry is not None
        assert txt_entry.type == "file"

        # Step 3: Read the file using its path
        read_result = await read_file(path=txt_entry.path, ctx=ctx)
        assert isinstance(read_result, ReadFileResponse)
        assert read_result.content == "Hello, world!"

    @pytest.mark.asyncio
    async def test_full_workflow_search_then_info(self, temp_sandbox: Path) -> None:
        """End-to-end: search files then get info on a match."""
        app_ctx = _make_real_app_ctx(temp_sandbox)
        ctx = _make_mock_ctx(app_ctx)

        # Step 1: Search for Python files
        search_result = await search_files(
            path=str(temp_sandbox),
            name_pattern="*.py",
            ctx=ctx,
        )
        assert isinstance(search_result, SearchResponse)
        assert search_result.total_matches >= 1

        # Step 2: Get info on the first match
        match = search_result.results[0]
        info_result = await get_file_info(path=match.path, ctx=ctx)
        assert isinstance(info_result, FileInfoResponse)
        assert info_result.type == "file"
        assert info_result.mime_type is not None
