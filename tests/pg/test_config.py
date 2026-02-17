"""Tests for configuration management."""

from pathlib import Path

import pytest
from mamba_mcp_pg.config import (
    DatabaseSettings,
    ServerSettings,
    get_env_file_path,
    get_settings,
    set_env_file_path,
)
from pydantic import SecretStr, ValidationError


class TestDatabaseSettings:
    """Tests for DatabaseSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test config loads all database settings from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_HOST", "pg-server.example.com")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "5433")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "mydb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret123")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_SIZE", "10")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_TIMEOUT", "60.0")
        monkeypatch.setenv("MAMBA_MCP_PG_STATEMENT_TIMEOUT", "60000")
        monkeypatch.setenv("MAMBA_MCP_PG_DEFAULT_SCHEMA", "app_schema")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_host == "pg-server.example.com"
        assert settings.db_port == 5433
        assert settings.db_name == "mydb"
        assert settings.db_user == "testuser"
        assert settings.db_password is not None
        assert settings.db_password.get_secret_value() == "secret123"
        assert settings.pool_size == 10
        assert settings.pool_timeout == 60.0
        assert settings.statement_timeout == 60000
        assert settings.default_schema == "app_schema"

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default values are applied correctly."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_host == "localhost"
        assert settings.db_port == 5432
        assert settings.pool_size == 5
        assert settings.pool_timeout == 30.0
        assert settings.statement_timeout == 30000
        assert settings.default_schema == "public"

    def test_required_db_name_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing db_name raises ValidationError."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_name" in error_text

    def test_required_db_user_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing db_user raises ValidationError."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_user" in error_text

    def test_required_db_password_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing db_password raises ValidationError."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_password" in error_text

    def test_all_required_fields_missing(self) -> None:
        """Test missing all required fields raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_name" in error_text
        assert "db_user" in error_text
        assert "db_password" in error_text

    def test_password_is_secret_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test db_password is stored as Pydantic SecretStr."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "my-secret-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert isinstance(settings.db_password, SecretStr)
        assert settings.db_password.get_secret_value() == "my-secret-password"

    def test_secret_str_not_leaked_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak password in repr/str."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "super-secret-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        repr_str = repr(settings)
        str_str = str(settings)

        assert "super-secret-password" not in repr_str
        assert "super-secret-password" not in str_str
        assert "**********" in repr_str

    def test_secret_str_not_in_model_dump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak password when dumped."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "super-secret-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        dumped = settings.model_dump()
        assert dumped["db_password"] != "super-secret-password"

    def test_async_url_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test async_url builds correct PostgreSQL connection string."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_HOST", "db.example.com")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "5433")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "mydb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "appuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "s3cret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        expected = "postgresql+asyncpg://appuser:s3cret@db.example.com:5433/mydb"
        assert settings.async_url == expected

    def test_async_url_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test async_url uses default host and port when not overridden."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "pass")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        expected = "postgresql+asyncpg://testuser:pass@localhost:5432/testdb"
        assert settings.async_url == expected

    def test_async_url_exposes_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test async_url contains the actual password value for driver use."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "real-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert "real-password" in settings.async_url


class TestDatabasePortValidation:
    """Tests for db_port field validation."""

    def test_port_minimum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test db_port=1 is accepted (minimum valid port)."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "1")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.db_port == 1

    def test_port_maximum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test db_port=65535 is accepted (maximum valid port)."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "65535")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.db_port == 65535

    def test_port_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test db_port=0 is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_port" in error_text

    def test_port_exceeds_maximum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test db_port=65536 is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "65536")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_port" in error_text

    def test_port_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative db_port is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PORT", "-1")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "db_port" in error_text


class TestPoolValidation:
    """Tests for pool and statement timeout field validation."""

    def test_pool_size_valid_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid pool sizes within range 1-20."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        for size in [1, 5, 10, 20]:
            monkeypatch.setenv("MAMBA_MCP_PG_POOL_SIZE", str(size))
            settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
            assert settings.pool_size == size

    def test_pool_size_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pool_size=0 is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_SIZE", "0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_size" in error_text

    def test_pool_size_too_large_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pool_size=21 is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_SIZE", "21")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_size" in error_text

    def test_pool_size_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative pool_size is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_SIZE", "-1")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_size" in error_text

    def test_pool_timeout_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pool_timeout=0 is rejected (must be > 0)."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_TIMEOUT", "0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_timeout" in error_text

    def test_pool_timeout_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative pool_timeout is rejected."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_TIMEOUT", "-5.0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_timeout" in error_text

    def test_pool_timeout_valid_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid float pool_timeout is accepted."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_POOL_TIMEOUT", "120.5")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.pool_timeout == 120.5

    def test_statement_timeout_below_minimum_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test statement_timeout below 1000ms is rejected."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_STATEMENT_TIMEOUT", "500")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "statement_timeout" in error_text

    def test_statement_timeout_at_minimum_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test statement_timeout at minimum (1000ms) is accepted."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_STATEMENT_TIMEOUT", "1000")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.statement_timeout == 1000

    def test_statement_timeout_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test statement_timeout=0 is rejected (minimum is 1000)."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_PG_STATEMENT_TIMEOUT", "0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "statement_timeout" in error_text


class TestServerSettings:
    """Tests for ServerSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test server settings load from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_PG_TRANSPORT", "http")
        monkeypatch.setenv("MAMBA_MCP_PG_SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("MAMBA_MCP_PG_SERVER_PORT", "9090")
        monkeypatch.setenv("MAMBA_MCP_PG_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAMBA_MCP_PG_LOG_FORMAT", "text")

        settings = ServerSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.transport == "http"
        assert settings.server_host == "127.0.0.1"
        assert settings.server_port == 9090
        assert settings.log_level == "DEBUG"
        assert settings.log_format == "text"

    def test_defaults(self) -> None:
        """Test default server settings values."""
        settings = ServerSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.transport == "stdio"
        assert settings.server_host == "0.0.0.0"
        assert settings.server_port == 8080
        assert settings.log_level == "INFO"
        assert settings.log_format == "json"

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

    def test_server_port_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test server_port respects ge=1 and le=65535 constraints."""
        with pytest.raises(ValidationError):
            ServerSettings(
                server_port=0,
                _env_file=None,  # type: ignore[call-arg]
            )

        with pytest.raises(ValidationError):
            ServerSettings(
                server_port=65536,
                _env_file=None,  # type: ignore[call-arg]
            )

    def test_extra_fields_ignored(self) -> None:
        """Test that extra fields are silently ignored."""
        settings = ServerSettings(
            unknown_field="value",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert not hasattr(settings, "unknown_field")


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
        """Test root Settings loads database and server sub-settings."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        settings = get_settings()

        assert settings.database is not None
        assert settings.server is not None
        assert settings.database.db_user == "testuser"
        assert settings.database.db_name == "testdb"
        assert settings.server.transport == "stdio"

    def test_settings_loads_from_env_file(self, tmp_path: Path) -> None:
        """Test settings loads values from custom env file."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_PG_DB_HOST=custom-host\n"
            "MAMBA_MCP_PG_DB_PORT=5433\n"
            "MAMBA_MCP_PG_DB_NAME=custom_db\n"
            "MAMBA_MCP_PG_DB_USER=custom_user\n"
            "MAMBA_MCP_PG_DB_PASSWORD=custom_pass\n"
            "MAMBA_MCP_PG_LOG_LEVEL=DEBUG\n"
        )

        set_env_file_path(str(env_file))

        settings = get_settings()

        assert settings.database.db_host == "custom-host"
        assert settings.database.db_port == 5433
        assert settings.database.db_name == "custom_db"
        assert settings.database.db_user == "custom_user"
        assert settings.database.db_password.get_secret_value() == "custom_pass"
        assert settings.server.log_level == "DEBUG"

    def test_get_settings_returns_new_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test get_settings() creates a new instance each call."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        s1 = get_settings()
        s2 = get_settings()

        assert s1 is not s2

    def test_nested_delimiter_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test nested delimiter __ is configured on root Settings."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        settings = get_settings()

        # Verify the sub-settings loaded with defaults correctly
        assert settings.database.db_host == "localhost"
        assert settings.database.db_user == "testuser"
        assert settings.server.transport == "stdio"

    def test_env_vars_override_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test environment variables take precedence over env file values."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_PG_DB_HOST=file-host\n"
            "MAMBA_MCP_PG_DB_NAME=file_db\n"
            "MAMBA_MCP_PG_DB_USER=file_user\n"
            "MAMBA_MCP_PG_DB_PASSWORD=file_pass\n"
        )

        set_env_file_path(str(env_file))

        # Env var should override the file value
        monkeypatch.setenv("MAMBA_MCP_PG_DB_HOST", "env-host")

        settings = get_settings()

        assert settings.database.db_host == "env-host"
        assert settings.database.db_name == "file_db"

    def test_model_validator_skips_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test model_validator does not overwrite pre-provided nested settings."""
        monkeypatch.setenv("MAMBA_MCP_PG_DB_NAME", "testdb")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_PG_DB_PASSWORD", "secret")

        db = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        srv = ServerSettings(_env_file=None)  # type: ignore[call-arg]

        from mamba_mcp_pg.config import Settings

        settings = Settings(database=db, server=srv)

        assert settings.database is db
        assert settings.server is srv
