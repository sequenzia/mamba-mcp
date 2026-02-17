"""Tests for the IssueService (services/issue_service.py).

Covers all 6 issue methods: list_issues, get_issue, list_issue_comments,
create_issue, update_issue, and add_issue_comment. Tests verify correct
endpoint calls, parameter passing, error mapping, and edge cases.
"""

import httpx
import pytest
import respx
from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.issue_service import IssueService

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
) -> IssueService:
    """Create an IssueService instance for testing."""
    settings = _make_settings(url=url, default_project_id=default_project_id)
    http_client = client or httpx.AsyncClient()
    return IssueService(http_client=http_client, settings=settings)


SAMPLE_ISSUE = {
    "id": 101,
    "iid": 1,
    "title": "Fix login bug",
    "state": "opened",
    "author": {"id": 1, "username": "dev", "name": "Developer", "avatar_url": None},
    "assignees": [],
    "labels": ["bug"],
    "created_at": "2026-01-15T10:00:00Z",
    "updated_at": "2026-01-15T12:00:00Z",
    "web_url": "https://gitlab.example.com/project/issues/1",
}

SAMPLE_ISSUE_DETAIL = {
    **SAMPLE_ISSUE,
    "description": "Login page throws 500 error",
    "milestone": None,
    "user_notes_count": 3,
    "upvotes": 2,
    "downvotes": 0,
}

SAMPLE_COMMENT = {
    "id": 501,
    "body": "I can reproduce this",
    "author": {"id": 2, "username": "qa", "name": "QA Engineer", "avatar_url": None},
    "created_at": "2026-01-15T14:00:00Z",
    "updated_at": "2026-01-15T14:00:00Z",
    "system": False,
}


class TestListIssues:
    """Tests for IssueService.list_issues."""

    @respx.mock
    async def test_lists_issues_for_project(self) -> None:
        """Test that list_issues calls GET /projects/{id}/issues."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[SAMPLE_ISSUE],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_issues(project_id=42)

        assert route.called
        assert result["items"] == [SAMPLE_ISSUE]
        assert result["total"] == 1
        assert result["total_pages"] == 1
        assert result["page"] == 1
        assert result["per_page"] == 20

    @respx.mock
    async def test_passes_state_filter(self) -> None:
        """Test that state filter is included in query params."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id=42, state="closed")

        request = route.calls[0].request
        assert b"state=closed" in request.url.raw_path

    @respx.mock
    async def test_passes_labels_filter(self) -> None:
        """Test that labels filter is passed as comma-separated string."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id=42, labels="bug,critical")

        request = route.calls[0].request
        # Labels should be in the query string (URL-encoded comma)
        raw_path = request.url.raw_path.decode()
        assert "labels=" in raw_path
        assert "bug" in raw_path

    @respx.mock
    async def test_passes_assignee_id_filter(self) -> None:
        """Test that assignee_id filter is included in query params."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id=42, assignee_id=7)

        request = route.calls[0].request
        assert b"assignee_id=7" in request.url.raw_path

    @respx.mock
    async def test_passes_pagination_params(self) -> None:
        """Test that page and per_page are included in query params."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id=42, page=3, per_page=50)

        request = route.calls[0].request
        assert b"page=3" in request.url.raw_path
        assert b"per_page=50" in request.url.raw_path

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.get(f"{BASE_API}/projects/99/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.list_issues()

        assert route.called

    async def test_raises_when_no_project_id(self) -> None:
        """Test that GitLabAPIError is raised when no project_id and no default."""
        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_issues()

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    @respx.mock
    async def test_no_filters_omits_optional_params(self) -> None:
        """Test that optional filter params are omitted when not provided."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id=42)

        request = route.calls[0].request
        raw_path = request.url.raw_path.decode()
        assert "state=" not in raw_path
        assert "labels=" not in raw_path
        assert "assignee_id=" not in raw_path

    @respx.mock
    async def test_empty_labels_string_passed_through(self) -> None:
        """Test that an empty labels string is still passed to the API."""
        route = respx.get(f"{BASE_API}/projects/42/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id=42, labels="")

        request = route.calls[0].request
        raw_path = request.url.raw_path.decode()
        assert "labels=" in raw_path


class TestGetIssue:
    """Tests for IssueService.get_issue."""

    @respx.mock
    async def test_gets_issue_by_iid(self) -> None:
        """Test that get_issue calls GET /projects/{id}/issues/{issue_iid}."""
        route = respx.get(f"{BASE_API}/projects/42/issues/1").respond(200, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_issue(project_id=42, issue_iid=1)

        assert route.called
        assert result == SAMPLE_ISSUE_DETAIL

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.get(f"{BASE_API}/projects/99/issues/1").respond(200, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            result = await service.get_issue(issue_iid=1)

        assert route.called
        assert result == SAMPLE_ISSUE_DETAIL

    @respx.mock
    async def test_issue_not_found_remapped(self) -> None:
        """Test that 404 is remapped to ISSUE_NOT_FOUND error code."""
        respx.get(f"{BASE_API}/projects/42/issues/999").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_issue(project_id=42, issue_iid=999)

        assert exc_info.value.error_code == ErrorCode.ISSUE_NOT_FOUND
        assert exc_info.value.status_code == 404
        assert "999" in str(exc_info.value)

    @respx.mock
    async def test_non_404_error_not_remapped(self) -> None:
        """Test that non-404 errors are not remapped to ISSUE_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/42/issues/1").respond(
            500, json={"error": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_issue(project_id=42, issue_iid=1)

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500


class TestListIssueComments:
    """Tests for IssueService.list_issue_comments."""

    @respx.mock
    async def test_lists_comments_for_issue(self) -> None:
        """Test that list_issue_comments calls GET /projects/{id}/issues/{iid}/notes."""
        route = respx.get(f"{BASE_API}/projects/42/issues/1/notes").respond(
            200,
            json=[SAMPLE_COMMENT],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_issue_comments(project_id=42, issue_iid=1)

        assert route.called
        assert result["items"] == [SAMPLE_COMMENT]
        assert result["total"] == 1
        assert result["total_pages"] == 1
        assert result["page"] == 1
        assert result["per_page"] == 20

    @respx.mock
    async def test_passes_pagination_params(self) -> None:
        """Test that page and per_page are included in query params."""
        route = respx.get(f"{BASE_API}/projects/42/issues/1/notes").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issue_comments(project_id=42, issue_iid=1, page=2, per_page=10)

        request = route.calls[0].request
        assert b"page=2" in request.url.raw_path
        assert b"per_page=10" in request.url.raw_path

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.get(f"{BASE_API}/projects/99/issues/1/notes").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.list_issue_comments(issue_iid=1)

        assert route.called

    @respx.mock
    async def test_issue_not_found_remapped(self) -> None:
        """Test that 404 on notes endpoint is remapped to ISSUE_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/42/issues/999/notes").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_issue_comments(project_id=42, issue_iid=999)

        assert exc_info.value.error_code == ErrorCode.ISSUE_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_non_404_error_not_remapped(self) -> None:
        """Test that non-404 errors on notes are not remapped."""
        respx.get(f"{BASE_API}/projects/42/issues/1/notes").respond(
            403, json={"message": "403 Forbidden"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_issue_comments(project_id=42, issue_iid=1)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert exc_info.value.status_code == 403


class TestCreateIssue:
    """Tests for IssueService.create_issue."""

    @respx.mock
    async def test_creates_issue_with_title(self) -> None:
        """Test that create_issue calls POST /projects/{id}/issues with title."""
        route = respx.post(f"{BASE_API}/projects/42/issues").respond(201, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.create_issue(project_id=42, title="New issue")

        assert route.called
        assert result == SAMPLE_ISSUE_DETAIL
        request = route.calls[0].request
        assert b'"title"' in request.content
        assert b'"New issue"' in request.content

    @respx.mock
    async def test_creates_issue_with_all_fields(self) -> None:
        """Test that create_issue sends all optional fields when provided."""
        route = respx.post(f"{BASE_API}/projects/42/issues").respond(201, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_issue(
                project_id=42,
                title="Full issue",
                description="Detailed description",
                assignee_ids=[1, 2, 3],
                labels="bug,critical",
                milestone_id=5,
            )

        request = route.calls[0].request
        body = request.content.decode()
        assert '"title"' in body
        assert '"description"' in body
        assert '"assignee_ids"' in body
        assert '"labels"' in body
        assert '"milestone_id"' in body

    @respx.mock
    async def test_creates_issue_omits_none_fields(self) -> None:
        """Test that create_issue omits fields that are None."""
        route = respx.post(f"{BASE_API}/projects/42/issues").respond(201, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_issue(project_id=42, title="Minimal issue")

        request = route.calls[0].request
        body = request.content.decode()
        assert '"title"' in body
        assert '"description"' not in body
        assert '"assignee_ids"' not in body
        assert '"labels"' not in body
        assert '"milestone_id"' not in body

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.post(f"{BASE_API}/projects/99/issues").respond(201, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.create_issue(title="Default project issue")

        assert route.called

    @respx.mock
    async def test_validation_error_on_400(self) -> None:
        """Test that 400 is remapped to VALIDATION_ERROR."""
        respx.post(f"{BASE_API}/projects/42/issues").respond(
            400, json={"message": {"title": ["can't be blank"]}}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.create_issue(project_id=42, title="")

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert exc_info.value.status_code == 400

    @respx.mock
    async def test_multiple_assignee_ids_supported(self) -> None:
        """Test that multiple assignee_ids are sent in the request body."""
        route = respx.post(f"{BASE_API}/projects/42/issues").respond(201, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_issue(
                project_id=42,
                title="Multi-assign",
                assignee_ids=[10, 20, 30],
            )

        request = route.calls[0].request
        body = request.content.decode()
        assert "[10, 20, 30]" in body or "[10,20,30]" in body

    @respx.mock
    async def test_non_400_error_not_remapped(self) -> None:
        """Test that non-400 errors are not remapped to VALIDATION_ERROR."""
        respx.post(f"{BASE_API}/projects/42/issues").respond(403, json={"message": "Forbidden"})

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.create_issue(project_id=42, title="Forbidden")

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN


class TestUpdateIssue:
    """Tests for IssueService.update_issue."""

    @respx.mock
    async def test_updates_issue_title(self) -> None:
        """Test that update_issue calls PUT /projects/{id}/issues/{iid}."""
        route = respx.put(f"{BASE_API}/projects/42/issues/1").respond(
            200, json={**SAMPLE_ISSUE_DETAIL, "title": "Updated title"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.update_issue(project_id=42, issue_iid=1, title="Updated title")

        assert route.called
        assert result["title"] == "Updated title"
        request = route.calls[0].request
        assert b'"title"' in request.content

    @respx.mock
    async def test_updates_issue_with_all_fields(self) -> None:
        """Test that update_issue sends all optional fields when provided."""
        route = respx.put(f"{BASE_API}/projects/42/issues/1").respond(200, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_issue(
                project_id=42,
                issue_iid=1,
                title="Updated",
                description="New desc",
                assignee_ids=[5],
                labels="enhancement",
                state_event="close",
            )

        request = route.calls[0].request
        body = request.content.decode()
        assert '"title"' in body
        assert '"description"' in body
        assert '"assignee_ids"' in body
        assert '"labels"' in body
        assert '"state_event"' in body

    @respx.mock
    async def test_updates_issue_omits_none_fields(self) -> None:
        """Test that update_issue omits fields that are None."""
        route = respx.put(f"{BASE_API}/projects/42/issues/1").respond(200, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_issue(project_id=42, issue_iid=1, title="Only title")

        request = route.calls[0].request
        body = request.content.decode()
        assert '"title"' in body
        assert '"description"' not in body
        assert '"state_event"' not in body

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.put(f"{BASE_API}/projects/99/issues/1").respond(200, json=SAMPLE_ISSUE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.update_issue(issue_iid=1, title="Update")

        assert route.called

    @respx.mock
    async def test_issue_not_found_remapped(self) -> None:
        """Test that 404 is remapped to ISSUE_NOT_FOUND error code."""
        respx.put(f"{BASE_API}/projects/42/issues/999").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.update_issue(project_id=42, issue_iid=999, title="x")

        assert exc_info.value.error_code == ErrorCode.ISSUE_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_validation_error_on_400(self) -> None:
        """Test that 400 is remapped to VALIDATION_ERROR."""
        respx.put(f"{BASE_API}/projects/42/issues/1").respond(
            400, json={"message": {"labels": ["is invalid"]}}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.update_issue(project_id=42, issue_iid=1, labels="nonexistent")

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert exc_info.value.status_code == 400

    @respx.mock
    async def test_state_event_close(self) -> None:
        """Test that state_event=close is sent in the request body."""
        route = respx.put(f"{BASE_API}/projects/42/issues/1").respond(
            200, json={**SAMPLE_ISSUE_DETAIL, "state": "closed"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.update_issue(project_id=42, issue_iid=1, state_event="close")

        assert result["state"] == "closed"
        request = route.calls[0].request
        assert b'"state_event"' in request.content
        assert b'"close"' in request.content

    @respx.mock
    async def test_non_404_non_400_error_not_remapped(self) -> None:
        """Test that errors other than 404/400 are not remapped."""
        respx.put(f"{BASE_API}/projects/42/issues/1").respond(
            500, json={"error": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.update_issue(project_id=42, issue_iid=1, title="x")

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500


class TestAddIssueComment:
    """Tests for IssueService.add_issue_comment."""

    @respx.mock
    async def test_adds_comment_to_issue(self) -> None:
        """Test that add_issue_comment calls POST /projects/{id}/issues/{iid}/notes."""
        route = respx.post(f"{BASE_API}/projects/42/issues/1/notes").respond(
            201, json=SAMPLE_COMMENT
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.add_issue_comment(project_id=42, issue_iid=1, body="Looks good")

        assert route.called
        assert result == SAMPLE_COMMENT
        request = route.calls[0].request
        assert b'"body"' in request.content
        assert b'"Looks good"' in request.content

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.post(f"{BASE_API}/projects/99/issues/1/notes").respond(
            201, json=SAMPLE_COMMENT
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=99)
            await service.add_issue_comment(issue_iid=1, body="Comment")

        assert route.called

    @respx.mock
    async def test_issue_not_found_remapped(self) -> None:
        """Test that 404 is remapped to ISSUE_NOT_FOUND error code."""
        respx.post(f"{BASE_API}/projects/42/issues/999/notes").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.add_issue_comment(project_id=42, issue_iid=999, body="Comment")

        assert exc_info.value.error_code == ErrorCode.ISSUE_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_comment_on_closed_issue(self) -> None:
        """Test that commenting on a closed issue succeeds (GitLab permits this)."""
        route = respx.post(f"{BASE_API}/projects/42/issues/1/notes").respond(
            201, json=SAMPLE_COMMENT
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.add_issue_comment(
                project_id=42, issue_iid=1, body="Comment on closed issue"
            )

        assert route.called
        assert result == SAMPLE_COMMENT

    @respx.mock
    async def test_non_404_error_not_remapped(self) -> None:
        """Test that non-404 errors are not remapped."""
        respx.post(f"{BASE_API}/projects/42/issues/1/notes").respond(
            401, json={"message": "401 Unauthorized"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.add_issue_comment(project_id=42, issue_iid=1, body="Comment")

        assert exc_info.value.error_code == ErrorCode.AUTH_FAILED
        assert exc_info.value.status_code == 401


class TestIssueServiceStringProjectPath:
    """Tests for IssueService with string project paths."""

    @respx.mock
    async def test_list_issues_with_string_path(self) -> None:
        """Test that string project paths are URL-encoded in issue list."""
        route = respx.get(f"{BASE_API}/projects/group%2Fsubgroup%2Fproject/issues").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_issues(project_id="group/subgroup/project")

        assert route.called

    @respx.mock
    async def test_get_issue_with_string_path(self) -> None:
        """Test that string project paths are URL-encoded in get_issue."""
        route = respx.get(f"{BASE_API}/projects/group%2Fproject/issues/5").respond(
            200, json=SAMPLE_ISSUE_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_issue(project_id="group/project", issue_iid=5)

        assert route.called
        assert result == SAMPLE_ISSUE_DETAIL


class TestIssueServiceConnectionErrors:
    """Tests for connection error handling in IssueService methods."""

    @respx.mock
    async def test_list_issues_connection_error(self) -> None:
        """Test that connection errors propagate with CONNECTION_ERROR code."""
        respx.get(f"{BASE_API}/projects/42/issues").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_issues(project_id=42)

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_create_issue_connection_timeout(self) -> None:
        """Test that timeout errors propagate with CONNECTION_ERROR code."""
        respx.post(f"{BASE_API}/projects/42/issues").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.create_issue(project_id=42, title="test")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR
