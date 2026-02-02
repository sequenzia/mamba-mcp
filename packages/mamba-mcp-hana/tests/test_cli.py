"""Tests for CLI argument parsing and env file handling."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from mamba_mcp_hana.__main__ import (
    app,
    resolve_default_env_file,
    setup_logging,
    validate_env_file,
)
from mamba_mcp_hana.config import get_env_file_path, set_env_file_path
from typer.testing import CliRunner

runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestCLI:
    """Tests for CLI using typer's CliRunner."""

    def test_cli_help(self) -> None:
        """Test that --help displays help and includes --env-file option."""
        result = runner.invoke(app, ["--help"])
        output = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "--env-file" in output
        assert "PATH" in output
        assert "SAP HANA MCP Server" in output

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

    def test_cli_auto_loads_env_from_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test CLI auto-loads mamba.env from cwd when --env-file not specified."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=auto-loaded-host\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=testuser\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=testpass\n"
        )

        monkeypatch.chdir(tmp_path)

        with patch("mamba_mcp_hana.__main__.create_pool") as mock_create:
            mock_pool = AsyncMock()
            mock_pool.test_connection = AsyncMock()
            mock_pool.close = AsyncMock()
            mock_create.return_value = mock_pool

            result = runner.invoke(app, ["test"])

            assert result.exit_code == 0
            call_args = mock_create.call_args[0][0]
            assert call_args.db_host == "auto-loaded-host"

    def test_cli_works_without_env_file_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test CLI proceeds without error when no mamba.env in cwd and no --env-file."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "env-var-host")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "testpass")

        with patch("mamba_mcp_hana.__main__.create_pool") as mock_create:
            mock_pool = AsyncMock()
            mock_pool.test_connection = AsyncMock()
            mock_pool.close = AsyncMock()
            mock_create.return_value = mock_pool

            result = runner.invoke(app, ["test"])

            assert result.exit_code == 0
            call_args = mock_create.call_args[0][0]
            assert call_args.db_host == "env-var-host"


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
        env_file.write_text("MAMBA_MCP_HANA_DB_HOST=localhost")

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
        env_file.write_text("MAMBA_MCP_HANA_DB_HOST=localhost")
        result = validate_env_file(ctx, str(env_file))
        assert result is None


class TestResolveDefaultEnvFile:
    """Tests for auto-detection of mamba.env file."""

    def test_returns_explicit_path_unchanged(self, tmp_path: Path) -> None:
        """Test that explicitly provided path is returned unchanged."""
        env_file = tmp_path / "custom.env"
        env_file.write_text("MAMBA_MCP_HANA_DB_HOST=localhost")
        result = resolve_default_env_file(str(env_file))
        assert result == str(env_file)

    def test_detects_mamba_env_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mamba.env in cwd is detected when no explicit path provided."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text("MAMBA_MCP_HANA_DB_HOST=localhost")

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
        home_env.write_text("MAMBA_MCP_HANA_DB_HOST=home-host")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        result = resolve_default_env_file(None)
        assert result == str(home_env.resolve())

    def test_cwd_takes_priority_over_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that cwd mamba.env takes priority over ~/mamba.env."""
        cwd_env = tmp_path / "mamba.env"
        cwd_env.write_text("MAMBA_MCP_HANA_DB_HOST=cwd-host")

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        home_env = fake_home / "mamba.env"
        home_env.write_text("MAMBA_MCP_HANA_DB_HOST=home-host")

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

    def test_set_env_file_path_to_none(self) -> None:
        """Test setting env file path back to None."""
        set_env_file_path("/some/path")
        set_env_file_path(None)
        assert get_env_file_path() is None


class TestTestCommand:
    """Tests for the 'test' CLI command."""

    def test_test_command_success(self, tmp_path: Path) -> None:
        """Test successful connection test exits with code 0."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=localhost\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=testuser\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=testpass\n"
        )

        with patch("mamba_mcp_hana.__main__.create_pool") as mock_create:
            mock_pool = AsyncMock()
            mock_pool.test_connection = AsyncMock()
            mock_pool.close = AsyncMock()
            mock_create.return_value = mock_pool

            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            assert "Connection successful" in result.output
            mock_create.assert_called_once()
            mock_pool.test_connection.assert_called_once()
            mock_pool.close.assert_called_once()

    def test_test_command_failure(self, tmp_path: Path) -> None:
        """Test failed connection test exits with code 1."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=localhost\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=testuser\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=testpass\n"
        )

        with patch("mamba_mcp_hana.__main__.create_pool") as mock_create:
            mock_pool = AsyncMock()
            mock_pool.test_connection = AsyncMock(side_effect=ConnectionError("Connection refused"))
            mock_pool.close = AsyncMock()
            mock_create.return_value = mock_pool

            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 1
            assert "Connection failed" in result.output
            assert "Connection refused" in result.output

    def test_test_command_with_env_file_option(self, tmp_path: Path) -> None:
        """Test that --env-file option works with test command."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=custom-host\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=custom_user\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=custom_pass\n"
        )

        with patch("mamba_mcp_hana.__main__.create_pool") as mock_create:
            mock_pool = AsyncMock()
            mock_pool.test_connection = AsyncMock()
            mock_pool.close = AsyncMock()
            mock_create.return_value = mock_pool

            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            call_args = mock_create.call_args[0][0]
            assert call_args.db_host == "custom-host"

    def test_test_command_help(self) -> None:
        """Test that test command help is displayed."""
        result = runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0
        assert "Test database connection" in result.output

    def test_test_command_missing_required_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that missing required env vars produces a clear error."""
        # Create an env file without required auth vars
        env_file = tmp_path / "test.env"
        env_file.write_text("MAMBA_MCP_HANA_DB_HOST=localhost\n")

        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["--env-file", str(env_file), "test"])

        # Should fail because auth config is missing
        assert result.exit_code != 0


class TestDefaultServeCommand:
    """Tests for the default serve command invocation."""

    def test_default_serve_stdio(self, tmp_path: Path) -> None:
        """Test default invocation starts MCP server with stdio transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=localhost\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=testuser\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=testpass\n"
            "MAMBA_MCP_HANA_TRANSPORT=stdio\n"
        )

        with patch("mamba_mcp_hana.__main__.mcp") as mock_mcp:
            result = runner.invoke(app, ["--env-file", str(env_file)])

            assert result.exit_code == 0
            mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_default_serve_http(self, tmp_path: Path) -> None:
        """Test default invocation starts MCP server with http transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=localhost\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=testuser\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=testpass\n"
            "MAMBA_MCP_HANA_TRANSPORT=http\n"
        )

        with patch("mamba_mcp_hana.__main__.mcp") as mock_mcp:
            result = runner.invoke(app, ["--env-file", str(env_file)])

            assert result.exit_code == 0
            mock_mcp.run.assert_called_once_with(transport="streamable-http")


class TestSetupLogging:
    """Tests for the setup_logging function."""

    def test_json_format(self) -> None:
        """Test logging configured with JSON format."""
        with patch("mamba_mcp_hana.__main__.logging.basicConfig") as mock_config:
            setup_logging("INFO", "json")

            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert "json" in call_kwargs["format"].lower() or "{" in call_kwargs["format"]
            assert call_kwargs["level"] == "INFO"

    def test_text_format(self) -> None:
        """Test logging configured with text format."""
        with patch("mamba_mcp_hana.__main__.logging.basicConfig") as mock_config:
            setup_logging("DEBUG", "text")

            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert "%(asctime)s" in call_kwargs["format"]
            assert "%(levelname)s" in call_kwargs["format"]
            assert call_kwargs["level"] == "DEBUG"

    def test_level_uppercased(self) -> None:
        """Test logging level is uppercased."""
        with patch("mamba_mcp_hana.__main__.logging.basicConfig") as mock_config:
            setup_logging("warning", "json")

            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == "WARNING"


class TestDefaultServeTextLogging:
    """Tests for serve command with text log format."""

    def test_default_serve_with_text_logging(self, tmp_path: Path) -> None:
        """Test serve command invokes setup_logging with text format."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=localhost\n"
            "MAMBA_MCP_HANA_DB_PORT=30015\n"
            "MAMBA_MCP_HANA_DB_USER=testuser\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=testpass\n"
            "MAMBA_MCP_HANA_TRANSPORT=stdio\n"
            "MAMBA_MCP_HANA_LOG_FORMAT=text\n"
        )

        with patch("mamba_mcp_hana.__main__.mcp") as mock_mcp:
            result = runner.invoke(app, ["--env-file", str(env_file)])

            assert result.exit_code == 0
            mock_mcp.run.assert_called_once_with(transport="stdio")


class TestSettingsWithEnvFile:
    """Integration tests for settings loading with custom env file."""

    def test_settings_loads_from_custom_env_file(self, tmp_path: Path) -> None:
        """Test that settings loads values from custom env file."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=custom-host\n"
            "MAMBA_MCP_HANA_DB_PORT=443\n"
            "MAMBA_MCP_HANA_DB_USER=custom_user\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=custom_pass\n"
            "MAMBA_MCP_HANA_LOG_LEVEL=DEBUG\n"
        )

        set_env_file_path(str(env_file))

        from mamba_mcp_hana.config import get_settings

        settings = get_settings()

        assert settings.database.db_host == "custom-host"
        assert settings.database.db_port == 443
        assert settings.database.db_user == "custom_user"
        assert settings.database.db_password.get_secret_value() == "custom_pass"
        assert settings.server.log_level == "DEBUG"
