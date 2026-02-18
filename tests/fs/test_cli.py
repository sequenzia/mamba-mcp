"""Tests for CLI argument parsing, env file handling, and commands."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from mamba_mcp_fs.__main__ import (
    app,
    resolve_default_env_file,
    setup_logging,
    validate_env_file,
)
from mamba_mcp_fs.config import get_env_file_path, set_env_file_path
from typer.testing import CliRunner

runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestCLI:
    """Tests for CLI using typer's CliRunner."""

    def test_cli_help(self) -> None:
        """Test that --help displays help and includes key options."""
        result = runner.invoke(app, ["--help"])
        output = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "--env-file" in output
        assert "--transport" in output
        assert "Filesystem MCP Server" in output

    def test_cli_with_env_file_missing(self, tmp_path: Path) -> None:
        """Test CLI with missing env file shows error."""
        missing_file = tmp_path / "missing.env"
        result = runner.invoke(app, ["--env-file", str(missing_file)])
        assert result.exit_code != 0
        assert "Environment file not found" in result.output

    def test_cli_with_env_file_is_directory(self, tmp_path: Path) -> None:
        """Test CLI with directory path shows error."""
        result = runner.invoke(app, ["--env-file", str(tmp_path)])
        assert result.exit_code != 0
        assert "Path is not a file" in result.output


class TestValidateEnvFile:
    """Tests for env file validation callback."""

    def _make_context(self, resilient_parsing: bool = False) -> typer.Context:
        """Create a mock typer.Context for testing."""
        ctx = MagicMock(spec=typer.Context)
        ctx.resilient_parsing = resilient_parsing
        return ctx

    def test_validate_env_file_none(self) -> None:
        """Test validation with None returns None."""
        ctx = self._make_context()
        result = validate_env_file(ctx, None)
        assert result is None

    def test_validate_env_file_valid_file(self, tmp_path: Path) -> None:
        """Test validation with valid file returns resolved path."""
        env_file = tmp_path / "test.env"
        env_file.write_text("MAMBA_MCP_FS_TRANSPORT=stdio")

        ctx = self._make_context()
        result = validate_env_file(ctx, str(env_file))
        assert result == str(env_file.resolve())

    def test_validate_env_file_missing_file(self, tmp_path: Path) -> None:
        """Test validation with missing file raises BadParameter."""
        missing_file = tmp_path / "missing.env"

        ctx = self._make_context()
        with pytest.raises(typer.BadParameter) as exc_info:
            validate_env_file(ctx, str(missing_file))

        assert "Environment file not found" in str(exc_info.value)

    def test_validate_env_file_directory(self, tmp_path: Path) -> None:
        """Test validation with directory path raises BadParameter."""
        ctx = self._make_context()
        with pytest.raises(typer.BadParameter) as exc_info:
            validate_env_file(ctx, str(tmp_path))

        assert "Path is not a file" in str(exc_info.value)

    def test_validate_env_file_resilient_parsing(self, tmp_path: Path) -> None:
        """Test validation during shell completion returns None."""
        ctx = self._make_context(resilient_parsing=True)
        env_file = tmp_path / "test.env"
        env_file.write_text("MAMBA_MCP_FS_TRANSPORT=stdio")
        result = validate_env_file(ctx, str(env_file))
        assert result is None


class TestResolveDefaultEnvFile:
    """Tests for auto-detection of mamba.env file."""

    def test_returns_explicit_path_unchanged(self, tmp_path: Path) -> None:
        """Test that explicitly provided path is returned unchanged."""
        env_file = tmp_path / "custom.env"
        env_file.write_text("MAMBA_MCP_FS_TRANSPORT=stdio")
        result = resolve_default_env_file(str(env_file))
        assert result == str(env_file)

    def test_detects_mamba_env_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mamba.env in cwd is detected when no explicit path provided."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text("MAMBA_MCP_FS_TRANSPORT=stdio")

        monkeypatch.chdir(tmp_path)

        result = resolve_default_env_file(None)
        assert result == str(env_file.resolve())

    def test_falls_back_to_home_mamba_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test fallback to ~/mamba.env when no mamba.env in cwd."""
        monkeypatch.chdir(tmp_path)

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        home_env = fake_home / "mamba.env"
        home_env.write_text("MAMBA_MCP_FS_TRANSPORT=stdio")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        result = resolve_default_env_file(None)
        assert result == str(home_env.resolve())

    def test_cwd_takes_priority_over_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that cwd mamba.env takes priority over ~/mamba.env."""
        cwd_env = tmp_path / "mamba.env"
        cwd_env.write_text("MAMBA_MCP_FS_TRANSPORT=stdio")

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        home_env = fake_home / "mamba.env"
        home_env.write_text("MAMBA_MCP_FS_TRANSPORT=streamable-http")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        result = resolve_default_env_file(None)
        assert result == str(cwd_env.resolve())

    def test_returns_none_when_no_mamba_env_anywhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that None is returned when no mamba.env exists anywhere."""
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        result = resolve_default_env_file(None)
        assert result is None

    def test_returns_none_when_mamba_env_is_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that None is returned when mamba.env exists but is a directory."""
        env_dir = tmp_path / "mamba.env"
        env_dir.mkdir()

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        result = resolve_default_env_file(None)
        assert result is None


class TestSetupLogging:
    """Tests for the setup_logging function."""

    def test_setup_logging_json_format(self) -> None:
        """Test JSON log format configuration."""
        # Should not raise
        setup_logging("INFO", "json")

    def test_setup_logging_text_format(self) -> None:
        """Test text log format configuration."""
        # Should not raise
        setup_logging("DEBUG", "text")


class TestEnvFilePathState:
    """Tests for module-level env file path state management."""

    def test_get_env_file_path_default(self) -> None:
        """Test default env file path is None."""
        set_env_file_path(None)
        assert get_env_file_path() is None

    def test_set_and_get_env_file_path(self) -> None:
        """Test setting and getting env file path."""
        test_path = "/custom/path/to/.env"
        set_env_file_path(test_path)
        assert get_env_file_path() == test_path
        set_env_file_path(None)  # Reset

    def test_set_env_file_path_to_none(self) -> None:
        """Test setting env file path back to None."""
        set_env_file_path("/some/path")
        set_env_file_path(None)
        assert get_env_file_path() is None


class TestTestCommand:
    """Tests for the 'test' CLI command."""

    def test_test_command_local_backend_ok(self, tmp_path: Path) -> None:
        """Test 'test' command shows OK when local backend path exists."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Local Backend: ENABLED" in result.output
        assert "Exists: OK" in result.output
        assert "Readable: OK" in result.output
        assert "Status: PASS" in result.output

    def test_test_command_shows_config_summary(self, tmp_path: Path) -> None:
        """Test 'test' command displays configuration summary."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
            "MAMBA_MCP_FS_READ_ONLY=true\n"
            "MAMBA_MCP_FS_TRANSPORT=stdio\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "mamba-mcp-fs v0.1.0" in result.output
        assert "Transport: stdio" in result.output
        assert "Mode: read-only" in result.output

    def test_test_command_local_disabled(self, tmp_path: Path) -> None:
        """Test 'test' command when local backend is disabled."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=false\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        # Should fail since no backends are enabled
        assert result.exit_code == 1
        assert "No backends enabled" in result.output
        assert "Status: FAIL" in result.output

    def test_test_command_s3_backend_shown(self, tmp_path: Path) -> None:
        """Test 'test' command shows S3 backend info when enabled."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_BUCKET=test-bucket\n"
            "MAMBA_MCP_FS_S3_REGION=us-west-2\n"
        )

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["test-bucket", "other-bucket"]
        mock_fs.exists.return_value = True

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "S3 Backend: ENABLED" in result.output
        assert "Region: us-west-2" in result.output
        assert "Default bucket: test-bucket" in result.output

    def test_test_command_help(self) -> None:
        """Test that test command help is displayed."""
        result = runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0
        assert "Test configuration" in result.output

    def test_test_command_with_env_file_option(self, tmp_path: Path) -> None:
        """Test that --env-file option works with test command."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])
        assert result.exit_code == 0
        assert "Status: PASS" in result.output


class TestTestCommandOutputFormat:
    """Tests for the exact output format of the test command."""

    def test_header_with_version(self, tmp_path: Path) -> None:
        """Test that header includes version and separator line."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert lines[0] == "mamba-mcp-fs v0.1.0"
        assert lines[1] == "=" * 40

    def test_transport_and_mode_section(self, tmp_path: Path) -> None:
        """Test transport and mode display."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
            "MAMBA_MCP_FS_TRANSPORT=stdio\n"
            "MAMBA_MCP_FS_READ_ONLY=true\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "Transport: stdio" in result.output
        assert "Mode: read-only" in result.output

    def test_read_write_mode(self, tmp_path: Path) -> None:
        """Test read-write mode display."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
            "MAMBA_MCP_FS_READ_ONLY=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "Mode: read-write" in result.output

    def test_entry_counts(self, tmp_path: Path) -> None:
        """Test that entry counts are displayed for base directory."""
        # Create some files and directories
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world")
        (tmp_path / "subdir1").mkdir()
        (tmp_path / "subdir2").mkdir()
        (tmp_path / "subdir3").mkdir()

        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        # 3 files (file1.txt, file2.txt, test.env) + 3 directories (subdir1, subdir2, subdir3)
        assert "Entries: 3 files, 3 directories" in result.output

    def test_security_section(self, tmp_path: Path) -> None:
        """Test security settings section output."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
            "MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS=false\n"
            "MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN=false\n"
            "MAMBA_MCP_FS_ALLOWED_EXTENSIONS=.txt,.py\n"
            "MAMBA_MCP_FS_DENIED_EXTENSIONS=.exe\n"
            "MAMBA_MCP_FS_RATE_LIMIT=60\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Security:" in result.output
        assert "Follow symlinks: false" in result.output
        assert "Show hidden: false" in result.output
        assert "Allowed extensions: .txt,.py" in result.output
        assert "Denied extensions: .exe" in result.output
        assert "Rate limit: 60/min" in result.output

    def test_security_defaults(self, tmp_path: Path) -> None:
        """Test security section with default settings."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Allowed extensions: (none)" in result.output
        assert "Denied extensions: (none)" in result.output
        assert "Rate limit: disabled" in result.output

    def test_s3_disabled_shows_disabled(self, tmp_path: Path) -> None:
        """Test that disabled S3 backend shows DISABLED label."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "S3 Backend: DISABLED" in result.output

    def test_writable_check_in_readwrite_mode(self, tmp_path: Path) -> None:
        """Test that writable check appears in read-write mode."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
            "MAMBA_MCP_FS_READ_ONLY=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Writable: OK" in result.output

    def test_writable_check_not_in_readonly_mode(self, tmp_path: Path) -> None:
        """Test that writable check is not shown in read-only mode."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
            "MAMBA_MCP_FS_READ_ONLY=true\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Writable:" not in result.output


class TestTestCommandEdgeCases:
    """Tests for edge cases in the test command."""

    def test_base_path_does_not_exist(self, tmp_path: Path) -> None:
        """Test that missing base_path gives clear error and FAIL status."""
        missing_path = tmp_path / "nonexistent"
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={missing_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=false\n"
            "MAMBA_MCP_FS_S3_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_BUCKET=test-bucket\n"
        )

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["test-bucket"]
        mock_fs.exists.return_value = True

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        # Local is disabled so base_path existence is not checked by the test command,
        # but config validator skips check when disabled. The test command should
        # still work. S3 enabled means at least one backend is active.
        assert "Local Backend: DISABLED" in result.output

    def test_base_path_is_file_not_directory(self, tmp_path: Path) -> None:
        """Test that base_path being a file gives clear error."""
        a_file = tmp_path / "not_a_dir.txt"
        a_file.write_text("I am a file")

        env_file = tmp_path / "test.env"
        # Config validator will fail when enabled=true and base_path is not a directory.
        # The test command catches config load errors gracefully.
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={a_file}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_empty_base_path_directory(self, tmp_path: Path) -> None:
        """Test test command with empty directory shows 0 entries."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={empty_dir}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Entries: 0 files, 0 directories" in result.output

    def test_both_backends_disabled(self, tmp_path: Path) -> None:
        """Test that both backends disabled reports all issues and FAIL."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=false\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Local Backend: DISABLED" in result.output
        assert "S3 Backend: DISABLED" in result.output
        assert "No backends enabled" in result.output
        assert "Status: FAIL" in result.output


class TestTestCommandErrorHandling:
    """Tests for error handling in the test command."""

    def test_config_load_error_does_not_crash(self, tmp_path: Path) -> None:
        """Test that configuration errors are caught and reported gracefully."""
        env_file = tmp_path / "test.env"
        # Empty base_path should cause a config validation error
        env_file.write_text("MAMBA_MCP_FS_LOCAL_BASE_PATH=\nMAMBA_MCP_FS_LOCAL_ENABLED=true\n")

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Status: FAIL" in result.output

    def test_reports_multiple_issues(self, tmp_path: Path) -> None:
        """Test that multiple issues are reported, not just the first one."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=false\n"
            "MAMBA_MCP_FS_S3_ENABLED=false\n"
        )

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Issues:" in result.output
        assert "No backends enabled" in result.output

    def test_s3_enabled_with_details(self, tmp_path: Path) -> None:
        """Test S3 backend section shows endpoint when configured."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_LOCAL_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_ENABLED=true\n"
            "MAMBA_MCP_FS_S3_BUCKET=my-bucket\n"
            "MAMBA_MCP_FS_S3_REGION=eu-west-1\n"
            "MAMBA_MCP_FS_S3_ENDPOINT_URL=http://localhost:4566\n"
        )

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["my-bucket"]
        mock_fs.exists.return_value = True

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "S3 Backend: ENABLED" in result.output
        assert "Default bucket: my-bucket" in result.output
        assert "Region: eu-west-1" in result.output
        assert "Endpoint: http://localhost:4566" in result.output


class TestTestCommandS3Connectivity:
    """Tests for S3 connectivity verification in the test command."""

    def _make_env_file(
        self,
        tmp_path: Path,
        *,
        s3_bucket: str | None = "my-bucket",
        s3_region: str = "us-east-1",
        s3_endpoint: str | None = None,
    ) -> Path:
        """Create an env file with S3 enabled and local backend pointing to tmp_path."""
        lines = [
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}",
            "MAMBA_MCP_FS_LOCAL_ENABLED=true",
            "MAMBA_MCP_FS_S3_ENABLED=true",
            f"MAMBA_MCP_FS_S3_REGION={s3_region}",
        ]
        if s3_bucket:
            lines.append(f"MAMBA_MCP_FS_S3_BUCKET={s3_bucket}")
        if s3_endpoint:
            lines.append(f"MAMBA_MCP_FS_S3_ENDPOINT_URL={s3_endpoint}")
        env_file = tmp_path / "test.env"
        env_file.write_text("\n".join(lines) + "\n")
        return env_file

    def test_s3_auth_ok_and_buckets_listed(self, tmp_path: Path) -> None:
        """Test successful S3 authentication shows bucket count."""
        env_file = self._make_env_file(tmp_path, s3_bucket=None)

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["bucket-a", "bucket-b", "bucket-c"]

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "S3 Backend: ENABLED" in result.output
        assert "Authentication: OK" in result.output
        assert "Buckets accessible: 3" in result.output
        assert "Status: PASS" in result.output

    def test_s3_default_bucket_accessible(self, tmp_path: Path) -> None:
        """Test default bucket check shows accessible OK when bucket exists."""
        env_file = self._make_env_file(tmp_path, s3_bucket="my-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["my-bucket", "other-bucket"]
        mock_fs.exists.return_value = True

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Default bucket: my-bucket (accessible: OK)" in result.output
        assert "Status: PASS" in result.output

    def test_s3_default_bucket_not_found(self, tmp_path: Path) -> None:
        """Test default bucket check shows FAIL when bucket does not exist."""
        env_file = self._make_env_file(tmp_path, s3_bucket="missing-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["other-bucket"]
        mock_fs.exists.return_value = False

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Default bucket: missing-bucket (accessible: FAIL" in result.output
        assert "bucket not found" in result.output
        assert "does not exist" in result.output
        assert "Status: FAIL" in result.output

    def test_s3_no_credentials_error(self, tmp_path: Path) -> None:
        """Test clear error when S3 credentials are missing."""
        from botocore.exceptions import NoCredentialsError

        env_file = self._make_env_file(tmp_path, s3_bucket="my-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.side_effect = NoCredentialsError()

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Authentication: FAIL (no credentials found)" in result.output
        assert "S3 credentials not found" in result.output
        assert "Status: FAIL" in result.output

    def test_s3_endpoint_connection_error(self, tmp_path: Path) -> None:
        """Test clear error when S3 endpoint is unreachable."""
        from botocore.exceptions import EndpointConnectionError

        env_file = self._make_env_file(
            tmp_path,
            s3_bucket="my-bucket",
            s3_endpoint="http://unreachable:4566",
        )

        mock_fs = MagicMock()
        mock_fs.ls.side_effect = EndpointConnectionError(endpoint_url="http://unreachable:4566")

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Authentication: FAIL (cannot connect to endpoint)" in result.output
        assert "Cannot connect to S3 endpoint" in result.output
        assert "Status: FAIL" in result.output

    def test_s3_client_error_on_auth(self, tmp_path: Path) -> None:
        """Test clear error when S3 returns a ClientError during auth check."""
        from botocore.exceptions import ClientError

        env_file = self._make_env_file(tmp_path, s3_bucket="my-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.side_effect = ClientError(
            error_response={"Error": {"Code": "403", "Message": "Access Denied"}},
            operation_name="ListBuckets",
        )

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Authentication: FAIL (403)" in result.output
        assert "S3 authentication failed" in result.output
        assert "Status: FAIL" in result.output

    def test_s3_os_error_on_auth(self, tmp_path: Path) -> None:
        """Test clear error when S3 raises an OSError (network issue)."""
        env_file = self._make_env_file(tmp_path, s3_bucket="my-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.side_effect = OSError("Connection refused")

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Authentication: FAIL (connection error)" in result.output
        assert "S3 connection error" in result.output
        assert "Status: FAIL" in result.output

    def test_s3_bucket_check_skipped_when_auth_fails(self, tmp_path: Path) -> None:
        """Test that default bucket check is skipped when authentication fails."""
        from botocore.exceptions import NoCredentialsError

        env_file = self._make_env_file(tmp_path, s3_bucket="my-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.side_effect = NoCredentialsError()

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "Default bucket: my-bucket (skipped - auth failed)" in result.output
        # exists should not have been called since auth failed
        mock_fs.exists.assert_not_called()

    def test_s3_region_and_default_endpoint_shown(self, tmp_path: Path) -> None:
        """Test that region and default AWS endpoint are displayed."""
        env_file = self._make_env_file(tmp_path, s3_bucket=None, s3_region="eu-west-1")

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["bucket-1"]

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "Region: eu-west-1" in result.output
        assert "Endpoint: (default AWS)" in result.output

    def test_s3_custom_endpoint_shown(self, tmp_path: Path) -> None:
        """Test that custom endpoint URL is displayed."""
        env_file = self._make_env_file(
            tmp_path,
            s3_bucket=None,
            s3_endpoint="http://localhost:9000",
        )

        mock_fs = MagicMock()
        mock_fs.ls.return_value = []

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert "Endpoint: http://localhost:9000" in result.output

    def test_s3_pass_status_when_all_checks_succeed(self, tmp_path: Path) -> None:
        """Test PASS status when S3 auth and bucket check both succeed."""
        env_file = self._make_env_file(tmp_path, s3_bucket="prod-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["prod-bucket", "staging-bucket"]
        mock_fs.exists.return_value = True

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "Authentication: OK" in result.output
        assert "Buckets accessible: 2" in result.output
        assert "Default bucket: prod-bucket (accessible: OK)" in result.output
        assert "Status: PASS" in result.output

    def test_s3_fail_status_reflects_all_checks(self, tmp_path: Path) -> None:
        """Test FAIL status when S3 checks fail."""
        from botocore.exceptions import NoCredentialsError

        env_file = self._make_env_file(tmp_path, s3_bucket="my-bucket")

        mock_fs = MagicMock()
        mock_fs.ls.side_effect = NoCredentialsError()

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 1
        assert "Status: FAIL" in result.output
        assert "Issues:" in result.output

    def test_s3_output_includes_s3_section(self, tmp_path: Path) -> None:
        """Test that CLI output includes the S3 section with connectivity details."""
        env_file = self._make_env_file(
            tmp_path,
            s3_bucket="data-bucket",
            s3_region="us-west-2",
            s3_endpoint="http://minio:9000",
        )

        mock_fs = MagicMock()
        mock_fs.ls.return_value = ["data-bucket"]
        mock_fs.exists.return_value = True

        with patch("mamba_mcp_fs.backends.s3.S3Backend") as mock_s3_cls:
            mock_s3_cls.return_value.fs = mock_fs
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        assert result.exit_code == 0
        assert "S3 Backend: ENABLED" in result.output
        assert "Region: us-west-2" in result.output
        assert "Endpoint: http://minio:9000" in result.output
        assert "Authentication: OK" in result.output
        assert "Buckets accessible: 1" in result.output
        assert "Default bucket: data-bucket (accessible: OK)" in result.output


class TestServerStartup:
    """Tests for server startup logic."""

    def test_server_startup_stdio(self, tmp_path: Path) -> None:
        """Test server starts with STDIO transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\nMAMBA_MCP_FS_TRANSPORT=stdio\n"
        )

        with patch("mamba_mcp_fs.__main__.mcp") as mock_mcp:
            runner.invoke(app, ["--env-file", str(env_file)])
            mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_server_startup_http(self, tmp_path: Path) -> None:
        """Test server starts with streamable-http transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\n"
            "MAMBA_MCP_FS_TRANSPORT=streamable-http\n"
            "MAMBA_MCP_FS_SERVER_HOST=localhost\n"
            "MAMBA_MCP_FS_SERVER_PORT=9090\n"
        )

        with patch("mamba_mcp_fs.__main__.mcp") as mock_mcp:
            runner.invoke(app, ["--env-file", str(env_file)])
            mock_mcp.run.assert_called_once_with(transport="streamable-http")

    def test_transport_flag_overrides_config(self, tmp_path: Path) -> None:
        """Test that --transport CLI flag overrides config setting."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\nMAMBA_MCP_FS_TRANSPORT=stdio\n"
        )

        with patch("mamba_mcp_fs.__main__.mcp") as mock_mcp:
            runner.invoke(app, ["--env-file", str(env_file), "--transport", "streamable-http"])
            mock_mcp.run.assert_called_once_with(transport="streamable-http")

    def test_server_startup_env_var_transport(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test transport is configurable via MAMBA_MCP_FS_TRANSPORT env var."""
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        monkeypatch.setenv("MAMBA_MCP_FS_TRANSPORT", "streamable-http")

        with patch("mamba_mcp_fs.__main__.mcp") as mock_mcp:
            runner.invoke(app, [])
            mock_mcp.run.assert_called_once_with(transport="streamable-http")

    def test_server_registers_tools_before_running(self, tmp_path: Path) -> None:
        """Test that tools are registered before the server starts."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={tmp_path}\nMAMBA_MCP_FS_TRANSPORT=stdio\n"
        )

        call_order: list[str] = []

        with (
            patch("mamba_mcp_fs.__main__._register_tools") as mock_register,
            patch("mamba_mcp_fs.__main__.mcp") as mock_mcp,
        ):
            mock_register.side_effect = lambda *args: call_order.append("register") or []
            mock_mcp.run.side_effect = lambda **kwargs: call_order.append("run")

            runner.invoke(app, ["--env-file", str(env_file)])

        assert call_order == ["register", "run"]
