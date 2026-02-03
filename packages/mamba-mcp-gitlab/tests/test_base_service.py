"""Tests for the base service class (services/base.py).

Covers HTTP methods, error mapping, pagination, URL construction,
project ID resolution, and connection error handling.
"""

import httpx
import pytest
import respx
from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import (
    GitLabAPIError,
    GitLabService,
    _map_status_to_error_code,
    _parse_json_body,
    _safe_int,
)

GITLAB_URL = "https://gitlab.example.com"
BASE_API = f"{GITLAB_URL}/api/v4"


def _make_settings(
    url: str = GITLAB_URL,
    default_project_id: int | None = None,
) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        gitlab={  # type: ignore[arg-type]
            "url": url,
            "token": "glpat-test-token",
            "default_project_id": default_project_id,
        },
        oauth={},  # type: ignore[arg-type]
        server={},  # type: ignore[arg-type]
        rate_limit={},  # type: ignore[arg-type]
    )


def _make_service(
    client: httpx.AsyncClient | None = None,
    url: str = GITLAB_URL,
    default_project_id: int | None = None,
) -> GitLabService:
    """Create a GitLabService instance for testing."""
    settings = _make_settings(url=url, default_project_id=default_project_id)
    http_client = client or httpx.AsyncClient()
    return GitLabService(http_client=http_client, settings=settings)


class TestGitLabAPIError:
    """Tests for GitLabAPIError exception class."""

    def test_error_with_all_fields(self) -> None:
        """Test that GitLabAPIError stores all provided fields."""
        err = GitLabAPIError(
            message="Not found",
            error_code=ErrorCode.NOT_FOUND,
            status_code=404,
            response_body={"message": "Not found"},
        )
        assert str(err) == "Not found"
        assert err.error_code == ErrorCode.NOT_FOUND
        assert err.status_code == 404
        assert err.response_body == {"message": "Not found"}

    def test_error_with_minimal_fields(self) -> None:
        """Test that GitLabAPIError works with only required fields."""
        err = GitLabAPIError(
            message="Connection lost",
            error_code=ErrorCode.CONNECTION_ERROR,
        )
        assert str(err) == "Connection lost"
        assert err.error_code == ErrorCode.CONNECTION_ERROR
        assert err.status_code is None
        assert err.response_body is None

    def test_error_is_exception_subclass(self) -> None:
        """Test that GitLabAPIError is a proper Exception subclass."""
        err = GitLabAPIError(message="test", error_code="TEST")
        assert isinstance(err, Exception)


class TestStatusCodeMapping:
    """Tests for HTTP status code to ErrorCode mapping."""

    @pytest.mark.parametrize(
        ("status_code", "expected_code"),
        [
            (400, ErrorCode.VALIDATION_ERROR),
            (401, ErrorCode.AUTH_FAILED),
            (403, ErrorCode.FORBIDDEN),
            (404, ErrorCode.NOT_FOUND),
            (429, ErrorCode.RATE_LIMITED),
        ],
    )
    def test_known_status_codes(self, status_code: int, expected_code: str) -> None:
        """Test that known HTTP status codes map to the correct error codes."""
        assert _map_status_to_error_code(status_code) == expected_code

    @pytest.mark.parametrize("status_code", [500, 502, 503, 504, 599])
    def test_5xx_maps_to_api_error(self, status_code: int) -> None:
        """Test that all 5xx status codes map to API_ERROR."""
        assert _map_status_to_error_code(status_code) == ErrorCode.API_ERROR

    def test_unknown_4xx_maps_to_api_error(self) -> None:
        """Test that unmapped 4xx status codes default to API_ERROR."""
        assert _map_status_to_error_code(418) == ErrorCode.API_ERROR


class TestSafeInt:
    """Tests for _safe_int helper."""

    def test_valid_integer_string(self) -> None:
        """Test parsing a valid integer string."""
        assert _safe_int("42") == 42

    def test_none_returns_zero(self) -> None:
        """Test that None returns 0."""
        assert _safe_int(None) == 0

    def test_empty_string_returns_zero(self) -> None:
        """Test that an empty string returns 0."""
        assert _safe_int("") == 0

    def test_non_numeric_returns_zero(self) -> None:
        """Test that a non-numeric string returns 0."""
        assert _safe_int("abc") == 0


class TestParseJsonBody:
    """Tests for _parse_json_body helper."""

    def test_valid_json(self) -> None:
        """Test parsing a valid JSON response body."""
        response = httpx.Response(200, json={"key": "value"})
        assert _parse_json_body(response) == {"key": "value"}

    def test_empty_body_returns_empty_dict(self) -> None:
        """Test that an empty response body returns an empty dict."""
        response = httpx.Response(200, content=b"")
        assert _parse_json_body(response) == {}

    def test_non_json_body_returns_empty_dict(self) -> None:
        """Test that a non-JSON response body returns an empty dict."""
        response = httpx.Response(
            200, content=b"<html>Not JSON</html>", headers={"content-type": "text/html"}
        )
        assert _parse_json_body(response) == {}


class TestGitLabServiceConstructor:
    """Tests for GitLabService constructor."""

    def test_base_url_computed_from_settings(self) -> None:
        """Test that base_url is computed from settings.gitlab.url + /api/v4."""
        service = _make_service(url="https://gitlab.example.com")
        assert service.base_url == "https://gitlab.example.com/api/v4"

    def test_base_url_strips_trailing_slash(self) -> None:
        """Test that trailing slash is stripped from URL before appending /api/v4."""
        service = _make_service(url="https://gitlab.example.com/")
        assert service.base_url == "https://gitlab.example.com/api/v4"

    def test_stores_http_client(self) -> None:
        """Test that http_client is stored on the instance."""
        client = httpx.AsyncClient()
        service = _make_service(client=client)
        assert service.http_client is client

    def test_stores_settings(self) -> None:
        """Test that settings is stored on the instance."""
        service = _make_service()
        assert isinstance(service.settings, Settings)


class TestBuildProjectUrl:
    """Tests for _build_project_url helper method."""

    def test_integer_project_id(self) -> None:
        """Test URL construction with an integer project ID."""
        service = _make_service()
        url = service._build_project_url(123, "merge_requests")
        assert url == "/projects/123/merge_requests"

    def test_string_project_path_is_url_encoded(self) -> None:
        """Test URL construction with a string project path that gets URL-encoded."""
        service = _make_service()
        url = service._build_project_url("group/subgroup/project", "merge_requests")
        assert url == "/projects/group%2Fsubgroup%2Fproject/merge_requests"

    def test_already_encoded_path_is_double_encoded(self) -> None:
        """Test that already URL-encoded paths are encoded again (correct behavior)."""
        service = _make_service()
        url = service._build_project_url("group%2Fproject", "issues")
        assert url == "/projects/group%252Fproject/issues"

    def test_nested_resource_path(self) -> None:
        """Test URL construction with a nested resource path."""
        service = _make_service()
        url = service._build_project_url(42, "merge_requests/1/diffs")
        assert url == "/projects/42/merge_requests/1/diffs"


class TestResolveProjectId:
    """Tests for _resolve_project_id helper method."""

    def test_explicit_integer_id_returned(self) -> None:
        """Test that an explicitly provided integer project ID is returned as-is."""
        service = _make_service()
        assert service._resolve_project_id(123) == 123

    def test_explicit_string_id_returned(self) -> None:
        """Test that an explicitly provided string project path is returned as-is."""
        service = _make_service()
        assert service._resolve_project_id("group/project") == "group/project"

    def test_falls_back_to_default_project_id(self) -> None:
        """Test that None falls back to the configured default_project_id."""
        service = _make_service(default_project_id=999)
        assert service._resolve_project_id(None) == 999

    def test_raises_when_no_id_and_no_default(self) -> None:
        """Test that GitLabAPIError is raised when no project_id and no default."""
        service = _make_service(default_project_id=None)
        with pytest.raises(GitLabAPIError) as exc_info:
            service._resolve_project_id(None)
        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    def test_explicit_id_overrides_default(self) -> None:
        """Test that an explicit project_id takes precedence over default."""
        service = _make_service(default_project_id=999)
        assert service._resolve_project_id(42) == 42


class TestGetMethod:
    """Tests for _get HTTP method."""

    @respx.mock
    async def test_get_returns_json_body(self) -> None:
        """Test that _get returns the parsed JSON response body."""
        respx.get(f"{BASE_API}/projects").respond(200, json={"id": 1, "name": "test"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._get("/projects")

        assert result == {"id": 1, "name": "test"}

    @respx.mock
    async def test_get_with_params(self) -> None:
        """Test that _get passes query parameters correctly."""
        route = respx.get(f"{BASE_API}/projects").respond(200, json=[])

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service._get("/projects", params={"search": "my-project"})

        assert route.called
        request = route.calls[0].request
        assert b"search=my-project" in request.url.raw_path

    @respx.mock
    async def test_get_raises_on_401(self) -> None:
        """Test that _get raises GitLabAPIError with AUTH_FAILED on 401."""
        respx.get(f"{BASE_API}/projects").respond(401, json={"message": "401 Unauthorized"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.AUTH_FAILED
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_get_raises_on_403(self) -> None:
        """Test that _get raises GitLabAPIError with FORBIDDEN on 403."""
        respx.get(f"{BASE_API}/projects").respond(403, json={"message": "403 Forbidden"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert exc_info.value.status_code == 403

    @respx.mock
    async def test_get_raises_on_404(self) -> None:
        """Test that _get raises GitLabAPIError with NOT_FOUND on 404."""
        respx.get(f"{BASE_API}/projects/999").respond(404, json={"message": "404 Not Found"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects/999")

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_get_raises_on_429(self) -> None:
        """Test that _get raises GitLabAPIError with RATE_LIMITED on 429."""
        respx.get(f"{BASE_API}/projects").respond(429, json={"message": "Rate limit exceeded"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.RATE_LIMITED
        assert exc_info.value.status_code == 429

    @respx.mock
    async def test_get_raises_on_500(self) -> None:
        """Test that _get raises GitLabAPIError with API_ERROR on 500."""
        respx.get(f"{BASE_API}/projects").respond(500, json={"error": "Internal Server Error"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_get_handles_empty_response_body(self) -> None:
        """Test that _get handles an empty 200 response body gracefully."""
        respx.get(f"{BASE_API}/projects").respond(200, content=b"")

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._get("/projects")

        assert result == {}

    @respx.mock
    async def test_get_handles_non_json_error_body(self) -> None:
        """Test that _get handles a non-JSON error response body without crashing."""
        respx.get(f"{BASE_API}/projects").respond(
            500, content=b"<html>Server Error</html>", headers={"content-type": "text/html"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_get_connection_timeout(self) -> None:
        """Test that connection timeouts are mapped to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects").mock(side_effect=httpx.ConnectTimeout("timed out"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR
        assert exc_info.value.status_code is None

    @respx.mock
    async def test_get_connection_error(self) -> None:
        """Test that connection errors are mapped to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_get_read_timeout(self) -> None:
        """Test that read timeouts are mapped to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects").mock(side_effect=httpx.ReadTimeout("read timed out"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR


class TestPostMethod:
    """Tests for _post HTTP method."""

    @respx.mock
    async def test_post_sends_json_body(self) -> None:
        """Test that _post sends the JSON body in the request."""
        route = respx.post(f"{BASE_API}/projects/1/issues").respond(201, json={"id": 42, "iid": 1})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._post("/projects/1/issues", json={"title": "Bug report"})

        assert result == {"id": 42, "iid": 1}
        assert route.called
        request = route.calls[0].request
        assert b'"title"' in request.content

    @respx.mock
    async def test_post_without_body(self) -> None:
        """Test that _post works without a JSON body."""
        respx.post(f"{BASE_API}/projects/1/merge_requests/1/merge").respond(
            200, json={"merged": True}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._post("/projects/1/merge_requests/1/merge")

        assert result == {"merged": True}

    @respx.mock
    async def test_post_raises_on_400(self) -> None:
        """Test that _post raises GitLabAPIError with VALIDATION_ERROR on 400."""
        respx.post(f"{BASE_API}/projects/1/issues").respond(
            400, json={"message": {"title": ["can't be blank"]}}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._post("/projects/1/issues", json={"title": ""})

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert exc_info.value.status_code == 400

    @respx.mock
    async def test_post_connection_error(self) -> None:
        """Test that _post connection errors are mapped to CONNECTION_ERROR."""
        respx.post(f"{BASE_API}/projects/1/issues").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._post("/projects/1/issues", json={"title": "test"})

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR


class TestPutMethod:
    """Tests for _put HTTP method."""

    @respx.mock
    async def test_put_sends_json_body(self) -> None:
        """Test that _put sends the JSON body in the request."""
        route = respx.put(f"{BASE_API}/projects/1/issues/1").respond(
            200, json={"id": 1, "title": "Updated"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._put("/projects/1/issues/1", json={"title": "Updated"})

        assert result == {"id": 1, "title": "Updated"}
        assert route.called

    @respx.mock
    async def test_put_without_body(self) -> None:
        """Test that _put works without a JSON body."""
        respx.put(f"{BASE_API}/projects/1/issues/1").respond(200, json={"id": 1})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._put("/projects/1/issues/1")

        assert result == {"id": 1}

    @respx.mock
    async def test_put_raises_on_error(self) -> None:
        """Test that _put raises GitLabAPIError on error status codes."""
        respx.put(f"{BASE_API}/projects/1/issues/1").respond(403, json={"message": "Forbidden"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._put("/projects/1/issues/1", json={"title": "x"})

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert exc_info.value.status_code == 403

    @respx.mock
    async def test_put_connection_error(self) -> None:
        """Test that _put connection errors are mapped to CONNECTION_ERROR."""
        respx.put(f"{BASE_API}/projects/1/issues/1").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._put("/projects/1/issues/1", json={"title": "x"})

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR


class TestGetPaginated:
    """Tests for _get_paginated method."""

    @respx.mock
    async def test_returns_items_total_and_total_pages(self) -> None:
        """Test that _get_paginated returns (items, total, total_pages) tuple."""
        respx.get(f"{BASE_API}/projects/1/issues").respond(
            200,
            json=[{"id": 1}, {"id": 2}],
            headers={"x-total": "50", "x-total-pages": "25"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            items, total, total_pages = await service._get_paginated("/projects/1/issues")

        assert items == [{"id": 1}, {"id": 2}]
        assert total == 50
        assert total_pages == 25

    @respx.mock
    async def test_adds_page_and_per_page_params(self) -> None:
        """Test that page and per_page are added to query parameters."""
        route = respx.get(f"{BASE_API}/projects/1/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service._get_paginated("/projects/1/issues", page=3, per_page=50)

        request = route.calls[0].request
        assert b"page=3" in request.url.raw_path
        assert b"per_page=50" in request.url.raw_path

    @respx.mock
    async def test_merges_additional_params(self) -> None:
        """Test that additional params are merged with pagination params."""
        route = respx.get(f"{BASE_API}/projects/1/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service._get_paginated(
                "/projects/1/issues",
                params={"state": "opened"},
                page=1,
                per_page=20,
            )

        request = route.calls[0].request
        assert b"state=opened" in request.url.raw_path
        assert b"page=1" in request.url.raw_path
        assert b"per_page=20" in request.url.raw_path

    @respx.mock
    async def test_missing_pagination_headers_default_to_zero(self) -> None:
        """Test that missing x-total and x-total-pages headers default to 0."""
        respx.get(f"{BASE_API}/projects/1/issues").respond(
            200,
            json=[{"id": 1}],
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            items, total, total_pages = await service._get_paginated("/projects/1/issues")

        assert items == [{"id": 1}]
        assert total == 0
        assert total_pages == 0

    @respx.mock
    async def test_non_list_response_returns_empty_items(self) -> None:
        """Test that a non-list JSON response returns empty items list."""
        respx.get(f"{BASE_API}/projects/1/issues").respond(
            200,
            json={"message": "unexpected format"},
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            items, total, total_pages = await service._get_paginated("/projects/1/issues")

        assert items == []

    @respx.mock
    async def test_paginated_raises_on_error(self) -> None:
        """Test that _get_paginated raises GitLabAPIError on error status codes."""
        respx.get(f"{BASE_API}/projects/1/issues").respond(404, json={"message": "Not Found"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get_paginated("/projects/1/issues")

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_paginated_connection_error(self) -> None:
        """Test that _get_paginated maps connection errors to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects/1/issues").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get_paginated("/projects/1/issues")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_paginated_generic_http_error(self) -> None:
        """Test that _get_paginated maps generic HTTPError to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects/1/issues").mock(
            side_effect=httpx.HTTPError("something went wrong")
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get_paginated("/projects/1/issues")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_default_page_and_per_page(self) -> None:
        """Test that default page=1 and per_page=20 are used when not specified."""
        route = respx.get(f"{BASE_API}/projects/1/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service._get_paginated("/projects/1/issues")

        request = route.calls[0].request
        assert b"page=1" in request.url.raw_path
        assert b"per_page=20" in request.url.raw_path


class TestErrorMapping:
    """Tests for comprehensive error mapping across all HTTP methods."""

    @respx.mock
    async def test_error_body_with_message_key(self) -> None:
        """Test that error message is extracted from 'message' key in response body."""
        respx.get(f"{BASE_API}/projects").respond(404, json={"message": "Project not found"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert str(exc_info.value) == "Project not found"

    @respx.mock
    async def test_error_body_with_error_key(self) -> None:
        """Test that error message falls back to 'error' key in response body."""
        respx.get(f"{BASE_API}/projects").respond(500, json={"error": "Internal failure"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert str(exc_info.value) == "Internal failure"

    @respx.mock
    async def test_error_body_fallback_to_http_status(self) -> None:
        """Test that error message falls back to HTTP status code string."""
        respx.get(f"{BASE_API}/projects").respond(502, json={})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert "HTTP 502" in str(exc_info.value)

    @respx.mock
    async def test_error_stores_response_body(self) -> None:
        """Test that the error response body is stored on the exception."""
        body = {"message": "Unauthorized", "details": "Token expired"}
        respx.get(f"{BASE_API}/projects").respond(401, json=body)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.response_body == body

    @respx.mock
    async def test_non_json_error_body_no_crash(self) -> None:
        """Test that non-JSON error bodies don't crash error handling."""
        respx.get(f"{BASE_API}/projects").respond(
            500, content=b"plain text error", headers={"content-type": "text/plain"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/projects")

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500


class TestAuthHeaderInjection:
    """Tests verifying that auth headers are passed through the httpx client.

    Note: Auth headers are configured at the httpx.AsyncClient level
    (via headers parameter), not injected per-request by the base service.
    The service delegates header management to the client.
    """

    @respx.mock
    async def test_client_headers_sent_with_get(self) -> None:
        """Test that httpx client headers are included in GET requests."""
        route = respx.get(f"{BASE_API}/projects").respond(200, json=[])

        async with httpx.AsyncClient(headers={"PRIVATE-TOKEN": "glpat-test"}) as client:
            service = _make_service(client=client)
            await service._get("/projects")

        request = route.calls[0].request
        assert request.headers["private-token"] == "glpat-test"

    @respx.mock
    async def test_client_headers_sent_with_post(self) -> None:
        """Test that httpx client headers are included in POST requests."""
        route = respx.post(f"{BASE_API}/projects/1/issues").respond(201, json={"id": 1})

        async with httpx.AsyncClient(headers={"PRIVATE-TOKEN": "glpat-test"}) as client:
            service = _make_service(client=client)
            await service._post("/projects/1/issues", json={"title": "test"})

        request = route.calls[0].request
        assert request.headers["private-token"] == "glpat-test"

    @respx.mock
    async def test_client_headers_sent_with_put(self) -> None:
        """Test that httpx client headers are included in PUT requests."""
        route = respx.put(f"{BASE_API}/projects/1/issues/1").respond(200, json={"id": 1})

        async with httpx.AsyncClient(headers={"PRIVATE-TOKEN": "glpat-test"}) as client:
            service = _make_service(client=client)
            await service._put("/projects/1/issues/1", json={"title": "updated"})

        request = route.calls[0].request
        assert request.headers["private-token"] == "glpat-test"

    @respx.mock
    async def test_oauth_bearer_token_header(self) -> None:
        """Test that OAuth Bearer token headers work via client configuration."""
        route = respx.get(f"{BASE_API}/projects").respond(200, json=[])

        async with httpx.AsyncClient(headers={"Authorization": "Bearer oauth-token-123"}) as client:
            service = _make_service(client=client)
            await service._get("/projects")

        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer oauth-token-123"


class TestConnectionErrors:
    """Tests for various httpx exception types being properly wrapped."""

    @respx.mock
    async def test_connect_timeout_wrapped(self) -> None:
        """Test that httpx.ConnectTimeout is wrapped as CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/test").mock(side_effect=httpx.ConnectTimeout("connection timed out"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/test")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR
        assert "timeout" in str(exc_info.value).lower()

    @respx.mock
    async def test_read_timeout_wrapped(self) -> None:
        """Test that httpx.ReadTimeout is wrapped as CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/test").mock(side_effect=httpx.ReadTimeout("read timed out"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/test")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_connect_error_wrapped(self) -> None:
        """Test that httpx.ConnectError is wrapped as CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/test").mock(side_effect=httpx.ConnectError("connection refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/test")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_generic_http_error_wrapped(self) -> None:
        """Test that generic httpx.HTTPError is wrapped as CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/test").mock(side_effect=httpx.HTTPError("something went wrong"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get("/test")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR
