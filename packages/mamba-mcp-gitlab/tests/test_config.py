"""Tests for configuration management."""

from pathlib import Path

import mamba_mcp_gitlab
import pytest
from mamba_mcp_gitlab.config import (
    GitLabSettings,
    OAuthSettings,
    RateLimitSettings,
    ServerSettings,
    Settings,
    get_env_file_path,
    get_settings,
    set_env_file_path,
)
from pydantic import SecretStr, ValidationError


class TestPackageImport:
    """Tests for package import and metadata."""

    def test_package_imports(self) -> None:
        """Test that the mamba_mcp_gitlab package can be imported."""
        assert mamba_mcp_gitlab is not None

    def test_version_defined(self) -> None:
        """Test that __version__ is defined."""
        assert hasattr(mamba_mcp_gitlab, "__version__")
        assert mamba_mcp_gitlab.__version__ == "0.1.0"


class TestGitLabSettings:
    """Tests for GitLabSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test config loads all GitLab settings from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-xxxxxxxxxxxxxxxxxxxx")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_VERIFY_SSL", "false")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_DEFAULT_PROJECT_ID", "42")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_DEFAULT_GROUP_ID", "7")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_READ_ONLY", "true")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.url == "https://gitlab.example.com"
        assert settings.token is not None
        assert settings.token.get_secret_value() == "glpat-xxxxxxxxxxxxxxxxxxxx"
        assert settings.verify_ssl is False
        assert settings.default_project_id == 42
        assert settings.default_group_id == 7
        assert settings.read_only is True

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default values are applied correctly."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.url == "https://gitlab.example.com"
        assert settings.token is None
        assert settings.verify_ssl is True
        assert settings.default_project_id is None
        assert settings.default_group_id is None
        assert settings.read_only is False

    def test_required_url_missing(self) -> None:
        """Test missing url raises clear ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "url" in error_text

    def test_empty_url_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty string url raises ValidationError."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "")

        with pytest.raises(ValidationError) as exc_info:
            GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "url" in error_text

    def test_whitespace_url_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test whitespace-only url raises ValidationError."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "   ")

        with pytest.raises(ValidationError) as exc_info:
            GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "url" in error_text

    def test_token_is_secret_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test token is stored as Pydantic SecretStr."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-my-secret-token")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        assert isinstance(settings.token, SecretStr)
        assert settings.token.get_secret_value() == "glpat-my-secret-token"

    def test_secret_str_not_leaked_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak token in repr/str."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-super-secret-token")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        repr_str = repr(settings)
        str_str = str(settings)

        assert "glpat-super-secret-token" not in repr_str
        assert "glpat-super-secret-token" not in str_str
        assert "**********" in repr_str

    def test_secret_str_not_in_model_dump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak token when dumped."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-super-secret-token")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        dumped = settings.model_dump()
        assert dumped["token"] != "glpat-super-secret-token"

    def test_empty_project_id_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty string DEFAULT_PROJECT_ID is treated as None."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_DEFAULT_PROJECT_ID", "")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.default_project_id is None

    def test_empty_group_id_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty string DEFAULT_GROUP_ID is treated as None."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_DEFAULT_GROUP_ID", "")

        settings = GitLabSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.default_group_id is None

    def test_extra_fields_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that extra fields are silently ignored."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")

        settings = GitLabSettings(
            url="https://gitlab.example.com",
            unknown_field="value",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert not hasattr(settings, "unknown_field")


class TestOAuthSettings:
    """Tests for OAuthSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test OAuth settings load from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID", "my-client-id")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET", "my-client-secret")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_REDIRECT_URI", "http://localhost:8080/callback")

        settings = OAuthSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.client_id == "my-client-id"
        assert settings.client_secret is not None
        assert settings.client_secret.get_secret_value() == "my-client-secret"
        assert settings.redirect_uri == "http://localhost:8080/callback"

    def test_defaults(self) -> None:
        """Test default OAuth settings values."""
        settings = OAuthSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.client_id is None
        assert settings.client_secret is None
        assert settings.redirect_uri is None

    def test_client_secret_is_secret_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test client_secret is stored as Pydantic SecretStr."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET", "super-secret")

        settings = OAuthSettings(_env_file=None)  # type: ignore[call-arg]

        assert isinstance(settings.client_secret, SecretStr)
        assert settings.client_secret.get_secret_value() == "super-secret"

    def test_client_secret_not_leaked_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak client_secret in repr/str."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET", "super-secret-value")

        settings = OAuthSettings(_env_file=None)  # type: ignore[call-arg]

        repr_str = repr(settings)
        str_str = str(settings)

        assert "super-secret-value" not in repr_str
        assert "super-secret-value" not in str_str
        assert "**********" in repr_str

    def test_empty_client_id_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty string CLIENT_ID is treated as None."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID", "")

        settings = OAuthSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.client_id is None

    def test_empty_redirect_uri_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty string REDIRECT_URI is treated as None."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_REDIRECT_URI", "")

        settings = OAuthSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.redirect_uri is None


class TestServerSettings:
    """Tests for ServerSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test server settings load from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_TRANSPORT", "http")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_SERVER_HOST", "0.0.0.0")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_SERVER_PORT", "9090")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_LOG_FORMAT", "json")

        settings = ServerSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.transport == "http"
        assert settings.server_host == "0.0.0.0"
        assert settings.server_port == 9090
        assert settings.log_level == "DEBUG"
        assert settings.log_format == "json"

    def test_defaults(self) -> None:
        """Test default server settings values."""
        settings = ServerSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.transport == "stdio"
        assert settings.server_host == "127.0.0.1"
        assert settings.server_port == 8004
        assert settings.log_level == "INFO"
        assert settings.log_format == "text"

    def test_transport_stdio_accepted(self) -> None:
        """Test transport='stdio' is valid."""
        settings = ServerSettings(transport="stdio", _env_file=None)  # type: ignore[call-arg]
        assert settings.transport == "stdio"

    def test_transport_http_accepted(self) -> None:
        """Test transport='http' is valid."""
        settings = ServerSettings(transport="http", _env_file=None)  # type: ignore[call-arg]
        assert settings.transport == "http"

    def test_transport_streamable_http_accepted(self) -> None:
        """Test transport='streamable-http' is valid."""
        settings = ServerSettings(
            transport="streamable-http",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert settings.transport == "streamable-http"

    def test_invalid_transport_rejected(self) -> None:
        """Test invalid transport value is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings(transport="invalid", _env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "transport" in error_text

    def test_transport_sse_rejected(self) -> None:
        """Test transport='sse' is rejected (not in pattern)."""
        with pytest.raises(ValidationError):
            ServerSettings(transport="sse", _env_file=None)  # type: ignore[call-arg]

    def test_invalid_log_format_rejected(self) -> None:
        """Test invalid log format is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings(log_format="yaml", _env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "log_format" in error_text

    def test_log_format_json_accepted(self) -> None:
        """Test log_format='json' is valid."""
        settings = ServerSettings(log_format="json", _env_file=None)  # type: ignore[call-arg]
        assert settings.log_format == "json"

    def test_log_format_text_accepted(self) -> None:
        """Test log_format='text' is valid."""
        settings = ServerSettings(log_format="text", _env_file=None)  # type: ignore[call-arg]
        assert settings.log_format == "text"

    def test_extra_fields_ignored(self) -> None:
        """Test that extra fields are silently ignored."""
        settings = ServerSettings(
            unknown_field="value",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert not hasattr(settings, "unknown_field")


class TestServerPortValidation:
    """Tests for server_port field validation."""

    def test_port_minimum_boundary(self) -> None:
        """Test server_port=1 is accepted (minimum valid port)."""
        settings = ServerSettings(
            server_port=1,
            _env_file=None,  # type: ignore[call-arg]
        )
        assert settings.server_port == 1

    def test_port_maximum_boundary(self) -> None:
        """Test server_port=65535 is accepted (maximum valid port)."""
        settings = ServerSettings(
            server_port=65535,
            _env_file=None,  # type: ignore[call-arg]
        )
        assert settings.server_port == 65535

    def test_port_zero_rejected(self) -> None:
        """Test server_port=0 is rejected with validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings(
                server_port=0,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "server_port" in error_text

    def test_port_exceeds_maximum_rejected(self) -> None:
        """Test server_port=65536 is rejected with validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings(
                server_port=65536,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "server_port" in error_text

    def test_port_negative_rejected(self) -> None:
        """Test negative server_port is rejected with validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServerSettings(
                server_port=-1,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "server_port" in error_text


class TestRateLimitSettings:
    """Tests for RateLimitSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test rate limit settings load from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_RATE_LIMIT_MAX_REQUESTS", "200")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_RATE_LIMIT_WINDOW_SECONDS", "120")

        settings = RateLimitSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.max_requests == 200
        assert settings.window_seconds == 120

    def test_defaults(self) -> None:
        """Test default rate limit settings values."""
        settings = RateLimitSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.max_requests == 100
        assert settings.window_seconds == 60

    def test_max_requests_zero_rejected(self) -> None:
        """Test max_requests=0 is rejected (must be >= 1)."""
        with pytest.raises(ValidationError) as exc_info:
            RateLimitSettings(
                max_requests=0,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "max_requests" in error_text

    def test_max_requests_negative_rejected(self) -> None:
        """Test negative max_requests is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RateLimitSettings(
                max_requests=-1,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "max_requests" in error_text

    def test_window_seconds_zero_rejected(self) -> None:
        """Test window_seconds=0 is rejected (must be >= 1)."""
        with pytest.raises(ValidationError) as exc_info:
            RateLimitSettings(
                window_seconds=0,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "window_seconds" in error_text

    def test_window_seconds_negative_rejected(self) -> None:
        """Test negative window_seconds is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RateLimitSettings(
                window_seconds=-1,
                _env_file=None,  # type: ignore[call-arg]
            )

        error_text = str(exc_info.value)
        assert "window_seconds" in error_text


class TestEnvFilePathState:
    """Tests for module-level env file path state management."""

    def test_default_is_none(self) -> None:
        """Test default env file path is None."""
        set_env_file_path(None)
        assert get_env_file_path() is None

    def test_set_and_get(self) -> None:
        """Test setting and getting env file path."""
        test_path = "/custom/path/to/.env"
        set_env_file_path(test_path)
        assert get_env_file_path() == test_path

    def test_reset_to_none(self) -> None:
        """Test setting env file path back to None."""
        set_env_file_path("/some/path")
        set_env_file_path(None)
        assert get_env_file_path() is None

    def test_overwrite_existing_path(self) -> None:
        """Test overwriting a previously set env file path."""
        set_env_file_path("/first/path")
        set_env_file_path("/second/path")
        assert get_env_file_path() == "/second/path"


class TestSettingsNested:
    """Tests for root Settings with nested delimiter support."""

    def test_settings_loads_nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test root Settings loads all nested sub-settings."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-test-token")

        settings = get_settings()

        assert settings.gitlab is not None
        assert settings.oauth is not None
        assert settings.server is not None
        assert settings.rate_limit is not None
        assert settings.gitlab.url == "https://gitlab.example.com"
        assert settings.gitlab.token is not None
        assert settings.gitlab.token.get_secret_value() == "glpat-test-token"
        assert settings.server.transport == "stdio"
        assert settings.rate_limit.max_requests == 100

    def test_settings_loads_from_env_file(self, tmp_path: Path) -> None:
        """Test settings loads values from custom env file."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://custom-gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-file-token\n"
            "MAMBA_MCP_GITLAB_VERIFY_SSL=false\n"
            "MAMBA_MCP_GITLAB_READ_ONLY=true\n"
            "MAMBA_MCP_GITLAB_SERVER_LOG_LEVEL=DEBUG\n"
            "MAMBA_MCP_GITLAB_RATE_LIMIT_MAX_REQUESTS=50\n"
        )

        set_env_file_path(str(env_file))

        settings = get_settings()

        assert settings.gitlab.url == "https://custom-gitlab.example.com"
        assert settings.gitlab.token is not None
        assert settings.gitlab.token.get_secret_value() == "glpat-file-token"
        assert settings.gitlab.verify_ssl is False
        assert settings.gitlab.read_only is True
        assert settings.server.log_level == "DEBUG"
        assert settings.rate_limit.max_requests == 50

    def test_get_settings_returns_new_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test get_settings() creates a new instance each call."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")

        s1 = get_settings()
        s2 = get_settings()

        assert s1 is not s2

    def test_nested_delimiter_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test nested delimiter __ is configured on root Settings."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")

        settings = get_settings()

        assert settings.gitlab.url == "https://gitlab.example.com"
        assert settings.server.transport == "stdio"
        assert settings.rate_limit.max_requests == 100

    def test_env_vars_override_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test environment variables take precedence over env file values."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_GITLAB_URL=https://file-gitlab.example.com\n"
            "MAMBA_MCP_GITLAB_TOKEN=glpat-file-token\n"
        )

        set_env_file_path(str(env_file))

        # Env var should override the file value
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://env-gitlab.example.com")

        settings = get_settings()

        assert settings.gitlab.url == "https://env-gitlab.example.com"
        assert settings.gitlab.token is not None
        assert settings.gitlab.token.get_secret_value() == "glpat-file-token"

    def test_model_validator_skips_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test model_validator does not overwrite pre-provided nested settings."""
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")

        gl = GitLabSettings(_env_file=None)  # type: ignore[call-arg]
        oauth = OAuthSettings(_env_file=None)  # type: ignore[call-arg]
        srv = ServerSettings(_env_file=None)  # type: ignore[call-arg]
        rl = RateLimitSettings(_env_file=None)  # type: ignore[call-arg]

        settings = Settings(gitlab=gl, oauth=oauth, server=srv, rate_limit=rl)

        assert settings.gitlab is gl
        assert settings.oauth is oauth
        assert settings.server is srv
        assert settings.rate_limit is rl

    def test_settings_with_all_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test settings load with all environment variables set."""
        # GitLab settings
        monkeypatch.setenv("MAMBA_MCP_GITLAB_URL", "https://gitlab.example.com")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_TOKEN", "glpat-full-test")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_VERIFY_SSL", "false")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_DEFAULT_PROJECT_ID", "42")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_DEFAULT_GROUP_ID", "7")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_READ_ONLY", "true")

        # OAuth settings
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID", "oauth-id")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET", "oauth-secret")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_OAUTH_REDIRECT_URI", "http://localhost/cb")

        # Server settings
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_TRANSPORT", "http")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_SERVER_HOST", "0.0.0.0")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_SERVER_PORT", "9000")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_SERVER_LOG_FORMAT", "json")

        # Rate limit settings
        monkeypatch.setenv("MAMBA_MCP_GITLAB_RATE_LIMIT_MAX_REQUESTS", "200")
        monkeypatch.setenv("MAMBA_MCP_GITLAB_RATE_LIMIT_WINDOW_SECONDS", "120")

        settings = get_settings()

        # Verify GitLab
        assert settings.gitlab.url == "https://gitlab.example.com"
        assert settings.gitlab.token is not None
        assert settings.gitlab.token.get_secret_value() == "glpat-full-test"
        assert settings.gitlab.verify_ssl is False
        assert settings.gitlab.default_project_id == 42
        assert settings.gitlab.default_group_id == 7
        assert settings.gitlab.read_only is True

        # Verify OAuth
        assert settings.oauth.client_id == "oauth-id"
        assert settings.oauth.client_secret is not None
        assert settings.oauth.client_secret.get_secret_value() == "oauth-secret"
        assert settings.oauth.redirect_uri == "http://localhost/cb"

        # Verify Server
        assert settings.server.transport == "http"
        assert settings.server.server_host == "0.0.0.0"
        assert settings.server.server_port == 9000
        assert settings.server.log_level == "DEBUG"
        assert settings.server.log_format == "json"

        # Verify Rate Limit
        assert settings.rate_limit.max_requests == 200
        assert settings.rate_limit.window_seconds == 120
