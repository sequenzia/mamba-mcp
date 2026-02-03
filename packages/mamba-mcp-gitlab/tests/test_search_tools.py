"""Tests for the search tool handler (tools/search_tools.py).

Covers the search tool's 7-step handler skeleton: context null check,
service delegation, output model conversion, GitLabAPIError handling,
and unexpected exception handling. Uses mock AppContext and respx for
HTTP mocking.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import httpx
import respx
from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.models.search import SearchOutput
from mamba_mcp_gitlab.server import AppContext
from mamba_mcp_gitlab.tools.search_tools import search

GITLAB_URL = "https://gitlab.example.com"
BASE_API = f"{GITLAB_URL}/api/v4"


def _make_settings(
    url: str = GITLAB_URL,
    default_project_id: int | None = None,
    default_group_id: int | None = None,
) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        gitlab={  # type: ignore[arg-type]
            "url": url,
            "token": "glpat-test-token",
            "default_project_id": default_project_id,
            "default_group_id": default_group_id,
        },
        oauth={},  # type: ignore[arg-type]
        server={},  # type: ignore[arg-type]
        rate_limit={},  # type: ignore[arg-type]
    )


@dataclass
class FakeRequestContext:
    """Fake request context to simulate MCP context structure."""

    lifespan_context: AppContext


@dataclass
class FakeContext:
    """Fake MCP Context for testing tool handlers."""

    request_context: FakeRequestContext


def _make_ctx(
    client: httpx.AsyncClient,
    settings: Settings | None = None,
) -> FakeContext:
    """Create a FakeContext wrapping an AppContext for tool tests."""
    if settings is None:
        settings = _make_settings()
    app_ctx = AppContext(
        client=client,
        settings=settings,
        rate_limiter=None,
        auth_info=MagicMock(),
    )
    return FakeContext(request_context=FakeRequestContext(lifespan_context=app_ctx))


SAMPLE_ISSUE_RESULT = {
    "id": 101,
    "iid": 1,
    "title": "Fix login bug",
    "state": "opened",
    "web_url": "https://gitlab.example.com/project/issues/1",
}

SAMPLE_MR_RESULT = {
    "id": 201,
    "iid": 5,
    "title": "Add feature X",
    "state": "opened",
    "web_url": "https://gitlab.example.com/project/merge_requests/5",
}

SAMPLE_PROJECT_RESULT = {
    "id": 42,
    "name": "my-project",
    "path_with_namespace": "group/my-project",
    "web_url": "https://gitlab.example.com/group/my-project",
}


class TestSearchToolContextCheck:
    """Tests for search tool context null check."""

    async def test_returns_error_when_context_is_none(self) -> None:
        """Test that a CONNECTION_ERROR is returned when ctx is None."""
        result = await search(query="test", scope="issues", ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "No context available" in result["message"]


class TestSearchToolSuccess:
    """Tests for successful search tool invocations."""

    @respx.mock
    async def test_instance_search_returns_search_output(self) -> None:
        """Test that a successful search returns SearchOutput model."""
        respx.get(f"{BASE_API}/search").respond(
            200,
            json=[SAMPLE_ISSUE_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="bug", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, SearchOutput)
        assert len(result.items) == 1
        assert result.items[0].type == "issues"
        assert result.items[0].data == SAMPLE_ISSUE_RESULT
        assert result.query == "bug"
        assert result.scope == "issues"
        assert result.page == 1
        assert result.per_page == 20
        assert result.total == 1
        assert result.total_pages == 1

    @respx.mock
    async def test_project_scoped_search(self) -> None:
        """Test that project-scoped search routes correctly."""
        route = respx.get(f"{BASE_API}/projects/42/search").respond(
            200,
            json=[SAMPLE_MR_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(
                query="feature",
                scope="merge_requests",
                project_id=42,
                ctx=ctx,  # type: ignore[arg-type]
            )

        assert route.called
        assert isinstance(result, SearchOutput)
        assert result.items[0].type == "merge_requests"
        assert result.scope == "merge_requests"

    @respx.mock
    async def test_group_scoped_search(self) -> None:
        """Test that group-scoped search routes correctly."""
        route = respx.get(f"{BASE_API}/groups/10/search").respond(
            200,
            json=[SAMPLE_PROJECT_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(
                query="project",
                scope="projects",
                group_id=10,
                ctx=ctx,  # type: ignore[arg-type]
            )

        assert route.called
        assert isinstance(result, SearchOutput)
        assert result.items[0].type == "projects"

    @respx.mock
    async def test_empty_results(self) -> None:
        """Test that empty search results return SearchOutput with empty items."""
        respx.get(f"{BASE_API}/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="nonexistent", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, SearchOutput)
        assert result.items == []
        assert result.total == 0
        assert result.query == "nonexistent"
        assert result.scope == "issues"

    @respx.mock
    async def test_pagination_clamped(self) -> None:
        """Test that pagination parameters are clamped to valid range."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            # Negative page should be clamped to 1, per_page over 100 clamped to 100
            await search(
                query="test",
                scope="issues",
                page=-1,
                per_page=200,
                ctx=ctx,  # type: ignore[arg-type]
            )

        request = route.calls[0].request
        assert b"page=1" in request.url.raw_path
        assert b"per_page=100" in request.url.raw_path


class TestSearchToolDefaultScoping:
    """Tests for default project/group scoping in the tool handler."""

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id from settings is used."""
        route = respx.get(f"{BASE_API}/projects/99/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        settings = _make_settings(default_project_id=99)
        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client, settings=settings)
            await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert route.called

    @respx.mock
    async def test_uses_default_group_id(self) -> None:
        """Test that default_group_id from settings is used."""
        route = respx.get(f"{BASE_API}/groups/50/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        settings = _make_settings(default_group_id=50)
        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client, settings=settings)
            await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert route.called


class TestSearchToolErrorHandling:
    """Tests for error handling in the search tool handler."""

    @respx.mock
    async def test_invalid_scope_returns_error_dict(self) -> None:
        """Test that invalid scope returns error dict with VALIDATION_ERROR."""
        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="test", scope="invalid", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.VALIDATION_ERROR
        assert "invalid" in result["message"]

    @respx.mock
    async def test_rate_limited_returns_error_dict(self) -> None:
        """Test that 429 returns error dict with RATE_LIMITED code."""
        respx.get(f"{BASE_API}/search").respond(429, json={"message": "429 Too Many Requests"})

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.RATE_LIMITED

    @respx.mock
    async def test_auth_error_returns_error_dict(self) -> None:
        """Test that 401 returns error dict with AUTH_FAILED code."""
        respx.get(f"{BASE_API}/search").respond(401, json={"message": "401 Unauthorized"})

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.AUTH_FAILED

    @respx.mock
    async def test_connection_error_returns_error_dict(self) -> None:
        """Test that connection errors return error dict with CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/search").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_error_includes_input_received(self) -> None:
        """Test that error dicts include the input parameters."""
        respx.get(f"{BASE_API}/search").respond(500, json={"error": "Internal Server Error"})

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(
                query="test",
                scope="issues",
                project_id=42,
                group_id=10,
                ctx=ctx,  # type: ignore[arg-type]
            )

        assert isinstance(result, dict)
        assert result["input_received"]["query"] == "test"
        assert result["input_received"]["scope"] == "issues"
        assert result["input_received"]["project_id"] == 42
        assert result["input_received"]["group_id"] == 10

    @respx.mock
    async def test_error_includes_context_with_elapsed_ms(self) -> None:
        """Test that error dicts include timing context."""
        respx.get(f"{BASE_API}/search").respond(500, json={"error": "Internal Server Error"})

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, dict)
        assert "elapsed_ms" in result.get("context", {})

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        # Create a mock client that raises when used
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = MagicMock(side_effect=RuntimeError("unexpected"))

        settings = _make_settings()
        app_ctx = AppContext(
            client=mock_client,
            settings=settings,
            rate_limiter=None,
            auth_info=MagicMock(),
        )
        ctx = FakeContext(request_context=FakeRequestContext(lifespan_context=app_ctx))

        result = await search(query="test", scope="issues", ctx=ctx)  # type: ignore[arg-type]

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


class TestSearchToolProjectGroupPrecedence:
    """Tests for project_id vs group_id precedence in the tool handler."""

    @respx.mock
    async def test_project_id_takes_precedence(self) -> None:
        """Test that project_id beats group_id when both are provided."""
        project_route = respx.get(f"{BASE_API}/projects/42/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )
        group_route = respx.get(f"{BASE_API}/groups/10/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            ctx = _make_ctx(client)
            result = await search(
                query="test",
                scope="issues",
                project_id=42,
                group_id=10,
                ctx=ctx,  # type: ignore[arg-type]
            )

        assert isinstance(result, SearchOutput)
        assert project_route.called
        assert not group_route.called
