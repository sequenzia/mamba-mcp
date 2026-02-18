"""Pytest fixtures for GitLab MCP Server tests.

Provides shared fixtures for configuration, HTTP mocking, and service
construction used across all test modules.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from mamba_mcp_gitlab.auth import AuthInfo, PATAuthStrategy
from mamba_mcp_gitlab.config import (
    GitLabSettings,
    OAuthSettings,
    RateLimitSettings,
    ServerSettings,
    Settings,
    set_env_file_path,
)
from mamba_mcp_gitlab.services.base import GitLabService
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Default test values
# ---------------------------------------------------------------------------

TEST_GITLAB_URL = "https://gitlab.example.com"
TEST_TOKEN = "glpat-test-token-xxxxxxxxxxxx"
TEST_USERNAME = "testuser"


# ---------------------------------------------------------------------------
# Environment state isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_env_file_path() -> Generator[None, None, None]:
    """Reset env file path state before and after each test."""
    set_env_file_path(None)
    yield
    set_env_file_path(None)


# ---------------------------------------------------------------------------
# Settings factories
# ---------------------------------------------------------------------------


@pytest.fixture
def gitlab_settings() -> GitLabSettings:
    """Create test GitLab settings with sensible defaults."""
    return GitLabSettings(
        url=TEST_GITLAB_URL,
        token=SecretStr(TEST_TOKEN),
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def oauth_settings() -> OAuthSettings:
    """Create test OAuth settings (empty by default)."""
    return OAuthSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def server_settings() -> ServerSettings:
    """Create test server settings with defaults."""
    return ServerSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def rate_limit_settings() -> RateLimitSettings:
    """Create test rate limit settings with defaults."""
    return RateLimitSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def mock_settings(
    gitlab_settings: GitLabSettings,
    oauth_settings: OAuthSettings,
    server_settings: ServerSettings,
    rate_limit_settings: RateLimitSettings,
) -> Settings:
    """Create a complete test Settings instance with all sub-settings.

    Uses the individual settings fixtures, which can be overridden
    independently in specific tests.
    """
    return Settings(
        gitlab=gitlab_settings,
        oauth=oauth_settings,
        server=server_settings,
        rate_limit=rate_limit_settings,
    )


def make_settings(
    *,
    url: str = TEST_GITLAB_URL,
    token: str | None = TEST_TOKEN,
    default_project_id: int | None = None,
    default_group_id: int | None = None,
    read_only: bool = False,
    verify_ssl: bool = True,
) -> Settings:
    """Factory function to create Settings instances with custom overrides.

    This is a plain function (not a fixture) so it can be called with
    arbitrary parameters in any test without fixture dependency.

    Args:
        url: GitLab instance URL.
        token: Personal Access Token (None to leave unset).
        default_project_id: Default project scope.
        default_group_id: Default group scope.
        read_only: Whether the server runs in read-only mode.
        verify_ssl: Whether to verify SSL certificates.

    Returns:
        A fully constructed Settings instance suitable for testing.
    """
    return Settings(
        gitlab=GitLabSettings(
            url=url,
            token=SecretStr(token) if token else None,
            default_project_id=default_project_id,
            default_group_id=default_group_id,
            read_only=read_only,
            verify_ssl=verify_ssl,
            _env_file=None,  # type: ignore[call-arg]
        ),
        oauth=OAuthSettings(_env_file=None),  # type: ignore[call-arg]
        server=ServerSettings(_env_file=None),  # type: ignore[call-arg]
        rate_limit=RateLimitSettings(_env_file=None),  # type: ignore[call-arg]
    )


# ---------------------------------------------------------------------------
# Mock AppContext (matches the spec Section 7.5 AppContext dataclass)
# ---------------------------------------------------------------------------


@dataclass
class MockAppContext:
    """Mock AppContext for testing tool handlers.

    Mirrors the AppContext structure from spec Section 7.5:
    - client: httpx.AsyncClient with connection pooling
    - settings: Server configuration
    - auth_strategy: Active auth strategy
    - auth_info: Validated auth details

    Also provides a pre-built GitLabService for service-layer tests.
    """

    client: httpx.AsyncClient
    settings: Settings
    auth_strategy: PATAuthStrategy
    auth_info: AuthInfo
    services: dict[str, Any] = field(default_factory=dict)

    @property
    def gitlab_service(self) -> GitLabService:
        """Get or create a GitLabService using this context's client and settings."""
        if "gitlab" not in self.services:
            self.services["gitlab"] = GitLabService(
                http_client=self.client,
                settings=self.settings,
            )
        return self.services["gitlab"]


@pytest.fixture
def mock_app_context(mock_settings: Settings) -> MockAppContext:
    """Create a MockAppContext with a real httpx.AsyncClient for respx mocking.

    The client is created without a base URL so that respx can intercept
    fully-qualified URLs (e.g., https://gitlab.example.com/api/v4/...).

    Usage with respx:
        @respx.mock
        def test_something(mock_app_context):
            respx.get("https://gitlab.example.com/api/v4/projects").respond(200, json=[])
            service = mock_app_context.gitlab_service
            ...
    """
    client = httpx.AsyncClient(
        headers={"PRIVATE-TOKEN": TEST_TOKEN},
    )
    auth_strategy = PATAuthStrategy(SecretStr(TEST_TOKEN))
    auth_info = AuthInfo(
        auth_type="pat",
        username=TEST_USERNAME,
        scopes=["api"],
        expires_at="2027-12-31",
    )
    return MockAppContext(
        client=client,
        settings=mock_settings,
        auth_strategy=auth_strategy,
        auth_info=auth_info,
    )


# ---------------------------------------------------------------------------
# HTTP mock helpers
# ---------------------------------------------------------------------------


def make_gitlab_api_response(
    *,
    status_code: int = 200,
    json: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a mock httpx.Response for testing service methods.

    Args:
        status_code: HTTP status code.
        json: JSON response body.
        headers: Additional response headers.

    Returns:
        An httpx.Response ready for use with MockTransport or assertions.
    """
    return httpx.Response(
        status_code=status_code,
        json=json if json is not None else {},
        headers=headers or {},
    )


def make_paginated_headers(total: int = 50, total_pages: int = 3) -> dict[str, str]:
    """Create GitLab pagination response headers.

    Args:
        total: Total number of items across all pages.
        total_pages: Total number of pages.

    Returns:
        Dict with x-total and x-total-pages headers.
    """
    return {
        "x-total": str(total),
        "x-total-pages": str(total_pages),
    }
