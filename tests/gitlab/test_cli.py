"""Tests for CLI argument parsing, env file handling, and test subcommand."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_gitlab.__main__ import app
from mamba_mcp_gitlab.auth import AuthenticationError, AuthInfo
from typer.testing import CliRunner

runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ---------------------------------------------------------------------------
# Helpers for mocking the test subcommand
# ---------------------------------------------------------------------------


def _make_auth_info(
    username: str = "testuser",
    scopes: list[str] | None = None,
) -> AuthInfo:
    """Create an AuthInfo instance for test assertions."""
    return AuthInfo(
        auth_type="pat",
        username=username,
        scopes=scopes if scopes is not None else ["api"],
        expires_at="2027-12-31",
    )


def _make_mock_auth_strategy(
    *,
    auth_info: AuthInfo | None = None,
    validate_error: AuthenticationError | None = None,
) -> MagicMock:
    """Create a mock auth strategy for the test subcommand.

    Uses MagicMock (not AsyncMock) so that synchronous methods like
    get_headers() return plain values. Only validate() is set up as
    an AsyncMock since it is an async method.
    """
    strategy = MagicMock()
    strategy.get_headers.return_value = {"PRIVATE-TOKEN": "glpat-test-token"}
    strategy.validate = AsyncMock()
    if validate_error:
        strategy.validate.side_effect = validate_error
    else:
        strategy.validate.return_value = auth_info or _make_auth_info()
    return strategy


class TestCLIHelp:
    """Tests for CLI help text and basic rendering."""

    def test_cli_help_displays(self) -> None:
        """Test that --help displays help and includes --env-file option."""
        result = runner.invoke(app, ["--help"])
        output = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "--env-file" in output
        assert "PATH" in output
        assert "GitLab MCP Server" in output

    def test_cli_help_includes_test_subcommand(self) -> None:
        """Test that --help mentions the test subcommand."""
        result = runner.invoke(app, ["--help"])
        output = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "test" in output

    def test_test_subcommand_help(self) -> None:
        """Test that test --help displays test subcommand help."""
        result = runner.invoke(app, ["test", "--help"])
        output = strip_ansi(result.output)
        assert result.exit_code == 0
        assert "GitLab connectivity" in output


class TestCLIEnvFile:
    """Tests for --env-file option handling."""

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

    def test_cli_env_file_resolves_for_test_subcommand(self, tmp_path: Path) -> None:
        """Test that --env-file option works with test subcommand."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        mock_strategy = _make_mock_auth_strategy()

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            assert "Connection successful" in result.output


class TestCLIAutoDetectEnv:
    """Tests for auto-detection of mamba.env file."""

    def test_cli_auto_loads_env_from_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test CLI auto-loads mamba.env from cwd when --env-file not specified."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://auto-loaded.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-auto-loaded-token\n"
        )

        monkeypatch.chdir(tmp_path)

        mock_strategy = _make_mock_auth_strategy()

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["test"])

            assert result.exit_code == 0
            assert "Connection successful" in result.output

    def test_cli_works_without_env_file_in_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test CLI proceeds without error when no mamba.env in cwd and no --env-file."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://env-var.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-env-var-token")

        mock_strategy = _make_mock_auth_strategy()

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["test"])

            assert result.exit_code == 0
            assert "Connection successful" in result.output


class TestTestSubcommandSuccess:
    """Tests for successful test subcommand scenarios."""

    def test_test_command_success(self, tmp_path: Path) -> None:
        """Test successful connectivity test exits with code 0."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        mock_strategy = _make_mock_auth_strategy()

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            assert "Connection successful" in result.output
            assert "testuser" in result.output
            assert "api" in result.output

    def test_test_command_shows_em_dash(self, tmp_path: Path) -> None:
        """Test success message contains em dash separator."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        mock_strategy = _make_mock_auth_strategy()

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            assert "\u2014" in result.output  # em dash

    def test_test_command_multiple_scopes(self, tmp_path: Path) -> None:
        """Test success message shows comma-separated scopes."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        auth_info = _make_auth_info(scopes=["api", "read_user", "read_repository"])
        mock_strategy = _make_mock_auth_strategy(auth_info=auth_info)

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            assert "api, read_user, read_repository" in result.output

    def test_test_command_empty_scopes(self, tmp_path: Path) -> None:
        """Test success message shows 'none' for empty scopes list."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        auth_info = _make_auth_info(scopes=[])
        mock_strategy = _make_mock_auth_strategy(auth_info=auth_info)

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 0
            assert "scopes: none" in result.output


class TestTestSubcommandFailure:
    """Tests for test subcommand failure scenarios."""

    def test_test_command_auth_config_error(self, tmp_path: Path) -> None:
        """Test authentication configuration error exits with code 1."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            side_effect=AuthenticationError("No authentication configured"),
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 1
            assert "Authentication configuration error" in result.output
            assert "No authentication configured" in result.output

    def test_test_command_connection_failure(self, tmp_path: Path) -> None:
        """Test connection failure exits with code 1."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        mock_strategy = _make_mock_auth_strategy(
            validate_error=AuthenticationError("Cannot reach GitLab at https://gitlab.example.com"),
        )

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 1
            assert "Connection failed" in result.output
            assert "Cannot reach GitLab" in result.output

    def test_test_command_invalid_token(self, tmp_path: Path) -> None:
        """Test invalid token exits with code 1."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        mock_strategy = _make_mock_auth_strategy(
            validate_error=AuthenticationError("GitLab token is invalid or expired"),
        )

        with patch(
            "mamba_mcp_gitlab.__main__.detect_auth_strategy",
            return_value=mock_strategy,
        ):
            result = runner.invoke(app, ["--env-file", str(env_file), "test"])

            assert result.exit_code == 1
            assert "Connection failed" in result.output
            assert "invalid or expired" in result.output


class TestServerStartup:
    """Tests for the bare command (server startup)."""

    def test_main_starts_server_stdio(self, tmp_path: Path) -> None:
        """Test bare command starts MCP server with stdio transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
        )

        with patch("mamba_mcp_gitlab.__main__.mcp") as mock_mcp:
            result = runner.invoke(app, ["--env-file", str(env_file)])

            mock_mcp.run.assert_called_once_with(transport="stdio")
            assert result.exit_code == 0

    def test_main_starts_server_http(self, tmp_path: Path) -> None:
        """Test bare command starts MCP server with streamable-http transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
            "MAMBA_MCP_GITLAB_SERVER_TRANSPORT=http\n"
        )

        with patch("mamba_mcp_gitlab.__main__.mcp") as mock_mcp:
            result = runner.invoke(app, ["--env-file", str(env_file)])

            mock_mcp.run.assert_called_once_with(transport="streamable-http")
            assert result.exit_code == 0

    def test_main_starts_server_streamable_http(self, tmp_path: Path) -> None:
        """Test bare command normalizes 'streamable-http' transport."""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-test-token-xxxx\n"
            "MAMBA_MCP_GITLAB_SERVER_TRANSPORT=streamable-http\n"
        )

        with patch("mamba_mcp_gitlab.__main__.mcp") as mock_mcp:
            result = runner.invoke(app, ["--env-file", str(env_file)])

            mock_mcp.run.assert_called_once_with(transport="streamable-http")
            assert result.exit_code == 0


class TestToolRegistration:
    """Tests for tool module side-effect imports."""

    def test_tool_modules_are_importable(self) -> None:
        """Test that tool modules can be imported from __main__."""
        # The import in __main__.py should not raise
        from mamba_mcp_gitlab.__main__ import (  # noqa: F401
            issue_tools,
            mr_tools,
            pipeline_tools,
            search_tools,
        )
