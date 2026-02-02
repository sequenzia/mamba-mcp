"""Tests for mamba_mcp_core.cli module."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer
from mamba_mcp_core.cli import resolve_default_env_file, setup_logging, validate_env_file


class TestValidateEnvFile:
    """Tests for validate_env_file callback."""

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        ctx = MagicMock(spec=typer.Context)
        ctx.resilient_parsing = False
        assert validate_env_file(ctx, None) is None

    def test_valid_file(self, tmp_path: Path) -> None:
        """Valid file returns resolved absolute path."""
        env_file = tmp_path / "test.env"
        env_file.write_text("KEY=value")
        ctx = MagicMock(spec=typer.Context)
        ctx.resilient_parsing = False
        result = validate_env_file(ctx, str(env_file))
        assert result == str(env_file.resolve())

    def test_missing_file_raises(self) -> None:
        """Missing file raises BadParameter."""
        ctx = MagicMock(spec=typer.Context)
        ctx.resilient_parsing = False
        with pytest.raises(typer.BadParameter, match="not found"):
            validate_env_file(ctx, "/nonexistent/path.env")

    def test_directory_raises(self, tmp_path: Path) -> None:
        """Directory path raises BadParameter."""
        ctx = MagicMock(spec=typer.Context)
        ctx.resilient_parsing = False
        with pytest.raises(typer.BadParameter, match="not a file"):
            validate_env_file(ctx, str(tmp_path))

    def test_resilient_parsing_returns_none(self) -> None:
        """Resilient parsing (shell completion) returns None."""
        ctx = MagicMock(spec=typer.Context)
        ctx.resilient_parsing = True
        assert validate_env_file(ctx, "/some/path.env") is None


class TestResolveDefaultEnvFile:
    """Tests for resolve_default_env_file."""

    def test_explicit_path_returned(self) -> None:
        """Explicit path is returned unchanged."""
        assert resolve_default_env_file("/explicit/path.env") == "/explicit/path.env"

    def test_detects_cwd_mamba_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Finds mamba.env in current working directory."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text("KEY=value")
        monkeypatch.chdir(tmp_path)
        result = resolve_default_env_file(None)
        assert result == str(env_file.resolve())

    def test_falls_back_to_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to ~/mamba.env when not in cwd."""
        monkeypatch.chdir(tmp_path)  # No mamba.env here
        home_env = tmp_path / "home_mamba.env"
        home_env.write_text("KEY=value")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Create mamba.env in "home"
        (tmp_path / "mamba.env").write_text("KEY=value")
        result = resolve_default_env_file(None)
        assert result is not None

    def test_returns_none_when_no_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns None when no mamba.env found anywhere."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty_home")
        (tmp_path / "empty_home").mkdir()
        result = resolve_default_env_file(None)
        assert result is None


class TestSetupLogging:
    """Tests for setup_logging."""

    def test_json_format(self) -> None:
        """JSON format configures structured logging."""
        # Reset handlers to allow reconfiguration
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        setup_logging("DEBUG", "json")
        assert root.level == logging.DEBUG

    def test_text_format(self) -> None:
        """Text format configures human-readable logging."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        setup_logging("WARNING", "text")
        assert root.level == logging.WARNING
