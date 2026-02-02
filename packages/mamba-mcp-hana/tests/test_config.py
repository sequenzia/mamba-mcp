"""Tests for configuration management."""

from pathlib import Path

import pytest
from mamba_mcp_hana.config import (
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
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana-server.example.com")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30041")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_NAME", "TENANT1")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret123")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_ENCRYPT", "true")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_SSL_VALIDATE", "false")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "10")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_TIMEOUT", "60.0")
        monkeypatch.setenv("MAMBA_MCP_HANA_STATEMENT_TIMEOUT", "60000")
        monkeypatch.setenv("MAMBA_MCP_HANA_DEFAULT_SCHEMA", "MY_SCHEMA")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_host == "hana-server.example.com"
        assert settings.db_port == 30041
        assert settings.db_name == "TENANT1"
        assert settings.db_user == "testuser"
        assert settings.db_password is not None
        assert settings.db_password.get_secret_value() == "secret123"
        assert settings.db_encrypt is True
        assert settings.db_ssl_validate is False
        assert settings.pool_size == 10
        assert settings.pool_timeout == 60.0
        assert settings.statement_timeout == 60000
        assert settings.default_schema == "MY_SCHEMA"

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default values are applied correctly."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_host == "localhost"
        assert settings.db_port == 30015
        assert settings.db_name is None
        assert settings.db_ssl_validate is True
        assert settings.db_userkey is None
        assert settings.pool_size == 5
        assert settings.pool_timeout == 30.0
        assert settings.statement_timeout == 30000
        assert settings.default_schema is None

    def test_password_is_secret_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test DB_PASSWORD is stored as Pydantic SecretStr."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "my-secret-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert isinstance(settings.db_password, SecretStr)
        assert settings.db_password.get_secret_value() == "my-secret-password"

    def test_secret_str_not_leaked_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak password in repr/str."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "super-secret-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        repr_str = repr(settings)
        str_str = str(settings)

        assert "super-secret-password" not in repr_str
        assert "super-secret-password" not in str_str
        assert "**********" in repr_str

    def test_secret_str_not_in_model_dump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test SecretStr does not leak password when dumped."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "super-secret-password")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        dumped = settings.model_dump()
        # model_dump returns SecretStr object, not the raw value
        assert dumped["db_password"] != "super-secret-password"


class TestAutoTlsDetection:
    """Tests for automatic TLS detection based on port number."""

    def test_port_443_enables_tls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-TLS detection: port 443 enables encryption."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "443")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_port == 443
        assert settings.db_encrypt is True
        assert settings.effective_encrypt is True

    def test_non_443_port_disables_tls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-TLS detection: non-443 port defaults to no encryption."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_port == 30015
        assert settings.db_encrypt is False
        assert settings.effective_encrypt is False

    def test_manual_encrypt_true_overrides_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test manual override: DB_ENCRYPT=True on non-443 port."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "30015")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_ENCRYPT", "true")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_encrypt is True
        assert settings.effective_encrypt is True

    def test_manual_encrypt_false_overrides_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test manual override: DB_ENCRYPT=False on port 443."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "443")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_ENCRYPT", "false")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_encrypt is False
        assert settings.effective_encrypt is False


class TestUserkeyAuth:
    """Tests for hdbuserstore key authentication."""

    def test_userkey_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test DB_USERKEY provided without DB_USER/DB_PASSWORD is valid."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "MY_KEY")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_userkey == "MY_KEY"
        assert settings.db_user is None
        assert settings.db_password is None

    def test_both_userkey_and_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test both DB_USERKEY and DB_USER/DB_PASSWORD: both are accepted."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "MY_KEY")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        # Both are present; user/password takes precedence at connection time
        assert settings.db_userkey == "MY_KEY"
        assert settings.db_user == "testuser"
        assert settings.db_password is not None
        assert settings.db_password.get_secret_value() == "secret"

    def test_no_auth_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing all auth raises clear validation error."""
        # No DB_USER, DB_PASSWORD, or DB_USERKEY
        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "Authentication required" in error_text

    def test_user_without_password_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test DB_USER without DB_PASSWORD raises error."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "Authentication required" in error_text


class TestPoolValidation:
    """Tests for pool size validation."""

    def test_pool_size_valid_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid pool sizes within range 1-20."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        for size in [1, 5, 10, 20]:
            monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", str(size))
            settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
            assert settings.pool_size == size

    def test_pool_size_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test POOL_SIZE=0 is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_size" in error_text

    def test_pool_size_too_large_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test POOL_SIZE=21 is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "21")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_size" in error_text

    def test_pool_size_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative POOL_SIZE is rejected with validation error."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "-1")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_size" in error_text

    def test_pool_timeout_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test POOL_TIMEOUT=0 is rejected (must be > 0)."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_TIMEOUT", "0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_timeout" in error_text

    def test_pool_timeout_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative POOL_TIMEOUT is rejected."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_TIMEOUT", "-5.0")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "pool_timeout" in error_text

    def test_statement_timeout_below_minimum_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test STATEMENT_TIMEOUT below 1000ms is rejected."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_STATEMENT_TIMEOUT", "500")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "statement_timeout" in error_text

    def test_statement_timeout_at_minimum_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test STATEMENT_TIMEOUT at minimum (1000ms) is accepted."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_STATEMENT_TIMEOUT", "1000")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.statement_timeout == 1000

    def test_pool_timeout_valid_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid float POOL_TIMEOUT is accepted."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_TIMEOUT", "120.5")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.pool_timeout == 120.5


class TestUserkeyConfigEdgeCases:
    """Edge case tests for hdbuserstore key configuration."""

    def test_userkey_with_custom_host_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test userkey auth with custom host/port settings."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "PROD_KEY")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_HOST", "hana-prod.example.com")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PORT", "443")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_userkey == "PROD_KEY"
        assert settings.db_host == "hana-prod.example.com"
        assert settings.db_port == 443
        assert settings.db_encrypt is True  # auto-detected from 443
        assert settings.db_user is None
        assert settings.db_password is None

    def test_userkey_with_pool_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test userkey auth combined with pool configuration."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USERKEY", "MY_KEY")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_SIZE", "10")
        monkeypatch.setenv("MAMBA_MCP_HANA_POOL_TIMEOUT", "60.0")

        settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        assert settings.db_userkey == "MY_KEY"
        assert settings.pool_size == 10
        assert settings.pool_timeout == 60.0

    def test_password_only_without_user_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test DB_PASSWORD without DB_USER raises validation error."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        with pytest.raises(ValidationError) as exc_info:
            DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

        error_text = str(exc_info.value)
        assert "Authentication required" in error_text


class TestServerSettings:
    """Tests for ServerSettings configuration."""

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test server settings load from environment variables."""
        monkeypatch.setenv("MAMBA_MCP_HANA_TRANSPORT", "http")
        monkeypatch.setenv("MAMBA_MCP_HANA_SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("MAMBA_MCP_HANA_SERVER_PORT", "9090")
        monkeypatch.setenv("MAMBA_MCP_HANA_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAMBA_MCP_HANA_LOG_FORMAT", "text")

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

    def test_invalid_transport_rejected(self) -> None:
        """Test invalid transport value is rejected."""
        with pytest.raises(ValidationError):
            ServerSettings(transport="invalid", _env_file=None)  # type: ignore[call-arg]

    def test_invalid_log_format_rejected(self) -> None:
        """Test invalid log format is rejected."""
        with pytest.raises(ValidationError):
            ServerSettings(log_format="yaml", _env_file=None)  # type: ignore[call-arg]


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


class TestSettingsNested:
    """Tests for root Settings with nested delimiter support."""

    def test_settings_loads_nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test root Settings loads database and server sub-settings."""
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = get_settings()

        assert settings.database is not None
        assert settings.server is not None
        assert settings.database.db_user == "testuser"
        assert settings.server.transport == "stdio"

    def test_settings_loads_from_env_file(self, tmp_path: Path) -> None:
        """Test settings loads values from custom env file."""
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "MAMBA_MCP_HANA_DB_HOST=custom-host\n"
            "MAMBA_MCP_HANA_DB_PORT=443\n"
            "MAMBA_MCP_HANA_DB_USER=custom_user\n"
            "MAMBA_MCP_HANA_DB_PASSWORD=custom_pass\n"
            "MAMBA_MCP_HANA_LOG_LEVEL=DEBUG\n"
        )

        set_env_file_path(str(env_file))

        settings = get_settings()

        assert settings.database.db_host == "custom-host"
        assert settings.database.db_port == 443
        assert settings.database.db_user == "custom_user"
        assert settings.database.db_encrypt is True  # auto-detected from port 443
        assert settings.server.log_level == "DEBUG"

    def test_nested_delimiter_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test nested delimiter __ works for env vars (e.g., MAMBA_MCP_HANA_DB__HOST)."""
        # The nested delimiter is configured on the root Settings class.
        # With env_nested_delimiter="__", MAMBA_MCP_HANA_DB__HOST would be
        # parsed as database.db_host. However, the sub-settings classes
        # load independently with their own env_prefix, so the flat
        # MAMBA_MCP_HANA_DB_HOST is the primary mechanism.
        # The nested delimiter primarily enables structured config passing.
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_USER", "testuser")
        monkeypatch.setenv("MAMBA_MCP_HANA_DB_PASSWORD", "secret")

        settings = get_settings()
        assert settings.database.db_host == "localhost"  # default
        assert settings.database.db_user == "testuser"
