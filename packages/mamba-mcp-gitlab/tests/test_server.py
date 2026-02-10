"""Tests for the MCP server core module."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
from mamba_mcp_gitlab.auth import AuthenticationError, AuthInfo
from mamba_mcp_gitlab.config import (
    GitLabSettings,
    OAuthSettings,
    RateLimitSettings,
    ServerSettings,
    Settings,
)
from mamba_mcp_gitlab.rate_limit import RateLimiter
from mamba_mcp_gitlab.server import AppContext, app_lifespan, mcp
from mcp.server.fastmcp import FastMCP
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    url: str = "https://gitlab.example.com",
    token: str = "glpat-xxxxxxxxxxxxxxxxxxxx",
    verify_ssl: bool = True,
    read_only: bool = False,
    max_connections: int = 10,
) -> Settings:
    """Create a Settings instance for testing."""
    gitlab = GitLabSettings(
        url=url,
        token=SecretStr(token),
        verify_ssl=verify_ssl,
        read_only=read_only,
        _env_file=None,  # type: ignore[call-arg]
    )
    server = ServerSettings(
        max_connections=max_connections,
        _env_file=None,  # type: ignore[call-arg]
    )
    return Settings(
        gitlab=gitlab,
        oauth=OAuthSettings(_env_file=None),  # type: ignore[call-arg]
        server=server,
        rate_limit=RateLimitSettings(_env_file=None),  # type: ignore[call-arg]
    )


def _make_auth_info(
    *,
    username: str = "testuser",
    scopes: list[str] | None = None,
) -> AuthInfo:
    """Create an AuthInfo instance for testing."""
    return AuthInfo(
        auth_type="pat",
        username=username,
        scopes=scopes if scopes is not None else ["api"],
        expires_at="2027-12-31",
    )


def _mock_token_response(
    *,
    active: bool = True,
    revoked: bool = False,
    scopes: list[str] | None = None,
    username: str = "testuser",
    expires_at: str | None = "2027-12-31",
) -> dict:
    """Build a mock /api/v4/personal_access_tokens/self response body."""
    return {
        "id": 1,
        "name": "test-token",
        "revoked": revoked,
        "active": active,
        "scopes": scopes if scopes is not None else ["api"],
        "user": {"username": username, "id": 42},
        "expires_at": expires_at,
    }


def _make_mock_transport(
    *,
    status_code: int = 200,
    json_data: dict | None = None,
    raise_error: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Create an httpx MockTransport that returns a fixed response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error is not None:
            raise raise_error("connection failed")
        return httpx.Response(
            status_code=status_code,
            json=json_data or _mock_token_response(),
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# AppContext Dataclass
# ---------------------------------------------------------------------------


class TestAppContext:
    """Tests for the AppContext dataclass."""

    def test_holds_all_required_fields(self) -> None:
        """Test that AppContext has client, settings, rate_limiter, and auth_info fields."""
        settings = _make_settings()
        auth_info = _make_auth_info()
        client = httpx.AsyncClient()
        limiter = RateLimiter(max_requests=100, window_seconds=60)

        ctx = AppContext(
            client=client,
            settings=settings,
            rate_limiter=limiter,
            auth_info=auth_info,
        )

        assert ctx.client is client
        assert ctx.settings is settings
        assert ctx.rate_limiter is limiter
        assert ctx.auth_info is auth_info

    def test_client_is_httpx_async_client(self) -> None:
        """Test that the client field holds an httpx.AsyncClient."""
        client = httpx.AsyncClient()
        limiter = RateLimiter(max_requests=0)
        ctx = AppContext(
            client=client,
            settings=_make_settings(),
            rate_limiter=limiter,
            auth_info=_make_auth_info(),
        )
        assert isinstance(ctx.client, httpx.AsyncClient)

    def test_settings_is_settings_instance(self) -> None:
        """Test that the settings field holds a Settings instance."""
        settings = _make_settings()
        limiter = RateLimiter(max_requests=0)
        ctx = AppContext(
            client=httpx.AsyncClient(),
            settings=settings,
            rate_limiter=limiter,
            auth_info=_make_auth_info(),
        )
        assert isinstance(ctx.settings, Settings)

    def test_auth_info_is_auth_info_instance(self) -> None:
        """Test that the auth_info field holds an AuthInfo instance."""
        auth_info = _make_auth_info()
        limiter = RateLimiter(max_requests=0)
        ctx = AppContext(
            client=httpx.AsyncClient(),
            settings=_make_settings(),
            rate_limiter=limiter,
            auth_info=auth_info,
        )
        assert isinstance(ctx.auth_info, AuthInfo)

    def test_rate_limiter_is_rate_limiter_instance(self) -> None:
        """Test that rate_limiter holds a RateLimiter instance."""
        limiter = RateLimiter(max_requests=100, window_seconds=60)
        ctx = AppContext(
            client=httpx.AsyncClient(),
            settings=_make_settings(),
            rate_limiter=limiter,
            auth_info=_make_auth_info(),
        )
        assert isinstance(ctx.rate_limiter, RateLimiter)
        assert ctx.rate_limiter.max_requests == 100

    def test_rate_limiter_disabled_when_zero(self) -> None:
        """Test that rate_limiter is disabled when max_requests=0."""
        limiter = RateLimiter(max_requests=0)
        ctx = AppContext(
            client=httpx.AsyncClient(),
            settings=_make_settings(),
            rate_limiter=limiter,
            auth_info=_make_auth_info(),
        )
        assert ctx.rate_limiter.enabled is False


# ---------------------------------------------------------------------------
# app_lifespan - Success Path
# ---------------------------------------------------------------------------


class TestAppLifespanSuccess:
    """Tests for app_lifespan with successful authentication."""

    async def test_creates_httpx_client(self) -> None:
        """Test that app_lifespan creates an httpx.AsyncClient."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert isinstance(ctx.client, httpx.AsyncClient)

    async def test_base_url_set_correctly(self) -> None:
        """Test that httpx client has the correct base_url from settings."""
        settings = _make_settings(url="https://my-gitlab.corp.com/")

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                # Base URL should have trailing slash stripped
                base_url = str(ctx.client.base_url)
                assert "my-gitlab.corp.com" in base_url

    async def test_auth_headers_applied(self) -> None:
        """Test that auth headers from the strategy are applied to the client."""
        settings = _make_settings(token="glpat-test-auth-header")

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.client.headers.get("private-token") == "glpat-test-auth-header"

    async def test_connection_limits_configured(self) -> None:
        """Test that connection pool limits are set from settings."""
        settings = _make_settings(max_connections=5)
        created_limits: list[httpx.Limits] = []

        original_init = httpx.AsyncClient.__init__

        def capture_limits(self, *args, **kwargs):
            if "limits" in kwargs:
                created_limits.append(kwargs["limits"])
            return original_init(self, *args, **kwargs)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
            patch.object(httpx.AsyncClient, "__init__", capture_limits),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as _ctx:
                assert len(created_limits) == 1
                assert created_limits[0].max_connections == 5
                assert created_limits[0].max_keepalive_connections == 5

    async def test_default_connection_limit_is_10(self) -> None:
        """Test that the default max_connections is 10."""
        settings = _make_settings()
        assert settings.server.max_connections == 10

        created_limits: list[httpx.Limits] = []

        original_init = httpx.AsyncClient.__init__

        def capture_limits(self, *args, **kwargs):
            if "limits" in kwargs:
                created_limits.append(kwargs["limits"])
            return original_init(self, *args, **kwargs)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
            patch.object(httpx.AsyncClient, "__init__", capture_limits),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as _ctx:
                assert len(created_limits) == 1
                assert created_limits[0].max_connections == 10

    async def test_verify_ssl_true_by_default(self) -> None:
        """Test that SSL verification is enabled by default."""
        settings = _make_settings(verify_ssl=True)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                # httpx stores verify in _transport._pool._ssl_context
                # We verify by checking the settings were passed correctly
                assert ctx.settings.gitlab.verify_ssl is True

    async def test_auth_validation_runs_before_yield(self) -> None:
        """Test that auth validation runs before yielding the context."""
        settings = _make_settings()
        validate_called = False
        original_auth_info = _make_auth_info()

        async def mock_validate(self, client):
            nonlocal validate_called
            validate_called = True
            return original_auth_info

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                side_effect=mock_validate,
                autospec=True,
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert validate_called
                assert ctx.auth_info is original_auth_info

    async def test_yields_app_context(self) -> None:
        """Test that app_lifespan yields an AppContext instance."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert isinstance(ctx, AppContext)

    async def test_settings_preserved_in_context(self) -> None:
        """Test that the settings are preserved in the yielded context."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings is settings

    async def test_rate_limiter_initialized_from_settings(self) -> None:
        """Test that the rate limiter is initialized from RateLimitSettings."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert isinstance(ctx.rate_limiter, RateLimiter)
                assert ctx.rate_limiter.max_requests == settings.rate_limit.max_requests
                assert ctx.rate_limiter.window_seconds == settings.rate_limit.window_seconds
                assert ctx.rate_limiter.enabled is True


# ---------------------------------------------------------------------------
# app_lifespan - Client Cleanup
# ---------------------------------------------------------------------------


class TestAppLifespanCleanup:
    """Tests for app_lifespan httpx client cleanup on shutdown."""

    async def test_client_closed_on_normal_exit(self) -> None:
        """Test that the httpx client is closed after the context exits."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                client = ctx.client
                assert not client.is_closed

            # After exiting, client should be closed
            assert client.is_closed

    async def test_client_closed_on_exception(self) -> None:
        """Test that the httpx client is closed even when an exception occurs."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            client = None
            with pytest.raises(RuntimeError, match="test error"):
                async with app_lifespan(mock_server) as ctx:
                    client = ctx.client
                    raise RuntimeError("test error")

            assert client is not None
            assert client.is_closed


# ---------------------------------------------------------------------------
# app_lifespan - Read-Only Mode Logging
# ---------------------------------------------------------------------------


class TestAppLifespanReadOnlyLogging:
    """Tests for read-only mode logging at startup."""

    async def test_read_only_mode_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that read-only mode is logged at startup."""
        settings = _make_settings(read_only=True)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            with caplog.at_level(logging.INFO, logger="mamba_mcp_gitlab.server"):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert "READ-ONLY mode" in caplog.text

    async def test_read_write_mode_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that read-write mode is logged when read_only is False."""
        settings = _make_settings(read_only=False)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            with caplog.at_level(logging.INFO, logger="mamba_mcp_gitlab.server"):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert "read-write mode" in caplog.text

    async def test_auth_success_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that successful authentication is logged with username and scopes."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(username="admin", scopes=["api"]),
            ),
        ):
            mock_server = MagicMock()
            with caplog.at_level(logging.INFO, logger="mamba_mcp_gitlab.server"):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert "admin" in caplog.text
        assert "pat" in caplog.text

    async def test_client_closed_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that client closure is logged on shutdown."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
        ):
            mock_server = MagicMock()
            with caplog.at_level(logging.INFO, logger="mamba_mcp_gitlab.server"):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert "HTTP client closed" in caplog.text


# ---------------------------------------------------------------------------
# app_lifespan - SSL Verification
# ---------------------------------------------------------------------------


class TestAppLifespanSSL:
    """Tests for SSL verification behavior."""

    async def test_verify_ssl_false_disables_verification(self) -> None:
        """Test that verify_ssl=False disables SSL verification (development mode)."""
        settings = _make_settings(verify_ssl=False)
        captured_verify: list[bool] = []

        original_init = httpx.AsyncClient.__init__

        def capture_verify(self, *args, **kwargs):
            if "verify" in kwargs:
                captured_verify.append(kwargs["verify"])
            return original_init(self, *args, **kwargs)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
            patch.object(httpx.AsyncClient, "__init__", capture_verify),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings.gitlab.verify_ssl is False
                assert len(captured_verify) == 1
                assert captured_verify[0] is False

    async def test_verify_ssl_true_passes_true(self) -> None:
        """Test that verify_ssl=True passes verify=True to httpx client."""
        settings = _make_settings(verify_ssl=True)
        captured_verify: list[bool] = []

        original_init = httpx.AsyncClient.__init__

        def capture_verify(self, *args, **kwargs):
            if "verify" in kwargs:
                captured_verify.append(kwargs["verify"])
            return original_init(self, *args, **kwargs)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                return_value=_make_auth_info(),
            ),
            patch.object(httpx.AsyncClient, "__init__", capture_verify),
        ):
            mock_server = MagicMock()
            async with app_lifespan(mock_server) as ctx:
                assert ctx.settings.gitlab.verify_ssl is True
                assert len(captured_verify) == 1
                assert captured_verify[0] is True


# ---------------------------------------------------------------------------
# app_lifespan - Auth Failure
# ---------------------------------------------------------------------------


class TestAppLifespanAuthFailure:
    """Tests for app_lifespan when authentication fails."""

    async def test_auth_config_error_exits(self) -> None:
        """Test that an auth configuration error triggers SystemExit(1)."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.server.detect_auth_strategy",
                side_effect=AuthenticationError("No auth configured"),
            ),
        ):
            mock_server = MagicMock()
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server) as _ctx:
                    pass
            assert exc_info.value.code == 1

    async def test_auth_config_error_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that an auth configuration error is logged."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.server.detect_auth_strategy",
                side_effect=AuthenticationError("Token missing"),
            ),
        ):
            mock_server = MagicMock()
            with (
                caplog.at_level(logging.ERROR, logger="mamba_mcp_gitlab.server"),
                pytest.raises(SystemExit),
            ):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert "Authentication configuration error" in caplog.text
        assert "Token missing" in caplog.text

    async def test_token_validation_failure_exits(self) -> None:
        """Test that token validation failure triggers SystemExit(1)."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                side_effect=AuthenticationError("Token invalid or expired"),
            ),
        ):
            mock_server = MagicMock()
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server) as _ctx:
                    pass
            assert exc_info.value.code == 1

    async def test_token_validation_failure_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that token validation failure is logged."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                side_effect=AuthenticationError("Token invalid"),
            ),
        ):
            mock_server = MagicMock()
            with (
                caplog.at_level(logging.ERROR, logger="mamba_mcp_gitlab.server"),
                pytest.raises(SystemExit),
            ):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert "Authentication failed" in caplog.text
        assert "Token invalid" in caplog.text

    async def test_connection_error_exits(self) -> None:
        """Test that GitLab unreachable at startup triggers SystemExit(1)."""
        settings = _make_settings()

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                side_effect=AuthenticationError(
                    "Cannot reach GitLab at https://gitlab.example.com"
                ),
            ),
        ):
            mock_server = MagicMock()
            with pytest.raises(SystemExit) as exc_info:
                async with app_lifespan(mock_server) as _ctx:
                    pass
            assert exc_info.value.code == 1

    async def test_client_closed_after_auth_failure(self) -> None:
        """Test that httpx client is closed when auth validation fails."""
        settings = _make_settings()
        close_called = False

        original_aclose = httpx.AsyncClient.aclose

        async def track_close(self):
            nonlocal close_called
            close_called = True
            await original_aclose(self)

        with (
            patch("mamba_mcp_gitlab.server.get_settings", return_value=settings),
            patch(
                "mamba_mcp_gitlab.auth.PATAuthStrategy.validate",
                side_effect=AuthenticationError("Token invalid"),
            ),
            patch.object(httpx.AsyncClient, "aclose", track_close),
        ):
            mock_server = MagicMock()
            with pytest.raises(SystemExit):
                async with app_lifespan(mock_server) as _ctx:
                    pass

        assert close_called


# ---------------------------------------------------------------------------
# Module-level mcp instance
# ---------------------------------------------------------------------------


class TestMCPInstance:
    """Tests for the module-level mcp FastMCP instance."""

    def test_mcp_instance_exists(self) -> None:
        """Test that the module-level mcp instance exists."""
        assert mcp is not None

    def test_mcp_is_fastmcp(self) -> None:
        """Test that mcp is a FastMCP instance."""
        assert isinstance(mcp, FastMCP)

    def test_mcp_name_is_gitlab(self) -> None:
        """Test that the MCP server is named 'GitLab MCP Server'."""
        assert mcp.name == "GitLab MCP Server"
