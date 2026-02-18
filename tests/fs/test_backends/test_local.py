"""Tests for the local filesystem backend.

Covers:
- Unit: Each method with mocked fsspec filesystem
- Integration: Real filesystem operations with tmp_path fixture
- Integration: Hidden file filtering with real dotfiles
- Integration: Symlink handling on real filesystem
- Error handling: FileNotFoundError, PermissionError, OSError mapping
- Edge cases: Empty directories, special characters, large listings
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fsspec.implementations.local import LocalFileSystem
from mamba_mcp_fs.backends.base import BackendProtocol
from mamba_mcp_fs.backends.local import LocalBackend
from mamba_mcp_fs.config import LocalSettings, ServerSettings
from mamba_mcp_fs.errors import (
    BackendError,
    FileTooLargeError,
    InvalidOperationError,
    PathNotFoundError,
    PermissionDeniedError,
)
from mamba_mcp_fs.security import SecurityValidator

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Create a sandbox directory with test files."""
    (tmp_path / "file.txt").write_text("hello world")
    (tmp_path / "data.json").write_text('{"key": "value"}')
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested content")
    return tmp_path


@pytest.fixture()
def server_settings() -> ServerSettings:
    """Default server settings."""
    return ServerSettings()


@pytest.fixture()
def local_settings(sandbox: Path) -> LocalSettings:
    """Local settings pointing at the sandbox."""
    return LocalSettings(base_path=str(sandbox))


@pytest.fixture()
def local_settings_show_hidden(sandbox: Path) -> LocalSettings:
    """Local settings with show_hidden=True."""
    return LocalSettings(base_path=str(sandbox), show_hidden=True)


@pytest.fixture()
def local_settings_follow_symlinks(sandbox: Path) -> LocalSettings:
    """Local settings with follow_symlinks=True."""
    return LocalSettings(base_path=str(sandbox), follow_symlinks=True)


@pytest.fixture()
def security(server_settings: ServerSettings, local_settings: LocalSettings) -> SecurityValidator:
    """Security validator for standard settings."""
    return SecurityValidator(server_settings, local_settings)


@pytest.fixture()
def fs() -> LocalFileSystem:
    """A real fsspec LocalFileSystem instance."""
    return LocalFileSystem()


@pytest.fixture()
def backend(
    fs: LocalFileSystem,
    security: SecurityValidator,
    local_settings: LocalSettings,
) -> LocalBackend:
    """A LocalBackend instance with real filesystem."""
    return LocalBackend(fs=fs, security=security, settings=local_settings)


def _make_backend(
    sandbox: Path,
    show_hidden: bool = False,
    follow_symlinks: bool = False,
    max_file_size: int = 10_485_760,
    allowed_extensions: str | None = None,
    denied_extensions: str | None = None,
) -> LocalBackend:
    """Helper to create a LocalBackend with custom settings."""
    server = ServerSettings(
        allowed_extensions=allowed_extensions,
        denied_extensions=denied_extensions,
    )
    local = LocalSettings(
        base_path=str(sandbox),
        show_hidden=show_hidden,
        follow_symlinks=follow_symlinks,
        max_file_size=max_file_size,
    )
    sec = SecurityValidator(server, local)
    fs = LocalFileSystem()
    return LocalBackend(fs=fs, security=sec, settings=local)


# ============================================================================
# TestProtocolCompliance
# ============================================================================


class TestProtocolCompliance:
    """LocalBackend satisfies BackendProtocol."""

    def test_satisfies_protocol(self, backend: LocalBackend) -> None:
        """LocalBackend should be recognized as a BackendProtocol instance."""
        assert isinstance(backend, BackendProtocol)

    def test_has_all_required_methods(self) -> None:
        """LocalBackend should have all BackendProtocol methods."""
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
        actual = {
            m
            for m in dir(LocalBackend)
            if not m.startswith("_") and callable(getattr(LocalBackend, m, None))
        }
        assert expected.issubset(actual)


# ============================================================================
# TestLs: Directory listing
# ============================================================================


class TestLs:
    """Tests for LocalBackend.ls method."""

    def test_ls_returns_entries(self, backend: LocalBackend, sandbox: Path) -> None:
        """ls should return a list of entry dicts."""
        entries = backend.ls(str(sandbox))
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_ls_entries_have_standard_keys(self, backend: LocalBackend, sandbox: Path) -> None:
        """Each entry from ls should have standardized keys."""
        entries = backend.ls(str(sandbox))
        for entry in entries:
            assert "name" in entry
            assert "type" in entry
            assert "size" in entry

    def test_ls_detail_false(self, backend: LocalBackend, sandbox: Path) -> None:
        """ls with detail=False should return name-only dicts."""
        entries = backend.ls(str(sandbox), detail=False)
        for entry in entries:
            assert "name" in entry
            assert len(entry) == 1

    def test_ls_includes_files_and_dirs(self, backend: LocalBackend, sandbox: Path) -> None:
        """ls should list both files and directories."""
        entries = backend.ls(str(sandbox))
        types = {e["type"] for e in entries}
        assert "file" in types
        assert "directory" in types

    def test_ls_relative_path(self, backend: LocalBackend, sandbox: Path) -> None:
        """ls should work with paths relative to the sandbox."""
        entries = backend.ls("subdir")
        assert len(entries) == 1
        assert entries[0]["type"] == "file"

    def test_ls_nonexistent_raises_path_not_found(self, backend: LocalBackend) -> None:
        """ls on a non-existent directory should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError, match="not found"):
            backend.ls("nonexistent_dir")

    def test_ls_empty_directory(self, backend: LocalBackend, sandbox: Path) -> None:
        """ls on an empty directory should return an empty list."""
        empty = sandbox / "empty_dir"
        empty.mkdir()
        entries = backend.ls(str(empty))
        assert entries == []

    def test_ls_standardizes_entry_format(self, backend: LocalBackend, sandbox: Path) -> None:
        """ls should standardize entry keys (modified instead of mtime)."""
        entries = backend.ls(str(sandbox))
        for entry in entries:
            assert "modified" in entry
            assert "islink" in entry


class TestLsWithMockedFs:
    """Unit tests for ls with mocked fsspec filesystem."""

    def test_ls_delegates_to_fsspec(self, sandbox: Path) -> None:
        """ls should call fsspec's ls method."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.ls.return_value = [
            {
                "name": str(sandbox / "a.txt"),
                "type": "file",
                "size": 10,
                "created": 0,
                "mtime": 0,
                "islink": False,
                "mode": 33188,
            },
        ]
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        entries = be.ls(str(sandbox))
        mock_fs.ls.assert_called_once_with(str(sandbox), detail=True)
        assert len(entries) == 1

    def test_ls_maps_file_not_found_to_path_not_found(self, sandbox: Path) -> None:
        """FileNotFoundError from fsspec should map to PathNotFoundError."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.ls.side_effect = FileNotFoundError("not found")
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        with pytest.raises(PathNotFoundError):
            be.ls(str(sandbox))

    def test_ls_maps_permission_error(self, sandbox: Path) -> None:
        """PermissionError from OS should map to PermissionDeniedError."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.ls.side_effect = PermissionError("denied")
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        with pytest.raises(PermissionDeniedError):
            be.ls(str(sandbox))

    def test_ls_maps_os_error_to_backend_error(self, sandbox: Path) -> None:
        """OSError from fsspec should map to BackendError."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.ls.side_effect = OSError("disk failure")
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        with pytest.raises(BackendError, match="Filesystem error"):
            be.ls(str(sandbox))


# ============================================================================
# TestInfo: File/directory metadata
# ============================================================================


class TestInfo:
    """Tests for LocalBackend.info method."""

    def test_info_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """info on a file should return metadata with MIME type."""
        result = backend.info(str(sandbox / "file.txt"))
        assert result["type"] == "file"
        assert result["size"] == 11  # "hello world"
        assert result["mime_type"] is not None
        assert result["permissions"] is not None
        assert "created_at" in result

    def test_info_directory(self, backend: LocalBackend, sandbox: Path) -> None:
        """info on a directory should return directory metadata."""
        result = backend.info(str(sandbox / "subdir"))
        assert result["type"] == "directory"
        assert result["mime_type"] == "inode/directory"

    def test_info_permissions_string(self, backend: LocalBackend, sandbox: Path) -> None:
        """info should include a human-readable permissions string."""
        result = backend.info(str(sandbox / "file.txt"))
        perms = result["permissions"]
        assert perms is not None
        # Should look like "-rw-r--r--" or similar
        assert perms.startswith("-")
        assert len(perms) == 10

    def test_info_mime_type_text_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """info on a .txt file should return a text MIME type."""
        result = backend.info(str(sandbox / "file.txt"))
        assert "text" in result["mime_type"]

    def test_info_mime_type_json_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """info on a .json file should return a JSON MIME type."""
        result = backend.info(str(sandbox / "data.json"))
        assert "json" in result["mime_type"]

    def test_info_created_at_present(self, backend: LocalBackend, sandbox: Path) -> None:
        """info should include a created_at timestamp."""
        result = backend.info(str(sandbox / "file.txt"))
        assert result["created_at"] is not None
        # ISO 8601 format check
        assert "T" in result["created_at"]

    def test_info_symlink_detection(self, sandbox: Path) -> None:
        """info should detect symlinks."""
        link = sandbox / "link.txt"
        link.symlink_to(sandbox / "file.txt")
        be = _make_backend(sandbox, follow_symlinks=True)
        result = be.info(str(link))
        assert result["islink"] is True

    def test_info_nonexistent_raises(self, backend: LocalBackend) -> None:
        """info on a non-existent path should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.info("nonexistent_file.txt")


class TestInfoWithMockedFs:
    """Unit tests for info with mocked fsspec filesystem."""

    def test_info_delegates_to_fsspec(self, sandbox: Path) -> None:
        """info should call fsspec's info method."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.info.return_value = {
            "name": str(sandbox / "a.txt"),
            "type": "file",
            "size": 10,
            "created": 0,
            "mtime": 0,
            "islink": False,
            "mode": 33188,
        }
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        result = be.info(str(sandbox / "a.txt"))
        mock_fs.info.assert_called_once_with(str(sandbox / "a.txt"))
        assert result["type"] == "file"

    def test_info_file_not_found_maps_to_path_not_found(self, sandbox: Path) -> None:
        """FileNotFoundError from fsspec info should map to PathNotFoundError."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.info.side_effect = FileNotFoundError("not found")
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        with pytest.raises(PathNotFoundError):
            be.info(str(sandbox / "missing.txt"))


# ============================================================================
# TestCatFile: File reading
# ============================================================================


class TestCatFile:
    """Tests for LocalBackend.cat_file method."""

    def test_cat_file_reads_content(self, backend: LocalBackend, sandbox: Path) -> None:
        """cat_file should return file content as bytes."""
        content = backend.cat_file(str(sandbox / "file.txt"))
        assert content == b"hello world"

    def test_cat_file_chunked_read(self, backend: LocalBackend, sandbox: Path) -> None:
        """cat_file with start/end should return a chunk."""
        content = backend.cat_file(str(sandbox / "file.txt"), start=0, end=5)
        assert content == b"hello"

    def test_cat_file_nonexistent_raises(self, backend: LocalBackend) -> None:
        """cat_file on a non-existent file should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.cat_file("nonexistent.txt")

    def test_cat_file_size_limit_enforced(self, sandbox: Path) -> None:
        """cat_file should enforce file size limit for full reads."""
        # Create a file larger than the limit
        big_file = sandbox / "big.txt"
        big_file.write_bytes(b"x" * 200)
        be = _make_backend(sandbox, max_file_size=100)

        with pytest.raises(FileTooLargeError):
            be.cat_file(str(big_file))

    def test_cat_file_chunked_bypasses_size_limit(self, sandbox: Path) -> None:
        """cat_file with start/end should bypass the size limit."""
        big_file = sandbox / "big.txt"
        big_file.write_bytes(b"x" * 200)
        be = _make_backend(sandbox, max_file_size=100)

        # Chunked read should work even though total file exceeds limit
        chunk = be.cat_file(str(big_file), start=0, end=50)
        assert len(chunk) == 50

    def test_cat_file_empty_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """cat_file on an empty file should return empty bytes."""
        empty = sandbox / "empty.txt"
        empty.write_bytes(b"")
        content = backend.cat_file(str(empty))
        assert content == b""


class TestCatFileWithMockedFs:
    """Unit tests for cat_file with mocked fsspec filesystem."""

    def test_cat_file_delegates_to_fsspec(self, sandbox: Path) -> None:
        """cat_file should call fsspec's cat_file method."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.info.return_value = {"size": 5}
        mock_fs.cat_file.return_value = b"hello"
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        result = be.cat_file(str(sandbox / "file.txt"))
        mock_fs.cat_file.assert_called_once()
        assert result == b"hello"


# ============================================================================
# TestPipeFile: File writing
# ============================================================================


class TestPipeFile:
    """Tests for LocalBackend.pipe_file method."""

    def test_pipe_file_writes_content(self, backend: LocalBackend, sandbox: Path) -> None:
        """pipe_file should write bytes to a file."""
        target = str(sandbox / "new_file.txt")
        backend.pipe_file(target, b"new content")
        assert (sandbox / "new_file.txt").read_bytes() == b"new content"

    def test_pipe_file_overwrites_existing(self, backend: LocalBackend, sandbox: Path) -> None:
        """pipe_file should overwrite existing file content."""
        target = str(sandbox / "file.txt")
        backend.pipe_file(target, b"overwritten")
        assert (sandbox / "file.txt").read_bytes() == b"overwritten"

    def test_pipe_file_size_limit(self, sandbox: Path) -> None:
        """pipe_file should enforce file size limit."""
        be = _make_backend(sandbox, max_file_size=50)
        with pytest.raises(FileTooLargeError):
            be.pipe_file(str(sandbox / "big.txt"), b"x" * 100)

    def test_pipe_file_extension_check(self, sandbox: Path) -> None:
        """pipe_file should check file extension against the deny list."""
        be = _make_backend(sandbox, denied_extensions=".exe,.bat")
        with pytest.raises(PermissionDeniedError):
            be.pipe_file(str(sandbox / "bad.exe"), b"malware")


class TestPipeFileWithMockedFs:
    """Unit tests for pipe_file with mocked fsspec filesystem."""

    def test_pipe_file_delegates_to_fsspec(self, sandbox: Path) -> None:
        """pipe_file should call fsspec's pipe_file method."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        be.pipe_file(str(sandbox / "file.txt"), b"data")
        mock_fs.pipe_file.assert_called_once()


# ============================================================================
# TestRm: File deletion
# ============================================================================


class TestRm:
    """Tests for LocalBackend.rm method."""

    def test_rm_deletes_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """rm should delete an existing file."""
        target = sandbox / "to_delete.txt"
        target.write_text("delete me")
        backend.rm(str(target))
        assert not target.exists()

    def test_rm_nonexistent_raises(self, backend: LocalBackend) -> None:
        """rm on a non-existent file should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.rm("nonexistent.txt")

    def test_rm_directory_raises(self, backend: LocalBackend, sandbox: Path) -> None:
        """rm on a directory should raise InvalidOperationError."""
        with pytest.raises(InvalidOperationError, match="Cannot remove directory"):
            backend.rm(str(sandbox / "subdir"))


class TestRmWithMockedFs:
    """Unit tests for rm with mocked fsspec filesystem."""

    def test_rm_delegates_to_fsspec(self, sandbox: Path) -> None:
        """rm should call fsspec's rm method after validation."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.isdir.return_value = False
        mock_fs.exists.return_value = True
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        be.rm(str(sandbox / "file.txt"))
        mock_fs.rm.assert_called_once()


# ============================================================================
# TestCpFile: File copy
# ============================================================================


class TestCpFile:
    """Tests for LocalBackend.cp_file method."""

    def test_cp_file_copies_content(self, backend: LocalBackend, sandbox: Path) -> None:
        """cp_file should copy a file to a new location."""
        src = str(sandbox / "file.txt")
        dst = str(sandbox / "file_copy.txt")
        backend.cp_file(src, dst)
        assert (sandbox / "file_copy.txt").read_text() == "hello world"

    def test_cp_file_source_still_exists(self, backend: LocalBackend, sandbox: Path) -> None:
        """cp_file should not delete the source."""
        src = str(sandbox / "file.txt")
        dst = str(sandbox / "file_copy.txt")
        backend.cp_file(src, dst)
        assert (sandbox / "file.txt").exists()


# ============================================================================
# TestMv: File move
# ============================================================================


class TestMv:
    """Tests for LocalBackend.mv method."""

    def test_mv_moves_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """mv should move a file to a new location."""
        src_file = sandbox / "moveme.txt"
        src_file.write_text("move content")
        backend.mv(str(src_file), str(sandbox / "moved.txt"))
        assert not src_file.exists()
        assert (sandbox / "moved.txt").read_text() == "move content"


# ============================================================================
# TestMkdir: Directory creation
# ============================================================================


class TestMkdir:
    """Tests for LocalBackend.mkdir method."""

    def test_mkdir_creates_directory(self, backend: LocalBackend, sandbox: Path) -> None:
        """mkdir should create a new directory."""
        target = str(sandbox / "new_dir")
        backend.mkdir(target)
        assert (sandbox / "new_dir").is_dir()

    def test_mkdir_create_parents(self, backend: LocalBackend, sandbox: Path) -> None:
        """mkdir with create_parents should create nested directories."""
        target = str(sandbox / "a" / "b" / "c")
        backend.mkdir(target, create_parents=True)
        assert (sandbox / "a" / "b" / "c").is_dir()

    def test_mkdir_existing_is_ok(self, backend: LocalBackend, sandbox: Path) -> None:
        """mkdir on an existing directory should not raise (idempotent)."""
        target = str(sandbox / "subdir")
        # Should not raise
        backend.mkdir(target, create_parents=True)


# ============================================================================
# TestExistsIsdirIsfile: Existence checks
# ============================================================================


class TestExistenceChecks:
    """Tests for exists, isdir, isfile methods."""

    def test_exists_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """exists should return True for existing files."""
        assert backend.exists(str(sandbox / "file.txt")) is True

    def test_exists_directory(self, backend: LocalBackend, sandbox: Path) -> None:
        """exists should return True for existing directories."""
        assert backend.exists(str(sandbox / "subdir")) is True

    def test_exists_nonexistent(self, backend: LocalBackend) -> None:
        """exists should return False for non-existent paths."""
        assert backend.exists("does_not_exist.txt") is False

    def test_isdir_on_dir(self, backend: LocalBackend, sandbox: Path) -> None:
        """isdir should return True for directories."""
        assert backend.isdir(str(sandbox / "subdir")) is True

    def test_isdir_on_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """isdir should return False for files."""
        assert backend.isdir(str(sandbox / "file.txt")) is False

    def test_isfile_on_file(self, backend: LocalBackend, sandbox: Path) -> None:
        """isfile should return True for files."""
        assert backend.isfile(str(sandbox / "file.txt")) is True

    def test_isfile_on_dir(self, backend: LocalBackend, sandbox: Path) -> None:
        """isfile should return False for directories."""
        assert backend.isfile(str(sandbox / "subdir")) is False


# ============================================================================
# TestHiddenFileFiltering: Hidden file policy
# ============================================================================


class TestHiddenFileFiltering:
    """Integration tests for hidden file filtering in ls."""

    def test_hidden_files_excluded_by_default(self, sandbox: Path) -> None:
        """ls should exclude dotfiles when show_hidden=False (default)."""
        (sandbox / ".hidden").write_text("secret")
        (sandbox / ".config").mkdir()
        be = _make_backend(sandbox, show_hidden=False)
        entries = be.ls(str(sandbox))
        names = [os.path.basename(e["name"]) for e in entries]
        assert ".hidden" not in names
        assert ".config" not in names

    def test_hidden_files_included_when_configured(self, sandbox: Path) -> None:
        """ls should include dotfiles when show_hidden=True."""
        (sandbox / ".hidden").write_text("secret")
        be = _make_backend(sandbox, show_hidden=True)
        entries = be.ls(str(sandbox))
        names = [os.path.basename(e["name"]) for e in entries]
        assert ".hidden" in names

    def test_hidden_files_excluded_but_regular_files_visible(self, sandbox: Path) -> None:
        """Regular files should still be visible when hidden are excluded."""
        (sandbox / ".hidden").write_text("secret")
        be = _make_backend(sandbox, show_hidden=False)
        entries = be.ls(str(sandbox))
        names = [os.path.basename(e["name"]) for e in entries]
        assert "file.txt" in names
        assert ".hidden" not in names

    def test_directory_with_only_hidden_files(self, sandbox: Path) -> None:
        """ls should return empty when directory has only hidden files and hidden excluded."""
        hidden_dir = sandbox / "all_hidden"
        hidden_dir.mkdir()
        (hidden_dir / ".a").write_text("a")
        (hidden_dir / ".b").write_text("b")
        be = _make_backend(sandbox, show_hidden=False)
        entries = be.ls(str(hidden_dir))
        assert entries == []


# ============================================================================
# TestSymlinkHandling: Symlink policy
# ============================================================================


class TestSymlinkHandling:
    """Integration tests for symlink handling."""

    def test_symlinks_excluded_when_not_following(self, sandbox: Path) -> None:
        """ls should exclude symlinks when follow_symlinks=False."""
        link = sandbox / "link.txt"
        link.symlink_to(sandbox / "file.txt")
        be = _make_backend(sandbox, follow_symlinks=False)
        entries = be.ls(str(sandbox))
        names = [os.path.basename(e["name"]) for e in entries]
        assert "link.txt" not in names

    def test_symlinks_included_when_following(self, sandbox: Path) -> None:
        """ls should include symlinks when follow_symlinks=True."""
        link = sandbox / "link.txt"
        link.symlink_to(sandbox / "file.txt")
        be = _make_backend(sandbox, follow_symlinks=True)
        entries = be.ls(str(sandbox))
        names = [os.path.basename(e["name"]) for e in entries]
        assert "link.txt" in names

    def test_symlink_outside_sandbox_excluded(self, sandbox: Path) -> None:
        """Symlinks pointing outside sandbox should be excluded even when following."""
        import shutil
        import tempfile

        # Create a truly external directory outside the sandbox
        external_dir = Path(tempfile.mkdtemp())
        try:
            external_file = external_dir / "external.txt"
            external_file.write_text("external")

            link = sandbox / "external_link.txt"
            link.symlink_to(external_file)
            be = _make_backend(sandbox, follow_symlinks=True)
            entries = be.ls(str(sandbox))
            names = [os.path.basename(e["name"]) for e in entries]
            assert "external_link.txt" not in names
        finally:
            shutil.rmtree(external_dir)

    def test_symlink_access_blocked_raises(self, sandbox: Path) -> None:
        """Direct access to a symlink should raise when follow_symlinks=False."""
        link = sandbox / "link.txt"
        link.symlink_to(sandbox / "file.txt")
        be = _make_backend(sandbox, follow_symlinks=False)

        from mamba_mcp_fs.errors import SymlinkBlockedError

        with pytest.raises(SymlinkBlockedError):
            be.cat_file(str(link))


# ============================================================================
# TestSecurityValidation: Path validation
# ============================================================================


class TestSecurityValidation:
    """Tests for security validation in LocalBackend."""

    def test_path_traversal_blocked(self, backend: LocalBackend) -> None:
        """Path traversal attempts should be blocked."""
        from mamba_mcp_fs.errors import PathOutsideSandboxError

        with pytest.raises(PathOutsideSandboxError):
            backend.ls("../../etc")

    def test_security_called_on_ls(self, sandbox: Path) -> None:
        """ls should validate paths through the security layer."""
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        with patch.object(sec, "validate_local_path", return_value=sandbox) as mock_validate:
            with patch.object(sec, "check_symlink"):
                be.ls(str(sandbox))
                mock_validate.assert_called_once_with(str(sandbox))

    def test_security_called_on_info(self, sandbox: Path) -> None:
        """info should validate paths through the security layer."""
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        with patch.object(
            sec, "validate_local_path", return_value=sandbox / "file.txt"
        ) as mock_validate:
            with patch.object(sec, "check_symlink"):
                be.info(str(sandbox / "file.txt"))
                mock_validate.assert_called_once()

    def test_security_called_on_cat_file(self, sandbox: Path) -> None:
        """cat_file should validate paths through the security layer."""
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        with patch.object(
            sec, "validate_local_path", return_value=sandbox / "file.txt"
        ) as mock_validate:
            with patch.object(sec, "check_symlink"):
                be.cat_file(str(sandbox / "file.txt"))
                mock_validate.assert_called_once()

    def test_security_called_on_pipe_file(self, sandbox: Path) -> None:
        """pipe_file should validate paths through the security layer."""
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        with patch.object(
            sec, "validate_local_path", return_value=sandbox / "new.txt"
        ) as mock_validate:
            with patch.object(sec, "check_symlink"):
                be.pipe_file(str(sandbox / "new.txt"), b"data")
                mock_validate.assert_called_once()

    def test_security_called_on_rm(self, sandbox: Path) -> None:
        """rm should validate paths through the security layer."""
        target = sandbox / "to_rm.txt"
        target.write_text("del")
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        with patch.object(sec, "validate_local_path", return_value=target) as mock_validate:
            with patch.object(sec, "check_symlink"):
                be.rm(str(target))
                mock_validate.assert_called_once()

    def test_security_called_on_cp_both_paths(self, sandbox: Path) -> None:
        """cp_file should validate both source and destination paths."""
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        call_count = 0
        original = sec.validate_local_path

        def tracking_validate(p: str) -> Path:
            nonlocal call_count
            call_count += 1
            return original(p)

        with patch.object(sec, "validate_local_path", side_effect=tracking_validate):
            with patch.object(sec, "check_symlink"):
                be.cp_file(str(sandbox / "file.txt"), str(sandbox / "copy.txt"))
                assert call_count == 2

    def test_security_called_on_mv_both_paths(self, sandbox: Path) -> None:
        """mv should validate both source and destination paths."""
        mv_src = sandbox / "mv_src.txt"
        mv_src.write_text("mv")
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        fs_instance = LocalFileSystem()
        be = LocalBackend(fs=fs_instance, security=sec, settings=local)

        call_count = 0
        original = sec.validate_local_path

        def tracking_validate(p: str) -> Path:
            nonlocal call_count
            call_count += 1
            return original(p)

        with patch.object(sec, "validate_local_path", side_effect=tracking_validate):
            with patch.object(sec, "check_symlink"):
                be.mv(str(mv_src), str(sandbox / "mv_dst.txt"))
                assert call_count == 2


# ============================================================================
# TestEdgeCases: Special characters, large listings
# ============================================================================


class TestEdgeCases:
    """Edge case tests for LocalBackend."""

    def test_path_with_spaces(self, backend: LocalBackend, sandbox: Path) -> None:
        """Paths with spaces should be handled correctly."""
        spaced = sandbox / "file with spaces.txt"
        spaced.write_text("spaced content")
        content = backend.cat_file(str(spaced))
        assert content == b"spaced content"

    def test_path_with_special_characters(self, backend: LocalBackend, sandbox: Path) -> None:
        """Paths with special characters should be handled correctly."""
        special = sandbox / "file-name_v2 (1).txt"
        special.write_text("special")
        assert backend.exists(str(special)) is True
        content = backend.cat_file(str(special))
        assert content == b"special"

    def test_large_directory_listing(self, sandbox: Path) -> None:
        """Large directory listings (1000+ entries) should be handled efficiently."""
        large_dir = sandbox / "large"
        large_dir.mkdir()
        for i in range(1000):
            (large_dir / f"file_{i:04d}.txt").write_text(f"content {i}")

        be = _make_backend(sandbox)
        entries = be.ls(str(large_dir))
        assert len(entries) == 1000

    def test_unicode_filenames(self, backend: LocalBackend, sandbox: Path) -> None:
        """Unicode filenames should be handled correctly."""
        unicode_file = sandbox / "caf\u00e9.txt"
        unicode_file.write_text("unicode content")
        assert backend.exists(str(unicode_file)) is True


# ============================================================================
# TestErrorMapping: Error type mapping
# ============================================================================


class TestErrorMapping:
    """Tests for error mapping from OS errors to FSError subclasses."""

    def test_file_not_found_mapped(self, backend: LocalBackend) -> None:
        """FileNotFoundError should be mapped to PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.cat_file("nonexistent.txt")

    def test_rm_file_not_found_mapped(self, backend: LocalBackend) -> None:
        """rm on nonexistent file should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.rm("nonexistent.txt")

    def test_info_not_found_mapped(self, backend: LocalBackend) -> None:
        """info on nonexistent path should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.info("nonexistent.txt")

    def test_ls_not_found_mapped(self, backend: LocalBackend) -> None:
        """ls on nonexistent directory should raise PathNotFoundError."""
        with pytest.raises(PathNotFoundError):
            backend.ls("nonexistent_dir")

    def test_os_error_mapped_to_backend_error(self, sandbox: Path) -> None:
        """OSError from fsspec should be mapped to BackendError."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.cat_file.side_effect = OSError("disk error")
        mock_fs.info.return_value = {"size": 5}
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        with pytest.raises(BackendError, match="Filesystem error"):
            be.cat_file(str(sandbox / "file.txt"))

    def test_permission_error_mapped(self, sandbox: Path) -> None:
        """PermissionError from OS should be mapped to PermissionDeniedError."""
        mock_fs = MagicMock(spec=LocalFileSystem)
        mock_fs.cat_file.side_effect = PermissionError("denied")
        mock_fs.info.return_value = {"size": 5}
        server = ServerSettings()
        local = LocalSettings(base_path=str(sandbox))
        sec = SecurityValidator(server, local)
        be = LocalBackend(fs=mock_fs, security=sec, settings=local)

        with pytest.raises(PermissionDeniedError):
            be.cat_file(str(sandbox / "file.txt"))
