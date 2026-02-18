"""Tests for authentication strategies module."""

from __future__ import annotations

import logging

import httpx
import pytest
from mamba_mcp_gitlab.auth import (
    REQUIRED_SCOPES,
    AuthenticationError,
    AuthInfo,
    AuthStrategy,
    OAuthAuthStrategy,
    PATAuthStrategy,
    detect_auth_strategy,
)
from mamba_mcp_gitlab.config import (
    GitLabSettings,
    OAuthSettings,
    RateLimitSettings,
    ServerSettings,
    Settings,
)
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    token: str | None = None,
    oauth_client_id: str | None = None,
    oauth_client_secret: str | None = None,
) -> Settings:
    """Create a Settings instance with specified auth configuration."""
    gitlab = GitLabSettings(
        url="https://gitlab.example.com",
        token=SecretStr(token) if token else None,
        _env_file=None,  # type: ignore[call-arg]
    )
    oauth = OAuthSettings(
        client_id=oauth_client_id,
        client_secret=SecretStr(oauth_client_secret) if oauth_client_secret else None,
        _env_file=None,  # type: ignore[call-arg]
    )
    return Settings(
        gitlab=gitlab,
        oauth=oauth,
        server=ServerSettings(_env_file=None),  # type: ignore[call-arg]
        rate_limit=RateLimitSettings(_env_file=None),  # type: ignore[call-arg]
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
# AuthenticationError
# ---------------------------------------------------------------------------


class TestAuthenticationError:
    """Tests for AuthenticationError custom exception."""

    def test_is_exception_subclass(self) -> None:
        """Test that AuthenticationError is a proper Exception subclass."""
        assert issubclass(AuthenticationError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that AuthenticationError can be raised and caught."""
        with pytest.raises(AuthenticationError, match="test error"):
            raise AuthenticationError("test error")

    def test_message_preserved(self) -> None:
        """Test that the error message is preserved."""
        err = AuthenticationError("detailed auth failure")
        assert str(err) == "detailed auth failure"

    def test_catchable_as_exception(self) -> None:
        """Test that AuthenticationError is catchable as a generic Exception."""
        with pytest.raises(Exception):
            raise AuthenticationError("catch me")


# ---------------------------------------------------------------------------
# AuthInfo
# ---------------------------------------------------------------------------


class TestAuthInfo:
    """Tests for AuthInfo dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """Test AuthInfo creation with only required fields."""
        info = AuthInfo(auth_type="pat", username="testuser")
        assert info.auth_type == "pat"
        assert info.username == "testuser"
        assert info.scopes == []
        assert info.expires_at is None

    def test_creates_with_all_fields(self) -> None:
        """Test AuthInfo creation with all fields populated."""
        info = AuthInfo(
            auth_type="pat",
            username="admin",
            scopes=["api", "read_user"],
            expires_at="2027-12-31",
        )
        assert info.auth_type == "pat"
        assert info.username == "admin"
        assert info.scopes == ["api", "read_user"]
        assert info.expires_at == "2027-12-31"

    def test_expires_at_none_for_non_expiring_token(self) -> None:
        """Test that expires_at defaults to None for tokens without expiration."""
        info = AuthInfo(auth_type="pat", username="user")
        assert info.expires_at is None

    def test_scopes_default_to_empty_list(self) -> None:
        """Test that scopes default to an empty list."""
        info = AuthInfo(auth_type="pat", username="user")
        assert info.scopes == []
        assert isinstance(info.scopes, list)


# ---------------------------------------------------------------------------
# AuthStrategy Protocol
# ---------------------------------------------------------------------------


class TestAuthStrategy:
    """Tests for AuthStrategy protocol compliance."""

    def test_pat_auth_strategy_satisfies_protocol(self) -> None:
        """Test that PATAuthStrategy is recognized as an AuthStrategy instance."""
        strategy = PATAuthStrategy(SecretStr("glpat-valid-token"))
        assert isinstance(strategy, AuthStrategy)

    def test_protocol_has_get_headers(self) -> None:
        """Test that AuthStrategy protocol requires get_headers method."""
        assert hasattr(AuthStrategy, "get_headers")

    def test_protocol_has_validate(self) -> None:
        """Test that AuthStrategy protocol requires validate method."""
        assert hasattr(AuthStrategy, "validate")


# ---------------------------------------------------------------------------
# PATAuthStrategy - Header Construction
# ---------------------------------------------------------------------------


class TestPATAuthStrategyHeaders:
    """Tests for PATAuthStrategy header construction."""

    def test_adds_private_token_header(self) -> None:
        """Test that get_headers returns the PRIVATE-TOKEN header."""
        strategy = PATAuthStrategy(SecretStr("glpat-xxxxxxxxxxxxxxxxxxxx"))
        headers = strategy.get_headers()
        assert headers == {"PRIVATE-TOKEN": "glpat-xxxxxxxxxxxxxxxxxxxx"}

    def test_header_key_is_private_token(self) -> None:
        """Test that the header key is exactly PRIVATE-TOKEN."""
        strategy = PATAuthStrategy(SecretStr("my-token"))
        headers = strategy.get_headers()
        assert "PRIVATE-TOKEN" in headers

    def test_header_value_matches_token(self) -> None:
        """Test that the header value matches the provided token."""
        token_value = "glpat-abcdef123456"
        strategy = PATAuthStrategy(SecretStr(token_value))
        assert strategy.get_headers()["PRIVATE-TOKEN"] == token_value

    def test_returns_new_dict_each_call(self) -> None:
        """Test that get_headers returns a new dict on each call (no shared state)."""
        strategy = PATAuthStrategy(SecretStr("glpat-token"))
        headers1 = strategy.get_headers()
        headers2 = strategy.get_headers()
        assert headers1 == headers2
        assert headers1 is not headers2


# ---------------------------------------------------------------------------
# PATAuthStrategy - Token Format Validation
# ---------------------------------------------------------------------------


class TestPATAuthStrategyValidation:
    """Tests for PATAuthStrategy constructor token validation."""

    def test_rejects_empty_token(self) -> None:
        """Test that an empty string token is rejected at construction."""
        with pytest.raises(AuthenticationError, match="empty or whitespace"):
            PATAuthStrategy(SecretStr(""))

    def test_rejects_whitespace_only_token(self) -> None:
        """Test that a whitespace-only token is rejected at construction."""
        with pytest.raises(AuthenticationError, match="empty or whitespace"):
            PATAuthStrategy(SecretStr("   "))

    def test_rejects_tab_only_token(self) -> None:
        """Test that a tab-only token is rejected at construction."""
        with pytest.raises(AuthenticationError, match="empty or whitespace"):
            PATAuthStrategy(SecretStr("\t\n"))

    def test_accepts_valid_token(self) -> None:
        """Test that a valid non-empty token is accepted."""
        strategy = PATAuthStrategy(SecretStr("glpat-valid"))
        assert strategy.get_headers()["PRIVATE-TOKEN"] == "glpat-valid"


# ---------------------------------------------------------------------------
# PATAuthStrategy - Token Validation via API
# ---------------------------------------------------------------------------


class TestPATAuthStrategyValidate:
    """Tests for PATAuthStrategy.validate() with mock HTTP responses."""

    async def test_calls_token_self_endpoint(self) -> None:
        """Test that validate calls /api/v4/personal_access_tokens/self."""
        called_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            called_urls.append(str(request.url))
            return httpx.Response(200, json=_mock_token_response())

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid-token"))
            await strategy.validate(client)

        assert len(called_urls) == 1
        assert "/api/v4/personal_access_tokens/self" in called_urls[0]

    async def test_sends_private_token_header(self) -> None:
        """Test that validate sends the PRIVATE-TOKEN header in the request."""
        sent_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            sent_headers.update(dict(request.headers))
            return httpx.Response(200, json=_mock_token_response())

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-my-token"))
            await strategy.validate(client)

        assert sent_headers.get("private-token") == "glpat-my-token"

    async def test_returns_auth_info_on_success(self) -> None:
        """Test that a successful validation returns populated AuthInfo."""
        data = _mock_token_response(
            username="admin",
            scopes=["api", "read_user"],
            expires_at="2027-06-30",
        )
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            info = await strategy.validate(client)

        assert isinstance(info, AuthInfo)
        assert info.auth_type == "pat"
        assert info.username == "admin"
        assert info.scopes == ["api", "read_user"]
        assert info.expires_at == "2027-06-30"

    async def test_no_expiration_yields_none(self) -> None:
        """Test that a token with no expiration returns expires_at=None."""
        data = _mock_token_response(expires_at=None)
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            info = await strategy.validate(client)

        assert info.expires_at is None

    async def test_invalid_token_raises_auth_error(self) -> None:
        """Test that a 401 response raises AuthenticationError."""
        transport = _make_mock_transport(status_code=401)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-invalid"))
            with pytest.raises(AuthenticationError, match="invalid or expired"):
                await strategy.validate(client)

    async def test_forbidden_raises_auth_error(self) -> None:
        """Test that a 403 response raises AuthenticationError."""
        transport = _make_mock_transport(status_code=403)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-limited"))
            with pytest.raises(AuthenticationError, match="lacks permission"):
                await strategy.validate(client)

    async def test_unexpected_status_raises_auth_error(self) -> None:
        """Test that a non-200/401/403 response raises AuthenticationError."""
        transport = _make_mock_transport(status_code=500)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            with pytest.raises(AuthenticationError, match="HTTP 500"):
                await strategy.validate(client)

    async def test_revoked_token_raises_auth_error(self) -> None:
        """Test that a revoked token raises AuthenticationError."""
        data = _mock_token_response(revoked=True)
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-revoked"))
            with pytest.raises(AuthenticationError, match="revoked"):
                await strategy.validate(client)

    async def test_expired_token_raises_auth_error(self) -> None:
        """Test that an expired token (active=false) raises AuthenticationError."""
        data = _mock_token_response(active=False, expires_at="2024-01-01")
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-expired"))
            with pytest.raises(AuthenticationError, match="expired on 2024-01-01"):
                await strategy.validate(client)

    async def test_connection_error_raises_auth_error(self) -> None:
        """Test that a connection failure raises AuthenticationError with URL."""
        transport = _make_mock_transport(raise_error=httpx.ConnectError)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            with pytest.raises(AuthenticationError, match="Cannot reach GitLab"):
                await strategy.validate(client)

    async def test_http_error_raises_auth_error(self) -> None:
        """Test that a generic HTTP error raises AuthenticationError."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            with pytest.raises(AuthenticationError, match="HTTP error"):
                await strategy.validate(client)

    async def test_insufficient_scopes_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that insufficient scopes produce a warning log."""
        data = _mock_token_response(scopes=["read_user"])
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            with caplog.at_level(logging.WARNING, logger="mamba_mcp_gitlab.auth"):
                info = await strategy.validate(client)

        assert info.scopes == ["read_user"]
        assert "requires one of" in caplog.text

    async def test_sufficient_scopes_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that sufficient scopes do not produce a warning."""
        data = _mock_token_response(scopes=["api"])
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            with caplog.at_level(logging.WARNING, logger="mamba_mcp_gitlab.auth"):
                await strategy.validate(client)

        assert "requires one of" not in caplog.text

    async def test_read_api_scope_is_sufficient(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that read_api scope alone does not trigger a warning."""
        data = _mock_token_response(scopes=["read_api"])
        transport = _make_mock_transport(json_data=data)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://gitlab.example.com"
        ) as client:
            strategy = PATAuthStrategy(SecretStr("glpat-valid"))
            with caplog.at_level(logging.WARNING, logger="mamba_mcp_gitlab.auth"):
                await strategy.validate(client)

        assert "requires one of" not in caplog.text


# ---------------------------------------------------------------------------
# detect_auth_strategy
# ---------------------------------------------------------------------------


class TestDetectAuthStrategy:
    """Tests for detect_auth_strategy factory function."""

    def test_returns_pat_when_token_set(self) -> None:
        """Test that PAT strategy is returned when token is configured."""
        settings = _make_settings(token="glpat-xxxxxxxxxxxxxxxxxxxx")
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, PATAuthStrategy)

    def test_pat_takes_precedence_over_oauth(self) -> None:
        """Test that PAT is selected when both PAT and OAuth are configured."""
        settings = _make_settings(
            token="glpat-xxxxxxxxxxxxxxxxxxxx",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
        )
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, PATAuthStrategy)

    def test_oauth_only_returns_oauth_strategy(self) -> None:
        """Test that OAuth-only config returns an OAuthAuthStrategy."""
        settings = _make_settings(
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
        )
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, OAuthAuthStrategy)

    def test_no_auth_raises_error(self) -> None:
        """Test that missing auth config raises AuthenticationError with clear message."""
        settings = _make_settings()
        with pytest.raises(AuthenticationError, match="No authentication configured"):
            detect_auth_strategy(settings)

    def test_no_auth_error_mentions_env_vars(self) -> None:
        """Test that the no-auth error message mentions the env variable names."""
        settings = _make_settings()
        with pytest.raises(AuthenticationError, match="MAMBA_MCP_GITLAB_TOKEN"):
            detect_auth_strategy(settings)

    def test_returned_strategy_satisfies_protocol(self) -> None:
        """Test that the returned strategy satisfies the AuthStrategy protocol."""
        settings = _make_settings(token="glpat-valid-token")
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, AuthStrategy)

    def test_empty_token_falls_through(self) -> None:
        """Test that an empty token is treated as if no PAT is configured."""
        settings = _make_settings(token="")
        # Token is empty, so it should fall through.
        # GitLabSettings converts empty to None via its validator,
        # but if somehow an empty SecretStr slips through, detect should handle it.
        with pytest.raises(AuthenticationError):
            detect_auth_strategy(settings)

    def test_whitespace_token_falls_through(self) -> None:
        """Test that a whitespace-only token is treated as unconfigured."""
        settings = _make_settings(token="   ")
        with pytest.raises(AuthenticationError):
            detect_auth_strategy(settings)


# ---------------------------------------------------------------------------
# REQUIRED_SCOPES
# ---------------------------------------------------------------------------


class TestRequiredScopes:
    """Tests for the REQUIRED_SCOPES constant."""

    def test_contains_api(self) -> None:
        """Test that api scope is in REQUIRED_SCOPES."""
        assert "api" in REQUIRED_SCOPES

    def test_contains_read_api(self) -> None:
        """Test that read_api scope is in REQUIRED_SCOPES."""
        assert "read_api" in REQUIRED_SCOPES

    def test_is_a_set(self) -> None:
        """Test that REQUIRED_SCOPES is a set type."""
        assert isinstance(REQUIRED_SCOPES, set)
