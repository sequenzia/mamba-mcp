"""Tests for configuration system (ServerSettings, LocalSettings, S3Settings).

Covers: default values, env var loading, extension parsing, validation errors,
and .env file integration.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from mamba_mcp_fs.config import (
    LocalSettings,
    S3Settings,
    ServerSettings,
    get_env_file_path,
    get_settings,
    set_env_file_path,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# ServerSettings -- default values
# ---------------------------------------------------------------------------
class TestServerSettingsDefaults:
    """All ServerSettings fields have the expected default values."""

    def test_transport_default(self) -> None:
        settings = ServerSettings()
        assert settings.transport == "stdio"

    def test_server_host_default(self) -> None:
        settings = ServerSettings()
        assert settings.server_host == "0.0.0.0"

    def test_server_port_default(self) -> None:
        settings = ServerSettings()
        assert settings.server_port == 8080

    def test_log_level_default(self) -> None:
        settings = ServerSettings()
        assert settings.log_level == "INFO"

    def test_log_format_default(self) -> None:
        settings = ServerSettings()
        assert settings.log_format == "json"

    def test_read_only_default(self) -> None:
        settings = ServerSettings()
        assert settings.read_only is True

    def test_rate_limit_default(self) -> None:
        settings = ServerSettings()
        assert settings.rate_limit == 0

    def test_allowed_extensions_default(self) -> None:
        settings = ServerSettings()
        assert settings.allowed_extensions is None

    def test_denied_extensions_default(self) -> None:
        settings = ServerSettings()
        assert settings.denied_extensions is None


# ---------------------------------------------------------------------------
# ServerSettings -- env var loading
# ---------------------------------------------------------------------------
class TestServerSettingsEnvLoading:
    """ServerSettings reads values from MAMBA_MCP_FS_* env vars."""

    def test_transport_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_TRANSPORT", "streamable-http")
        settings = ServerSettings()
        assert settings.transport == "streamable-http"

    def test_server_host_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_SERVER_HOST", "127.0.0.1")
        settings = ServerSettings()
        assert settings.server_host == "127.0.0.1"

    def test_server_port_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_SERVER_PORT", "9090")
        settings = ServerSettings()
        assert settings.server_port == 9090

    def test_log_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOG_LEVEL", "DEBUG")
        settings = ServerSettings()
        assert settings.log_level == "DEBUG"

    def test_log_format_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOG_FORMAT", "text")
        settings = ServerSettings()
        assert settings.log_format == "text"

    def test_read_only_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_READ_ONLY", "false")
        settings = ServerSettings()
        assert settings.read_only is False

    def test_rate_limit_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_RATE_LIMIT", "100")
        settings = ServerSettings()
        assert settings.rate_limit == 100

    def test_allowed_extensions_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", ".py,.md,.txt")
        settings = ServerSettings()
        assert settings.allowed_extensions == ".py,.md,.txt"

    def test_denied_extensions_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_DENIED_EXTENSIONS", ".exe,.bat")
        settings = ServerSettings()
        assert settings.denied_extensions == ".exe,.bat"


# ---------------------------------------------------------------------------
# ServerSettings -- extension parsing
# ---------------------------------------------------------------------------
class TestExtensionParsing:
    """parsed_allowed_extensions and parsed_denied_extensions work correctly."""

    def test_parsed_allowed_none_when_not_set(self) -> None:
        settings = ServerSettings()
        assert settings.parsed_allowed_extensions is None

    def test_parsed_denied_none_when_not_set(self) -> None:
        settings = ServerSettings()
        assert settings.parsed_denied_extensions is None

    def test_parsed_allowed_simple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", ".py,.md,.txt")
        settings = ServerSettings()
        assert settings.parsed_allowed_extensions == {".py", ".md", ".txt"}

    def test_parsed_denied_simple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_DENIED_EXTENSIONS", ".exe,.bat")
        settings = ServerSettings()
        assert settings.parsed_denied_extensions == {".exe", ".bat"}

    def test_whitespace_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", " .py , .md , .txt ")
        settings = ServerSettings()
        assert settings.parsed_allowed_extensions == {".py", ".md", ".txt"}

    def test_case_normalization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", ".PY,.Md,.TXT")
        settings = ServerSettings()
        assert settings.parsed_allowed_extensions == {".py", ".md", ".txt"}

    def test_empty_string_treated_as_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", "")
        settings = ServerSettings()
        assert settings.allowed_extensions is None
        assert settings.parsed_allowed_extensions is None

    def test_whitespace_only_treated_as_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", "   ")
        settings = ServerSettings()
        assert settings.allowed_extensions is None
        assert settings.parsed_allowed_extensions is None

    def test_single_extension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_DENIED_EXTENSIONS", ".exe")
        settings = ServerSettings()
        assert settings.parsed_denied_extensions == {".exe"}

    def test_trailing_comma_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", ".py,.md,")
        settings = ServerSettings()
        assert settings.parsed_allowed_extensions == {".py", ".md"}

    def test_duplicate_extensions_collapsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_ALLOWED_EXTENSIONS", ".py,.py,.md")
        settings = ServerSettings()
        assert settings.parsed_allowed_extensions == {".py", ".md"}


# ---------------------------------------------------------------------------
# ServerSettings -- validation errors
# ---------------------------------------------------------------------------
class TestServerSettingsValidation:
    """Invalid values raise ValidationError."""

    def test_invalid_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_TRANSPORT", "websocket")
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings()
        assert "transport" in str(exc_info.value).lower()

    def test_invalid_log_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOG_FORMAT", "xml")
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings()
        assert "log_format" in str(exc_info.value).lower()

    def test_port_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_SERVER_PORT", "0")
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings()
        assert "server_port" in str(exc_info.value).lower()

    def test_port_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_SERVER_PORT", "70000")
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings()
        assert "server_port" in str(exc_info.value).lower()

    def test_port_negative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_SERVER_PORT", "-1")
        with pytest.raises(ValidationError):
            ServerSettings()

    def test_rate_limit_negative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_RATE_LIMIT", "-5")
        with pytest.raises(ValidationError):
            ServerSettings()


# ---------------------------------------------------------------------------
# LocalSettings -- default values (requires base_path)
# ---------------------------------------------------------------------------
class TestLocalSettingsDefaults:
    """LocalSettings fields have the expected default values."""

    def test_enabled_default(self, tmp_path: Path) -> None:
        settings = LocalSettings(base_path=str(tmp_path))
        assert settings.enabled is True

    def test_max_file_size_default(self, tmp_path: Path) -> None:
        settings = LocalSettings(base_path=str(tmp_path))
        assert settings.max_file_size == 10_485_760

    def test_follow_symlinks_default(self, tmp_path: Path) -> None:
        settings = LocalSettings(base_path=str(tmp_path))
        assert settings.follow_symlinks is False

    def test_show_hidden_default(self, tmp_path: Path) -> None:
        settings = LocalSettings(base_path=str(tmp_path))
        assert settings.show_hidden is False


# ---------------------------------------------------------------------------
# LocalSettings -- env var loading
# ---------------------------------------------------------------------------
class TestLocalSettingsEnvLoading:
    """LocalSettings reads values from MAMBA_MCP_FS_LOCAL_* env vars."""

    def test_base_path_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        settings = LocalSettings()
        assert settings.base_path == str(tmp_path)

    def test_enabled_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_ENABLED", "false")
        settings = LocalSettings()
        assert settings.enabled is False

    def test_max_file_size_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_MAX_FILE_SIZE", "5242880")
        settings = LocalSettings()
        assert settings.max_file_size == 5_242_880

    def test_follow_symlinks_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS", "true")
        settings = LocalSettings()
        assert settings.follow_symlinks is True

    def test_show_hidden_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN", "true")
        settings = LocalSettings()
        assert settings.show_hidden is True


# ---------------------------------------------------------------------------
# LocalSettings -- validation errors
# ---------------------------------------------------------------------------
class TestLocalSettingsValidation:
    """Invalid LocalSettings values raise clear validation errors."""

    def test_missing_base_path_raises_error(self) -> None:
        """Missing required base_path raises a clear validation error."""
        with pytest.raises(ValidationError) as exc_info:
            LocalSettings()
        assert "base_path" in str(exc_info.value).lower()

    def test_nonexistent_base_path_raises_error(self) -> None:
        """Non-existent base_path raises a validation error."""
        with pytest.raises(ValidationError) as exc_info:
            LocalSettings(base_path="/this/path/does/not/exist/anywhere")
        assert "base_path" in str(exc_info.value).lower()
        assert "does not exist" in str(exc_info.value).lower()

    def test_base_path_is_file_raises_error(self, tmp_path: Path) -> None:
        """base_path pointing to a file (not directory) raises a validation error."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(ValidationError) as exc_info:
            LocalSettings(base_path=str(file_path))
        assert "not a directory" in str(exc_info.value).lower()

    def test_empty_base_path_raises_error(self) -> None:
        """Empty string base_path raises a validation error."""
        with pytest.raises(ValidationError) as exc_info:
            LocalSettings(base_path="")
        assert "base_path" in str(exc_info.value).lower()

    def test_whitespace_base_path_raises_error(self) -> None:
        """Whitespace-only base_path raises a validation error."""
        with pytest.raises(ValidationError) as exc_info:
            LocalSettings(base_path="   ")
        assert "base_path" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# S3Settings -- default values
# ---------------------------------------------------------------------------
class TestS3SettingsDefaults:
    """All S3Settings fields have the expected default values."""

    def test_enabled_default(self) -> None:
        settings = S3Settings()
        assert settings.enabled is False

    def test_bucket_default(self) -> None:
        settings = S3Settings()
        assert settings.bucket is None

    def test_prefix_default(self) -> None:
        settings = S3Settings()
        assert settings.prefix == ""

    def test_region_default(self) -> None:
        settings = S3Settings()
        assert settings.region == "us-east-1"

    def test_endpoint_url_default(self) -> None:
        settings = S3Settings()
        assert settings.endpoint_url is None

    def test_max_file_size_default(self) -> None:
        settings = S3Settings()
        assert settings.max_file_size == 52_428_800


# ---------------------------------------------------------------------------
# S3Settings -- env var loading
# ---------------------------------------------------------------------------
class TestS3SettingsEnvLoading:
    """S3Settings reads values from MAMBA_MCP_FS_S3_* env vars."""

    def test_enabled_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_S3_ENABLED", "true")
        settings = S3Settings()
        assert settings.enabled is True

    def test_bucket_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_S3_BUCKET", "my-data-bucket")
        settings = S3Settings()
        assert settings.bucket == "my-data-bucket"

    def test_prefix_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_S3_PREFIX", "data/2024/")
        settings = S3Settings()
        assert settings.prefix == "data/2024/"

    def test_region_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_S3_REGION", "eu-west-1")
        settings = S3Settings()
        assert settings.region == "eu-west-1"

    def test_endpoint_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_S3_ENDPOINT_URL", "http://localhost:4566")
        settings = S3Settings()
        assert settings.endpoint_url == "http://localhost:4566"

    def test_max_file_size_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_S3_MAX_FILE_SIZE", "104857600")
        settings = S3Settings()
        assert settings.max_file_size == 104_857_600


# ---------------------------------------------------------------------------
# Integration: Loading from .env file
# ---------------------------------------------------------------------------
class TestEnvFileLoading:
    """Settings load values from mamba.env file."""

    def test_server_settings_from_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ServerSettings reads from mamba.env when present."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text(
            textwrap.dedent("""\
                MAMBA_MCP_FS_TRANSPORT=streamable-http
                MAMBA_MCP_FS_SERVER_PORT=9999
                MAMBA_MCP_FS_LOG_FORMAT=text
                MAMBA_MCP_FS_READ_ONLY=false
            """)
        )
        # Change to the directory containing the env file so pydantic finds it
        monkeypatch.chdir(tmp_path)
        settings = ServerSettings()
        assert settings.transport == "streamable-http"
        assert settings.server_port == 9999
        assert settings.log_format == "text"
        assert settings.read_only is False

    def test_s3_settings_from_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S3Settings reads from mamba.env when present."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text(
            textwrap.dedent("""\
                MAMBA_MCP_FS_S3_ENABLED=true
                MAMBA_MCP_FS_S3_BUCKET=test-bucket
                MAMBA_MCP_FS_S3_REGION=ap-southeast-1
            """)
        )
        monkeypatch.chdir(tmp_path)
        settings = S3Settings()
        assert settings.enabled is True
        assert settings.bucket == "test-bucket"
        assert settings.region == "ap-southeast-1"

    def test_local_settings_from_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LocalSettings reads from mamba.env when present."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        env_file = tmp_path / "mamba.env"
        env_file.write_text(
            textwrap.dedent(f"""\
                MAMBA_MCP_FS_LOCAL_BASE_PATH={sandbox}
                MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS=true
                MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN=true
            """)
        )
        monkeypatch.chdir(tmp_path)
        settings = LocalSettings()
        assert settings.base_path == str(sandbox)
        assert settings.follow_symlinks is True
        assert settings.show_hidden is True

    def test_env_var_overrides_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables take precedence over .env file values."""
        env_file = tmp_path / "mamba.env"
        env_file.write_text("MAMBA_MCP_FS_SERVER_PORT=9999\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MAMBA_MCP_FS_SERVER_PORT", "7777")
        settings = ServerSettings()
        assert settings.server_port == 7777


# ---------------------------------------------------------------------------
# Extra SettingsConfigDict checks
# ---------------------------------------------------------------------------
class TestSettingsConfigDict:
    """All settings classes use SettingsConfigDict(env_file='mamba.env')."""

    def test_server_settings_env_file(self) -> None:
        assert ServerSettings.model_config["env_file"] == "mamba.env"

    def test_local_settings_env_file(self) -> None:
        assert LocalSettings.model_config["env_file"] == "mamba.env"

    def test_s3_settings_env_file(self) -> None:
        assert S3Settings.model_config["env_file"] == "mamba.env"

    def test_server_settings_env_prefix(self) -> None:
        assert ServerSettings.model_config["env_prefix"] == "MAMBA_MCP_FS_"

    def test_local_settings_env_prefix(self) -> None:
        assert LocalSettings.model_config["env_prefix"] == "MAMBA_MCP_FS_LOCAL_"

    def test_s3_settings_env_prefix(self) -> None:
        assert S3Settings.model_config["env_prefix"] == "MAMBA_MCP_FS_S3_"

    def test_server_settings_extra_ignore(self) -> None:
        assert ServerSettings.model_config["extra"] == "ignore"

    def test_local_settings_extra_ignore(self) -> None:
        assert LocalSettings.model_config["extra"] == "ignore"

    def test_s3_settings_extra_ignore(self) -> None:
        assert S3Settings.model_config["extra"] == "ignore"


# ---------------------------------------------------------------------------
# LocalSettings -- nonexistent base_path OK when disabled
# ---------------------------------------------------------------------------
class TestLocalSettingsDisabledBypass:
    """When enabled=False, base_path existence is not validated."""

    def test_nonexistent_base_path_ok_when_disabled(self) -> None:
        settings = LocalSettings(enabled=False, base_path="/nonexistent/path/that/does/not/exist")
        assert settings.base_path == "/nonexistent/path/that/does/not/exist"
        assert settings.enabled is False


# ---------------------------------------------------------------------------
# Root Settings class
# ---------------------------------------------------------------------------
class TestRootSettings:
    """Settings combines ServerSettings, LocalSettings, and S3Settings."""

    def test_creates_all_nested_settings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        settings = get_settings()
        assert isinstance(settings.server, ServerSettings)
        assert isinstance(settings.local, LocalSettings)
        assert isinstance(settings.s3, S3Settings)

    def test_server_defaults_accessible(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        settings = get_settings()
        assert settings.server.transport == "stdio"
        assert settings.server.read_only is True

    def test_local_defaults_accessible(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        settings = get_settings()
        assert settings.local.enabled is True
        assert settings.local.base_path == str(tmp_path)

    def test_s3_defaults_accessible(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MAMBA_MCP_FS_LOCAL_BASE_PATH", str(tmp_path))
        settings = get_settings()
        assert settings.s3.enabled is False
        assert settings.s3.region == "us-east-1"


# ---------------------------------------------------------------------------
# Env file path helpers
# ---------------------------------------------------------------------------
class TestEnvFilePathHelpers:
    """set_env_file_path and get_env_file_path manage module-level state."""

    def test_default_is_none(self) -> None:
        set_env_file_path(None)
        assert get_env_file_path() is None

    def test_set_and_get(self) -> None:
        set_env_file_path("/tmp/custom.env")
        assert get_env_file_path() == "/tmp/custom.env"
        set_env_file_path(None)

    def test_set_none_resets(self) -> None:
        set_env_file_path("/tmp/custom.env")
        set_env_file_path(None)
        assert get_env_file_path() is None

    def test_root_settings_uses_custom_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            f"MAMBA_MCP_FS_TRANSPORT=streamable-http\n"
            f"MAMBA_MCP_FS_LOCAL_BASE_PATH={sandbox}\n"
            f"MAMBA_MCP_FS_S3_ENABLED=true\n"
            f"MAMBA_MCP_FS_S3_BUCKET=custom-bucket\n"
        )
        set_env_file_path(str(env_file))
        try:
            settings = get_settings()
            assert settings.server.transport == "streamable-http"
            assert settings.local.base_path == str(sandbox)
            assert settings.s3.enabled is True
            assert settings.s3.bucket == "custom-bucket"
        finally:
            set_env_file_path(None)
