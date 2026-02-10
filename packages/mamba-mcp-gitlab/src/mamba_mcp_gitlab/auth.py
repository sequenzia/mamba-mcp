"""Authentication strategies for GitLab API access.

Supports Personal Access Token (PAT) and OAuth 2.0 client credentials
authentication with auto-detection. PAT always takes precedence over OAuth.

Based on spec Section 5.5 and 7.5.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx
from pydantic import SecretStr

from mamba_mcp_gitlab.config import OAuthSettings, Settings

logger = logging.getLogger(__name__)

# Required scopes for full access; read_api is sufficient for read-only mode
REQUIRED_SCOPES = {"api", "read_api"}


class AuthenticationError(Exception):
    """Raised when authentication fails or cannot be configured."""


@dataclass
class AuthInfo:
    """Validated authentication details.

    Populated after successful token validation against the GitLab API.
    """

    auth_type: str
    username: str
    scopes: list[str] = field(default_factory=list)
    expires_at: str | None = None


@runtime_checkable
class AuthStrategy(Protocol):
    """Protocol defining the authentication strategy interface."""

    def get_headers(self) -> dict[str, str]:
        """Return headers to attach to each API request."""
        ...

    async def validate(self, client: httpx.AsyncClient) -> AuthInfo:
        """Validate credentials against the GitLab API.

        Args:
            client: An httpx.AsyncClient configured with the GitLab base URL.

        Returns:
            AuthInfo with validated user details.

        Raises:
            AuthenticationError: If validation fails.
        """
        ...


class PATAuthStrategy:
    """Personal Access Token authentication strategy.

    Adds the PRIVATE-TOKEN header to requests and validates the token
    via GET /api/v4/personal_access_tokens/self.
    """

    def __init__(self, token: SecretStr) -> None:
        self._token = token
        self._validate_token_format()

    def _validate_token_format(self) -> None:
        """Ensure the token is non-empty and not whitespace-only."""
        value = self._token.get_secret_value()
        if not value or not value.strip():
            raise AuthenticationError(
                "GitLab personal access token is empty or whitespace-only. "
                "Set MAMBA_MCP_GITLAB_TOKEN to a valid PAT."
            )

    def get_headers(self) -> dict[str, str]:
        """Return the PRIVATE-TOKEN header for GitLab API requests."""
        return {"PRIVATE-TOKEN": self._token.get_secret_value()}

    async def validate(self, client: httpx.AsyncClient) -> AuthInfo:
        """Validate the PAT against GitLab's token introspection endpoint.

        Calls GET /api/v4/personal_access_tokens/self to verify:
        - Token is valid and not expired
        - Token scopes are sufficient

        Args:
            client: An httpx.AsyncClient configured with the GitLab base URL.

        Returns:
            AuthInfo with username, scopes, and expiration from GitLab.

        Raises:
            AuthenticationError: If the token is invalid, expired, or GitLab is unreachable.
        """
        try:
            response = await client.get(
                "/api/v4/personal_access_tokens/self",
                headers=self.get_headers(),
            )
        except httpx.ConnectError as exc:
            base_url = str(client.base_url)
            raise AuthenticationError(
                f"Cannot reach GitLab at {base_url}. "
                "Check network connectivity and the MAMBA_MCP_GITLAB_URL setting."
            ) from exc
        except httpx.HTTPError as exc:
            base_url = str(client.base_url)
            raise AuthenticationError(
                f"HTTP error connecting to GitLab at {base_url}: {exc}"
            ) from exc

        if response.status_code == 401:
            raise AuthenticationError(
                "GitLab token is invalid or expired. "
                "Generate a new PAT at GitLab > User Settings > Access Tokens."
            )

        if response.status_code == 403:
            raise AuthenticationError(
                "GitLab token lacks permission to introspect itself. "
                "Ensure the token has 'api' or 'read_api' scope."
            )

        if response.status_code != 200:
            raise AuthenticationError(
                f"Unexpected response from GitLab token validation "
                f"(HTTP {response.status_code}). Check GitLab server status."
            )

        data = response.json()

        # Check if token is marked as revoked
        if data.get("revoked", False):
            raise AuthenticationError(
                "GitLab token has been revoked. "
                "Generate a new PAT at GitLab > User Settings > Access Tokens."
            )

        # Check if token is expired (active=false without revoked=true)
        if not data.get("active", True):
            expires_at = data.get("expires_at", "unknown")
            raise AuthenticationError(
                f"GitLab token expired on {expires_at}. "
                "Generate a new PAT at GitLab > User Settings > Access Tokens."
            )

        scopes = data.get("scopes", [])
        username = data.get("user", {}).get("username", "unknown")

        # Warn if scopes are insufficient
        if scopes and not set(scopes) & REQUIRED_SCOPES:
            logger.warning(
                "GitLab token has scopes %s but requires one of %s. Some operations may fail.",
                scopes,
                sorted(REQUIRED_SCOPES),
            )

        return AuthInfo(
            auth_type="pat",
            username=username,
            scopes=scopes,
            expires_at=data.get("expires_at"),
        )


class OAuthAuthStrategy:
    """OAuth 2.0 client credentials authentication strategy.

    Obtains an access token via the client credentials flow
    (POST /oauth/token with grant_type=client_credentials) and sets
    the ``Authorization: Bearer {access_token}`` header on requests.

    Handles automatic token refresh when the access token expires.
    """

    # Refresh the token 30 seconds before it actually expires to avoid
    # race conditions where a request is sent with an about-to-expire token.
    _EXPIRY_BUFFER_SECONDS: int = 30

    def __init__(
        self,
        oauth_settings: OAuthSettings,
        gitlab_url: str,
    ) -> None:
        self._client_id = oauth_settings.client_id
        self._client_secret = oauth_settings.client_secret
        self._gitlab_url = gitlab_url.rstrip("/")

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float | None = None

        self._validate_settings()

    def _validate_settings(self) -> None:
        """Ensure required OAuth settings are present."""
        if not self._client_id:
            raise AuthenticationError(
                "OAuth client_id is required. Set MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID."
            )
        if self._client_secret is None:
            raise AuthenticationError(
                "OAuth client_secret is required. Set MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET."
            )
        secret_value = self._client_secret.get_secret_value()
        if not secret_value or not secret_value.strip():
            raise AuthenticationError(
                "OAuth client_secret is empty or whitespace-only. "
                "Set MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET to a valid secret."
            )

    def get_headers(self) -> dict[str, str]:
        """Return the Authorization: Bearer header for API requests.

        Returns an empty dict if no token has been obtained yet.
        """
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    @property
    def is_token_expired(self) -> bool:
        """Check whether the current access token has expired or is missing."""
        if self._access_token is None or self._expires_at is None:
            return True
        return time.monotonic() >= (self._expires_at - self._EXPIRY_BUFFER_SECONDS)

    async def _obtain_token(self, client: httpx.AsyncClient) -> None:
        """Obtain a new access token via the client credentials flow.

        Posts to ``{gitlab_url}/oauth/token`` with ``grant_type=client_credentials``.

        Args:
            client: An httpx.AsyncClient (does not need auth headers).

        Raises:
            AuthenticationError: If the token request fails.
        """
        assert self._client_secret is not None  # guarded by _validate_settings
        token_url = f"{self._gitlab_url}/oauth/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret.get_secret_value(),
        }

        try:
            response = await client.post(token_url, data=payload)
        except httpx.ConnectError as exc:
            raise AuthenticationError(
                f"Cannot reach GitLab OAuth endpoint at {self._gitlab_url}. "
                "Check network connectivity and the MAMBA_MCP_GITLAB_URL setting."
            ) from exc
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                f"HTTP error during OAuth token request to {self._gitlab_url}: {exc}"
            ) from exc

        if response.status_code == 401:
            raise AuthenticationError(
                "OAuth client credentials are invalid. "
                "Check MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID and "
                "MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET."
            )

        if response.status_code != 200:
            raise AuthenticationError(
                f"OAuth token request failed (HTTP {response.status_code}). "
                "Verify OAuth application configuration in GitLab."
            )

        data = response.json()

        access_token = data.get("access_token")
        if not access_token:
            raise AuthenticationError(
                "OAuth token response missing 'access_token'. "
                "Verify GitLab OAuth application configuration."
            )

        self._access_token = access_token
        self._refresh_token = data.get("refresh_token")

        # Calculate absolute expiry time from the 'expires_in' field
        expires_in = data.get("expires_in")
        if expires_in is not None:
            self._expires_at = time.monotonic() + float(expires_in)
        else:
            # No expiry reported; assume token does not expire
            self._expires_at = None

        logger.debug("OAuth access token obtained (expires_in=%s)", expires_in)

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> None:
        """Refresh the access token using the stored refresh token.

        Falls back to a full re-authentication if refresh fails or
        no refresh token is available.

        Args:
            client: An httpx.AsyncClient.

        Raises:
            AuthenticationError: If both refresh and re-authentication fail.
        """
        if not self._refresh_token:
            # No refresh token available; re-obtain via client credentials
            await self._obtain_token(client)
            return

        assert self._client_secret is not None
        token_url = f"{self._gitlab_url}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret.get_secret_value(),
        }

        try:
            response = await client.post(token_url, data=payload)
        except httpx.HTTPError:
            logger.warning(
                "OAuth token refresh failed due to HTTP error; attempting full re-authentication."
            )
            await self._obtain_token(client)
            return

        if response.status_code != 200:
            logger.warning(
                "OAuth token refresh returned HTTP %s; attempting full re-authentication.",
                response.status_code,
            )
            # Clear the stale refresh token so the fallback uses client credentials
            self._refresh_token = None
            await self._obtain_token(client)
            return

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            logger.warning(
                "OAuth refresh response missing 'access_token'; attempting full re-authentication."
            )
            self._refresh_token = None
            await self._obtain_token(client)
            return

        self._access_token = access_token
        self._refresh_token = data.get("refresh_token", self._refresh_token)

        expires_in = data.get("expires_in")
        if expires_in is not None:
            self._expires_at = time.monotonic() + float(expires_in)
        else:
            self._expires_at = None

        logger.debug("OAuth access token refreshed (expires_in=%s)", expires_in)

    async def ensure_valid_token(self, client: httpx.AsyncClient) -> None:
        """Ensure the access token is valid, refreshing or re-obtaining if needed.

        Args:
            client: An httpx.AsyncClient.

        Raises:
            AuthenticationError: If token cannot be obtained or refreshed.
        """
        if not self.is_token_expired:
            return

        if self._access_token is not None:
            # Token exists but expired; try refresh
            await self._refresh_access_token(client)
        else:
            # No token yet; obtain one
            await self._obtain_token(client)

    async def validate(self, client: httpx.AsyncClient) -> AuthInfo:
        """Obtain an OAuth token and validate it via the GitLab user endpoint.

        Calls ``GET /api/v4/user`` with the Bearer token to verify that
        the token is valid and retrieve user information.

        Args:
            client: An httpx.AsyncClient configured with the GitLab base URL.

        Returns:
            AuthInfo with username from the ``/api/v4/user`` response.

        Raises:
            AuthenticationError: If token acquisition or validation fails.
        """
        # Obtain token (first time)
        await self.ensure_valid_token(client)

        # Validate via /api/v4/user
        try:
            response = await client.get(
                f"{self._gitlab_url}/api/v4/user",
                headers=self.get_headers(),
            )
        except httpx.ConnectError as exc:
            raise AuthenticationError(
                f"Cannot reach GitLab at {self._gitlab_url}. "
                "Check network connectivity and the MAMBA_MCP_GITLAB_URL setting."
            ) from exc
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                f"HTTP error validating OAuth token at {self._gitlab_url}: {exc}"
            ) from exc

        if response.status_code == 401:
            raise AuthenticationError(
                "OAuth access token is invalid or expired after acquisition. "
                "Check OAuth application permissions in GitLab."
            )

        if response.status_code != 200:
            raise AuthenticationError(
                f"Unexpected response from GitLab user endpoint "
                f"(HTTP {response.status_code}). Check GitLab server status."
            )

        data = response.json()
        username = data.get("username", "unknown")

        return AuthInfo(
            auth_type="oauth",
            username=username,
            scopes=[],
            expires_at=None,
        )


def detect_auth_strategy(settings: Settings) -> AuthStrategy:
    """Detect and return the appropriate auth strategy from settings.

    Resolution order (PAT takes precedence):
    1. If settings.gitlab.token is set -> PATAuthStrategy
    2. If settings.oauth has credentials -> OAuthAuthStrategy
    3. Neither configured -> raise AuthenticationError

    Args:
        settings: The root Settings instance.

    Returns:
        An AuthStrategy implementation.

    Raises:
        AuthenticationError: If no authentication method is configured.
    """
    # PAT takes precedence
    if settings.gitlab.token is not None:
        token_value = settings.gitlab.token.get_secret_value()
        if token_value and token_value.strip():
            return PATAuthStrategy(settings.gitlab.token)

    # Check for OAuth credentials
    if settings.oauth.client_id is not None and settings.oauth.client_secret is not None:
        return OAuthAuthStrategy(
            oauth_settings=settings.oauth,
            gitlab_url=settings.gitlab.url,
        )

    raise AuthenticationError(
        "No authentication configured. Set MAMBA_MCP_GITLAB_TOKEN for PAT authentication, "
        "or configure OAuth 2.0 credentials (MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID, "
        "MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET)."
    )


__all__ = [
    "AuthInfo",
    "AuthStrategy",
    "AuthenticationError",
    "OAuthAuthStrategy",
    "PATAuthStrategy",
    "REQUIRED_SCOPES",
    "detect_auth_strategy",
]
