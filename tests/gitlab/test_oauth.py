"""Tests for OAuth 2.0 client credentials authentication strategy."""

from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import pytest
from mamba_mcp_gitlab.auth import (
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
# Constants
# ---------------------------------------------------------------------------

GITLAB_URL = "https://gitlab.example.com"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_oauth_settings(
    *,
    client_id: str | None = CLIENT_ID,
    client_secret: str | None = CLIENT_SECRET,
    redirect_uri: str | None = None,
) -> OAuthSettings:
    """Create an OAuthSettings instance for testing."""
    return OAuthSettings(
        client_id=client_id,
        client_secret=SecretStr(client_secret) if client_secret else None,
        redirect_uri=redirect_uri,
        _env_file=None,  # type: ignore[call-arg]
    )


def _make_full_settings(
    *,
    token: str | None = None,
    client_id: str | None = CLIENT_ID,
    client_secret: str | None = CLIENT_SECRET,
) -> Settings:
    """Create a full Settings instance with specified auth configuration."""
    gitlab = GitLabSettings(
        url=GITLAB_URL,
        token=SecretStr(token) if token else None,
        _env_file=None,  # type: ignore[call-arg]
    )
    oauth = OAuthSettings(
        client_id=client_id,
        client_secret=SecretStr(client_secret) if client_secret else None,
        _env_file=None,  # type: ignore[call-arg]
    )
    return Settings(
        gitlab=gitlab,
        oauth=oauth,
        server=ServerSettings(_env_file=None),  # type: ignore[call-arg]
        rate_limit=RateLimitSettings(_env_file=None),  # type: ignore[call-arg]
    )


def _make_oauth_token_response(
    *,
    access_token: str = "oauth-access-token-123",
    refresh_token: str | None = "oauth-refresh-token-456",
    expires_in: int | None = 7200,
    token_type: str = "bearer",
) -> dict:
    """Build a mock /oauth/token response body."""
    data: dict = {
        "access_token": access_token,
        "token_type": token_type,
    }
    if refresh_token is not None:
        data["refresh_token"] = refresh_token
    if expires_in is not None:
        data["expires_in"] = expires_in
    return data


def _make_user_response(
    *,
    username: str = "oauth-user",
    user_id: int = 99,
) -> dict:
    """Build a mock /api/v4/user response body."""
    return {
        "id": user_id,
        "username": username,
        "name": "OAuth User",
        "state": "active",
    }


def _make_oauth_transport(
    *,
    token_response: dict | None = None,
    user_response: dict | None = None,
    token_status: int = 200,
    user_status: int = 200,
    token_error: type[Exception] | None = None,
    user_error: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Create a MockTransport that handles both /oauth/token and /api/v4/user."""
    t_resp = token_response or _make_oauth_token_response()
    u_resp = user_response or _make_user_response()

    def handler(request: httpx.Request) -> httpx.Response:
        url_path = str(request.url.path)
        if "/oauth/token" in url_path:
            if token_error is not None:
                raise token_error("token request failed")
            return httpx.Response(token_status, json=t_resp)
        if "/api/v4/user" in url_path:
            if user_error is not None:
                raise user_error("user request failed")
            return httpx.Response(user_status, json=u_resp)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Protocol Compliance
# ---------------------------------------------------------------------------


class TestOAuthProtocolCompliance:
    """Tests that OAuthAuthStrategy satisfies the AuthStrategy protocol."""

    def test_satisfies_auth_strategy_protocol(self) -> None:
        """Test that OAuthAuthStrategy is recognized as an AuthStrategy instance."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        assert isinstance(strategy, AuthStrategy)

    def test_has_get_headers_method(self) -> None:
        """Test that OAuthAuthStrategy has get_headers method."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        assert hasattr(strategy, "get_headers")
        assert callable(strategy.get_headers)

    def test_has_validate_method(self) -> None:
        """Test that OAuthAuthStrategy has validate method."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        assert hasattr(strategy, "validate")


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Constructor Validation
# ---------------------------------------------------------------------------


class TestOAuthConstructorValidation:
    """Tests for OAuthAuthStrategy constructor settings validation."""

    def test_accepts_valid_settings(self) -> None:
        """Test that valid OAuth settings are accepted."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        assert strategy is not None

    def test_rejects_missing_client_id(self) -> None:
        """Test that missing client_id raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="client_id is required"):
            OAuthAuthStrategy(
                oauth_settings=_make_oauth_settings(client_id=None),
                gitlab_url=GITLAB_URL,
            )

    def test_rejects_empty_client_id(self) -> None:
        """Test that empty client_id raises AuthenticationError."""
        # OAuthSettings converts empty string to None via validator
        with pytest.raises(AuthenticationError, match="client_id is required"):
            OAuthAuthStrategy(
                oauth_settings=_make_oauth_settings(client_id=""),
                gitlab_url=GITLAB_URL,
            )

    def test_rejects_missing_client_secret(self) -> None:
        """Test that missing client_secret raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="client_secret is required"):
            OAuthAuthStrategy(
                oauth_settings=_make_oauth_settings(client_secret=None),
                gitlab_url=GITLAB_URL,
            )

    def test_rejects_empty_client_secret(self) -> None:
        """Test that empty client_secret raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="client_secret is empty"):
            OAuthAuthStrategy(
                oauth_settings=OAuthSettings(
                    client_id=CLIENT_ID,
                    client_secret=SecretStr(""),
                    _env_file=None,  # type: ignore[call-arg]
                ),
                gitlab_url=GITLAB_URL,
            )

    def test_rejects_whitespace_client_secret(self) -> None:
        """Test that whitespace-only client_secret raises AuthenticationError."""
        with pytest.raises(AuthenticationError, match="client_secret is empty"):
            OAuthAuthStrategy(
                oauth_settings=OAuthSettings(
                    client_id=CLIENT_ID,
                    client_secret=SecretStr("   "),
                    _env_file=None,  # type: ignore[call-arg]
                ),
                gitlab_url=GITLAB_URL,
            )

    def test_strips_trailing_slash_from_url(self) -> None:
        """Test that trailing slashes are stripped from the GitLab URL."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url="https://gitlab.example.com/",
        )
        assert strategy._gitlab_url == "https://gitlab.example.com"


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Header Construction
# ---------------------------------------------------------------------------


class TestOAuthHeaders:
    """Tests for OAuthAuthStrategy header construction."""

    def test_returns_empty_dict_before_token_obtained(self) -> None:
        """Test that get_headers returns empty dict when no token is available."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        headers = strategy.get_headers()
        assert headers == {}

    def test_returns_bearer_header_after_token_set(self) -> None:
        """Test that get_headers returns Authorization: Bearer header."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "test-access-token"
        headers = strategy.get_headers()
        assert headers == {"Authorization": "Bearer test-access-token"}

    def test_header_key_is_authorization(self) -> None:
        """Test that the header key is exactly 'Authorization'."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "token"
        assert "Authorization" in strategy.get_headers()

    def test_header_value_starts_with_bearer(self) -> None:
        """Test that the header value starts with 'Bearer '."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "my-token"
        value = strategy.get_headers()["Authorization"]
        assert value.startswith("Bearer ")

    def test_returns_new_dict_each_call(self) -> None:
        """Test that get_headers returns a new dict on each call."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "token"
        headers1 = strategy.get_headers()
        headers2 = strategy.get_headers()
        assert headers1 == headers2
        assert headers1 is not headers2


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Token Expiry
# ---------------------------------------------------------------------------


class TestOAuthTokenExpiry:
    """Tests for token expiry detection."""

    def test_expired_when_no_token(self) -> None:
        """Test that is_token_expired returns True when no token exists."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        assert strategy.is_token_expired is True

    def test_expired_when_no_expiry_set(self) -> None:
        """Test that is_token_expired returns True when expires_at is None."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "token"
        strategy._expires_at = None
        assert strategy.is_token_expired is True

    def test_not_expired_when_future_expiry(self) -> None:
        """Test that is_token_expired returns False for future expiry."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "token"
        # Set expiry far in the future
        strategy._expires_at = time.monotonic() + 3600
        assert strategy.is_token_expired is False

    def test_expired_when_past_expiry(self) -> None:
        """Test that is_token_expired returns True for past expiry."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "token"
        # Set expiry in the past
        strategy._expires_at = time.monotonic() - 100
        assert strategy.is_token_expired is True

    def test_expired_within_buffer_window(self) -> None:
        """Test that token is considered expired within the buffer window."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "token"
        # Set expiry just within the buffer (30 seconds by default)
        strategy._expires_at = time.monotonic() + 10
        assert strategy.is_token_expired is True


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Token Acquisition
# ---------------------------------------------------------------------------


class TestOAuthTokenAcquisition:
    """Tests for _obtain_token via client credentials flow."""

    async def test_posts_to_oauth_token_endpoint(self) -> None:
        """Test that _obtain_token posts to /oauth/token."""
        posted_urls: list[str] = []
        posted_data: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posted_urls.append(str(request.url))
            # Parse form data from content
            content = request.content.decode()
            pairs = dict(p.split("=") for p in content.split("&"))
            posted_data.append(pairs)
            return httpx.Response(200, json=_make_oauth_token_response())

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._obtain_token(client)

        assert len(posted_urls) == 1
        assert "/oauth/token" in posted_urls[0]
        assert posted_data[0]["grant_type"] == "client_credentials"
        assert posted_data[0]["client_id"] == CLIENT_ID

    async def test_stores_access_token(self) -> None:
        """Test that the access token is stored after acquisition."""
        transport = _make_oauth_transport()
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._obtain_token(client)

        assert strategy._access_token == "oauth-access-token-123"

    async def test_stores_refresh_token(self) -> None:
        """Test that the refresh token is stored if present."""
        transport = _make_oauth_transport()
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._obtain_token(client)

        assert strategy._refresh_token == "oauth-refresh-token-456"

    async def test_calculates_expiry_from_expires_in(self) -> None:
        """Test that expires_at is calculated from the expires_in field."""
        transport = _make_oauth_transport(
            token_response=_make_oauth_token_response(expires_in=3600),
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        before = time.monotonic()
        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._obtain_token(client)
        after = time.monotonic()

        assert strategy._expires_at is not None
        assert before + 3600 <= strategy._expires_at <= after + 3600

    async def test_no_expires_in_sets_none(self) -> None:
        """Test that missing expires_in results in expires_at=None."""
        transport = _make_oauth_transport(
            token_response=_make_oauth_token_response(expires_in=None),
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._obtain_token(client)

        assert strategy._expires_at is None

    async def test_no_refresh_token_in_response(self) -> None:
        """Test that missing refresh_token is stored as None."""
        transport = _make_oauth_transport(
            token_response=_make_oauth_token_response(refresh_token=None),
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._obtain_token(client)

        assert strategy._refresh_token is None

    async def test_401_raises_auth_error_with_credentials_message(self) -> None:
        """Test that 401 from token endpoint raises clear error about credentials."""
        transport = _make_oauth_transport(token_status=401)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="client credentials are invalid"):
                await strategy._obtain_token(client)

    async def test_500_raises_auth_error(self) -> None:
        """Test that non-200/401 status raises AuthenticationError."""
        transport = _make_oauth_transport(token_status=500)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="HTTP 500"):
                await strategy._obtain_token(client)

    async def test_missing_access_token_in_response_raises_error(self) -> None:
        """Test that response without access_token raises AuthenticationError."""
        transport = _make_oauth_transport(
            token_response={"token_type": "bearer"},
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="missing 'access_token'"):
                await strategy._obtain_token(client)

    async def test_connect_error_raises_auth_error(self) -> None:
        """Test that connection failure raises AuthenticationError with URL."""
        transport = _make_oauth_transport(token_error=httpx.ConnectError)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="Cannot reach GitLab"):
                await strategy._obtain_token(client)

    async def test_http_error_raises_auth_error(self) -> None:
        """Test that generic HTTP error raises AuthenticationError."""
        transport = _make_oauth_transport(token_error=httpx.ReadTimeout)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="HTTP error during OAuth"):
                await strategy._obtain_token(client)


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Token Refresh
# ---------------------------------------------------------------------------


class TestOAuthTokenRefresh:
    """Tests for _refresh_access_token flow."""

    async def test_refresh_uses_refresh_token(self) -> None:
        """Test that refresh sends the stored refresh token."""
        posted_data: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            content = request.content.decode()
            pairs = dict(p.split("=") for p in content.split("&"))
            posted_data.append(pairs)
            return httpx.Response(
                200,
                json=_make_oauth_token_response(
                    access_token="new-access-token",
                    refresh_token="new-refresh-token",
                ),
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = "old-refresh-token"

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)

        assert posted_data[0]["grant_type"] == "refresh_token"
        assert posted_data[0]["refresh_token"] == "old-refresh-token"
        assert strategy._access_token == "new-access-token"
        assert strategy._refresh_token == "new-refresh-token"

    async def test_refresh_falls_back_to_obtain_when_no_refresh_token(self) -> None:
        """Test that missing refresh token triggers full re-authentication."""
        transport = _make_oauth_transport()
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = None

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)

        assert strategy._access_token == "oauth-access-token-123"

    async def test_refresh_falls_back_on_http_error(self) -> None:
        """Test that HTTP error during refresh triggers fallback to obtain."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call is refresh attempt -> fail
                raise httpx.ReadTimeout("timeout")
            # Second call is the fallback obtain
            return httpx.Response(
                200,
                json=_make_oauth_token_response(
                    access_token="fallback-token",
                ),
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = "old-refresh"

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)

        assert strategy._access_token == "fallback-token"

    async def test_refresh_falls_back_on_non_200_status(self) -> None:
        """Test that non-200 refresh response triggers fallback to obtain."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call is refresh attempt -> fail with 400
                return httpx.Response(400, json={"error": "invalid_grant"})
            # Second call is the fallback obtain (no refresh token in response)
            return httpx.Response(
                200,
                json=_make_oauth_token_response(
                    access_token="new-token",
                    refresh_token=None,
                ),
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = "old-refresh"

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)

        assert strategy._access_token == "new-token"
        # Refresh token was cleared before fallback and not restored by response
        assert strategy._refresh_token is None

    async def test_refresh_falls_back_on_missing_access_token_in_response(self) -> None:
        """Test fallback when refresh response has no access_token."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Refresh succeeds but response is missing access_token
                return httpx.Response(200, json={"token_type": "bearer"})
            # Fallback obtain
            return httpx.Response(
                200,
                json=_make_oauth_token_response(
                    access_token="fallback-token",
                ),
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = "old-refresh"

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)

        assert strategy._access_token == "fallback-token"

    async def test_refresh_preserves_old_refresh_token_if_new_not_provided(self) -> None:
        """Test that the existing refresh token is kept if response lacks one."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "token_type": "bearer",
                },
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = "keep-this-refresh"

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)

        assert strategy._access_token == "new-access"
        assert strategy._refresh_token == "keep-this-refresh"

    async def test_refresh_updates_expiry(self) -> None:
        """Test that refresh updates the expires_at timestamp."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_make_oauth_token_response(
                    access_token="refreshed-token",
                    expires_in=1800,
                ),
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "old-token"
        strategy._refresh_token = "refresh"

        before = time.monotonic()
        async with httpx.AsyncClient(transport=transport) as client:
            await strategy._refresh_access_token(client)
        after = time.monotonic()

        assert strategy._expires_at is not None
        assert before + 1800 <= strategy._expires_at <= after + 1800


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - ensure_valid_token
# ---------------------------------------------------------------------------


class TestOAuthEnsureValidToken:
    """Tests for ensure_valid_token orchestration."""

    async def test_skips_when_token_is_valid(self) -> None:
        """Test that no request is made when token is still valid."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_make_oauth_token_response())

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "valid-token"
        strategy._expires_at = time.monotonic() + 3600

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy.ensure_valid_token(client)

        assert call_count == 0

    async def test_obtains_when_no_token(self) -> None:
        """Test that a new token is obtained when none exists."""
        transport = _make_oauth_transport()
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy.ensure_valid_token(client)

        assert strategy._access_token == "oauth-access-token-123"

    async def test_refreshes_when_token_expired(self) -> None:
        """Test that token is refreshed when expired."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_make_oauth_token_response(
                    access_token="refreshed-token",
                ),
            )

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "expired-token"
        strategy._refresh_token = "my-refresh"
        strategy._expires_at = time.monotonic() - 100  # expired

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy.ensure_valid_token(client)

        assert strategy._access_token == "refreshed-token"


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - validate() (full flow)
# ---------------------------------------------------------------------------


class TestOAuthValidate:
    """Tests for OAuthAuthStrategy.validate() end-to-end flow."""

    async def test_obtains_token_and_validates_user(self) -> None:
        """Test that validate obtains a token and calls /api/v4/user."""
        transport = _make_oauth_transport(
            user_response=_make_user_response(username="admin-user"),
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            info = await strategy.validate(client)

        assert isinstance(info, AuthInfo)
        assert info.auth_type == "oauth"
        assert info.username == "admin-user"
        assert info.scopes == []
        assert info.expires_at is None

    async def test_sends_bearer_header_to_user_endpoint(self) -> None:
        """Test that the Bearer header is sent when validating via /api/v4/user."""
        sent_auth_headers: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url_path = str(request.url.path)
            if "/oauth/token" in url_path:
                return httpx.Response(200, json=_make_oauth_token_response())
            if "/api/v4/user" in url_path:
                sent_auth_headers.append(request.headers.get("authorization"))
                return httpx.Response(200, json=_make_user_response())
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            await strategy.validate(client)

        assert len(sent_auth_headers) == 1
        assert sent_auth_headers[0] == "Bearer oauth-access-token-123"

    async def test_user_endpoint_401_raises_auth_error(self) -> None:
        """Test that 401 from /api/v4/user raises AuthenticationError."""
        transport = _make_oauth_transport(user_status=401)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="invalid or expired after acquisition"):
                await strategy.validate(client)

    async def test_user_endpoint_500_raises_auth_error(self) -> None:
        """Test that non-200/401 from /api/v4/user raises AuthenticationError."""
        transport = _make_oauth_transport(user_status=500)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="HTTP 500"):
                await strategy.validate(client)

    async def test_user_endpoint_connect_error(self) -> None:
        """Test that connection error to /api/v4/user raises AuthenticationError."""
        transport = _make_oauth_transport(user_error=httpx.ConnectError)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="Cannot reach GitLab"):
                await strategy.validate(client)

    async def test_user_endpoint_http_error(self) -> None:
        """Test that generic HTTP error from /api/v4/user raises AuthenticationError."""
        transport = _make_oauth_transport(user_error=httpx.ReadTimeout)
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(AuthenticationError, match="HTTP error validating OAuth"):
                await strategy.validate(client)

    async def test_unknown_username_defaults_to_unknown(self) -> None:
        """Test that missing username in user response defaults to 'unknown'."""
        transport = _make_oauth_transport(
            user_response={"id": 1, "name": "No Username"},
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        async with httpx.AsyncClient(transport=transport) as client:
            info = await strategy.validate(client)

        assert info.username == "unknown"


# ---------------------------------------------------------------------------
# detect_auth_strategy - OAuth Integration
# ---------------------------------------------------------------------------


class TestDetectAuthStrategyOAuth:
    """Tests for detect_auth_strategy with OAuth configuration."""

    def test_returns_oauth_when_credentials_configured(self) -> None:
        """Test that OAuthAuthStrategy is returned when OAuth is configured."""
        settings = _make_full_settings()
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, OAuthAuthStrategy)

    def test_pat_takes_precedence_over_oauth(self) -> None:
        """Test that PAT is returned when both PAT and OAuth are configured."""
        settings = _make_full_settings(
            token="glpat-xxxxxxxxxxxxxxxxxxxx",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, PATAuthStrategy)

    def test_oauth_not_selected_without_client_id(self) -> None:
        """Test that OAuth is not selected when client_id is missing."""
        settings = _make_full_settings(
            client_id=None,
            client_secret=CLIENT_SECRET,
        )
        with pytest.raises(AuthenticationError, match="No authentication configured"):
            detect_auth_strategy(settings)

    def test_oauth_not_selected_without_client_secret(self) -> None:
        """Test that OAuth is not selected when client_secret is missing."""
        settings = _make_full_settings(
            client_id=CLIENT_ID,
            client_secret=None,
        )
        with pytest.raises(AuthenticationError, match="No authentication configured"):
            detect_auth_strategy(settings)

    def test_oauth_strategy_has_correct_url(self) -> None:
        """Test that the OAuth strategy receives the GitLab URL from settings."""
        settings = _make_full_settings()
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, OAuthAuthStrategy)
        assert strategy._gitlab_url == GITLAB_URL

    def test_oauth_strategy_satisfies_protocol(self) -> None:
        """Test that the returned OAuth strategy satisfies AuthStrategy protocol."""
        settings = _make_full_settings()
        strategy = detect_auth_strategy(settings)
        assert isinstance(strategy, AuthStrategy)


# ---------------------------------------------------------------------------
# OAuthAuthStrategy - Token Expiry During Request (Edge Case)
# ---------------------------------------------------------------------------


class TestOAuthTokenExpiryEdgeCases:
    """Tests for token expiry edge cases."""

    async def test_token_refresh_before_validate_when_expired(self) -> None:
        """Test that ensure_valid_token refreshes before validate completes."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "expired-token"
        strategy._refresh_token = "my-refresh"
        strategy._expires_at = time.monotonic() - 100

        call_order: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url_path = str(request.url.path)
            if "/oauth/token" in url_path:
                call_order.append("token")
                return httpx.Response(
                    200,
                    json=_make_oauth_token_response(
                        access_token="refreshed-token",
                    ),
                )
            if "/api/v4/user" in url_path:
                call_order.append("user")
                return httpx.Response(200, json=_make_user_response())
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            info = await strategy.validate(client)

        assert call_order == ["token", "user"]
        assert info.auth_type == "oauth"

    async def test_token_with_no_expiry_considered_expired(self) -> None:
        """Test that a token without expiry is treated as expired (requires re-check)."""
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )
        strategy._access_token = "no-expiry-token"
        strategy._expires_at = None

        # is_token_expired should be True when expires_at is None
        assert strategy.is_token_expired is True

    async def test_monotonic_clock_used_for_expiry(self) -> None:
        """Test that time.monotonic is used (not time.time) for expiry tracking."""
        transport = _make_oauth_transport(
            token_response=_make_oauth_token_response(expires_in=100),
        )
        strategy = OAuthAuthStrategy(
            oauth_settings=_make_oauth_settings(),
            gitlab_url=GITLAB_URL,
        )

        with patch("mamba_mcp_gitlab.auth.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            async with httpx.AsyncClient(transport=transport) as client:
                await strategy._obtain_token(client)

        assert strategy._expires_at == 1100.0
