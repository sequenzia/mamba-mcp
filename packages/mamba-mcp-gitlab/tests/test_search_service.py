"""Tests for the SearchService (services/search_service.py).

Covers the search method with instance-wide, project-scoped, and group-scoped
endpoint routing, scope validation, pagination, default settings fallback,
rate limit error remapping, and edge cases.
"""

import httpx
import pytest
import respx
from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.search_service import VALID_SCOPES, SearchService

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


def _make_service(
    client: httpx.AsyncClient | None = None,
    url: str = GITLAB_URL,
    default_project_id: int | None = None,
    default_group_id: int | None = None,
) -> SearchService:
    """Create a SearchService instance for testing."""
    settings = _make_settings(
        url=url,
        default_project_id=default_project_id,
        default_group_id=default_group_id,
    )
    http_client = client or httpx.AsyncClient()
    return SearchService(http_client=http_client, settings=settings)


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


class TestSearchInstanceWide:
    """Tests for instance-wide search (no project or group scope)."""

    @respx.mock
    async def test_instance_search_issues(self) -> None:
        """Test that instance-wide search calls GET /search with correct params."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[SAMPLE_ISSUE_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="bug", scope="issues")

        assert route.called
        assert result["items"] == [SAMPLE_ISSUE_RESULT]
        assert result["total"] == 1
        assert result["total_pages"] == 1
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert result["query"] == "bug"
        assert result["scope"] == "issues"

    @respx.mock
    async def test_instance_search_merge_requests(self) -> None:
        """Test that instance-wide search works for merge_requests scope."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[SAMPLE_MR_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="feature", scope="merge_requests")

        assert route.called
        assert result["items"] == [SAMPLE_MR_RESULT]
        assert result["scope"] == "merge_requests"

    @respx.mock
    async def test_instance_search_projects(self) -> None:
        """Test that instance-wide search works for projects scope."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[SAMPLE_PROJECT_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="my-project", scope="projects")

        assert route.called
        assert result["items"] == [SAMPLE_PROJECT_RESULT]
        assert result["scope"] == "projects"

    @respx.mock
    async def test_instance_search_passes_query_and_scope_params(self) -> None:
        """Test that search and scope query params are included in request."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.search(query="test query", scope="issues")

        request = route.calls[0].request
        raw_path = request.url.raw_path.decode()
        assert "search=" in raw_path
        assert "scope=issues" in raw_path


class TestSearchProjectScoped:
    """Tests for project-scoped search."""

    @respx.mock
    async def test_project_search_with_integer_id(self) -> None:
        """Test project-scoped search calls GET /projects/{id}/search."""
        route = respx.get(f"{BASE_API}/projects/42/search").respond(
            200,
            json=[SAMPLE_ISSUE_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="bug", scope="issues", project_id=42)

        assert route.called
        assert result["items"] == [SAMPLE_ISSUE_RESULT]

    @respx.mock
    async def test_project_search_with_string_path(self) -> None:
        """Test project-scoped search URL-encodes string project paths."""
        route = respx.get(f"{BASE_API}/projects/group%2Fsubgroup%2Fproject/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.search(query="test", scope="issues", project_id="group/subgroup/project")

        assert route.called

    @respx.mock
    async def test_project_id_takes_precedence_over_group_id(self) -> None:
        """Test that project_id takes precedence when both are provided."""
        route = respx.get(f"{BASE_API}/projects/42/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )
        # Group route should NOT be called
        group_route = respx.get(f"{BASE_API}/groups/10/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.search(query="test", scope="issues", project_id=42, group_id=10)

        assert route.called
        assert not group_route.called


class TestSearchGroupScoped:
    """Tests for group-scoped search."""

    @respx.mock
    async def test_group_search(self) -> None:
        """Test group-scoped search calls GET /groups/{id}/search."""
        route = respx.get(f"{BASE_API}/groups/10/search").respond(
            200,
            json=[SAMPLE_ISSUE_RESULT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="bug", scope="issues", group_id=10)

        assert route.called
        assert result["items"] == [SAMPLE_ISSUE_RESULT]


class TestSearchDefaultScoping:
    """Tests for default project/group scoping from settings."""

    @respx.mock
    async def test_uses_default_project_id_when_no_explicit_scope(self) -> None:
        """Test that default_project_id from settings is used when nothing explicit."""
        route = respx.get(f"{BASE_API}/projects/99/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.search(query="test", scope="issues")

        assert route.called

    @respx.mock
    async def test_uses_default_group_id_when_no_project_default(self) -> None:
        """Test that default_group_id from settings is used when no project default."""
        route = respx.get(f"{BASE_API}/groups/50/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_group_id=50)
            await service.search(query="test", scope="issues")

        assert route.called

    @respx.mock
    async def test_default_project_id_takes_precedence_over_default_group_id(self) -> None:
        """Test that default project_id beats default group_id."""
        project_route = respx.get(f"{BASE_API}/projects/99/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )
        group_route = respx.get(f"{BASE_API}/groups/50/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99, default_group_id=50)
            await service.search(query="test", scope="issues")

        assert project_route.called
        assert not group_route.called

    @respx.mock
    async def test_explicit_project_overrides_default_project(self) -> None:
        """Test that explicit project_id overrides default_project_id."""
        route = respx.get(f"{BASE_API}/projects/42/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )
        default_route = respx.get(f"{BASE_API}/projects/99/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.search(query="test", scope="issues", project_id=42)

        assert route.called
        assert not default_route.called

    @respx.mock
    async def test_explicit_group_overrides_default_group(self) -> None:
        """Test that explicit group_id overrides default_group_id."""
        route = respx.get(f"{BASE_API}/groups/10/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )
        default_route = respx.get(f"{BASE_API}/groups/50/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_group_id=50)
            await service.search(query="test", scope="issues", group_id=10)

        assert route.called
        assert not default_route.called

    @respx.mock
    async def test_instance_wide_when_no_defaults_and_no_explicit(self) -> None:
        """Test that instance-wide search is used when no scope is provided."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.search(query="test", scope="issues")

        assert route.called


class TestSearchPagination:
    """Tests for search pagination."""

    @respx.mock
    async def test_passes_pagination_params(self) -> None:
        """Test that page and per_page are included in query params."""
        route = respx.get(f"{BASE_API}/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.search(query="test", scope="issues", page=3, per_page=50)

        request = route.calls[0].request
        assert b"page=3" in request.url.raw_path
        assert b"per_page=50" in request.url.raw_path

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that pagination metadata is returned correctly."""
        respx.get(f"{BASE_API}/search").respond(
            200,
            json=[SAMPLE_ISSUE_RESULT, SAMPLE_ISSUE_RESULT],
            headers={"x-total": "15", "x-total-pages": "3"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="bug", scope="issues", page=2, per_page=5)

        assert result["page"] == 2
        assert result["per_page"] == 5
        assert result["total"] == 15
        assert result["total_pages"] == 3


class TestSearchScopeValidation:
    """Tests for search scope validation."""

    async def test_invalid_scope_raises_validation_error(self) -> None:
        """Test that an invalid scope raises VALIDATION_ERROR."""
        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="invalid_scope")

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert "invalid_scope" in str(exc_info.value)
        assert "issues" in str(exc_info.value)
        assert "merge_requests" in str(exc_info.value)
        assert "projects" in str(exc_info.value)

    async def test_empty_scope_raises_validation_error(self) -> None:
        """Test that an empty scope raises VALIDATION_ERROR."""
        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="")

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    def test_valid_scopes_constant(self) -> None:
        """Test that VALID_SCOPES contains all expected values."""
        assert VALID_SCOPES == {"issues", "merge_requests", "projects"}


class TestSearchEmptyResults:
    """Tests for empty search results."""

    @respx.mock
    async def test_empty_results_returns_empty_list_with_metadata(self) -> None:
        """Test that empty search results return an empty list with search metadata."""
        respx.get(f"{BASE_API}/search").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.search(query="nonexistent", scope="issues")

        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 0
        assert result["query"] == "nonexistent"
        assert result["scope"] == "issues"


class TestSearchErrorHandling:
    """Tests for error handling in search operations."""

    @respx.mock
    async def test_rate_limited_remapped(self) -> None:
        """Test that 429 is remapped to RATE_LIMITED error code."""
        respx.get(f"{BASE_API}/search").respond(429, json={"message": "429 Too Many Requests"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="issues")

        assert exc_info.value.error_code == ErrorCode.RATE_LIMITED
        assert exc_info.value.status_code == 429

    @respx.mock
    async def test_auth_error_propagated(self) -> None:
        """Test that 401 errors propagate with AUTH_FAILED error code."""
        respx.get(f"{BASE_API}/search").respond(401, json={"message": "401 Unauthorized"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="issues")

        assert exc_info.value.error_code == ErrorCode.AUTH_FAILED
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_server_error_propagated(self) -> None:
        """Test that 500 errors propagate with API_ERROR error code."""
        respx.get(f"{BASE_API}/search").respond(500, json={"error": "Internal Server Error"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="issues")

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_connection_error_propagated(self) -> None:
        """Test that connection errors propagate with CONNECTION_ERROR code."""
        respx.get(f"{BASE_API}/search").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="issues")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_timeout_error_propagated(self) -> None:
        """Test that timeout errors propagate with CONNECTION_ERROR code."""
        respx.get(f"{BASE_API}/search").mock(side_effect=httpx.ConnectTimeout("timed out"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="issues")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_non_429_error_not_remapped_to_rate_limited(self) -> None:
        """Test that non-429 errors are not remapped to RATE_LIMITED."""
        respx.get(f"{BASE_API}/projects/42/search").respond(403, json={"message": "403 Forbidden"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.search(query="test", scope="issues", project_id=42)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert exc_info.value.status_code == 403
