"""Tests for the merge request service (services/merge_request_service.py).

Covers all 7 MergeRequestService methods: list_mrs, get_mr, get_mr_diffs,
get_mr_commits, create_mr, update_mr, get_mr_pipelines. Verifies correct
API endpoints, pagination forwarding, error mapping, and optional field handling.
"""

import httpx
import pytest
import respx
from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.merge_request_service import MergeRequestService

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
) -> MergeRequestService:
    """Create a MergeRequestService instance for testing."""
    settings = _make_settings(url=url, default_project_id=default_project_id)
    http_client = client or httpx.AsyncClient()
    return MergeRequestService(http_client=http_client, settings=settings)


# Sample MR data for reuse in tests
SAMPLE_MR = {
    "id": 101,
    "iid": 1,
    "title": "Add feature X",
    "state": "opened",
    "source_branch": "feature-x",
    "target_branch": "main",
    "created_at": "2025-01-15T10:00:00Z",
    "updated_at": "2025-01-16T12:00:00Z",
    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
    "author": {"id": 1, "username": "dev", "name": "Developer", "avatar_url": None},
}

SAMPLE_MR_DETAIL = {
    **SAMPLE_MR,
    "description": "Adds feature X to the project",
    "assignees": [{"id": 2, "username": "reviewer", "name": "Reviewer", "avatar_url": None}],
    "reviewers": [],
    "labels": ["enhancement"],
    "merge_status": "can_be_merged",
    "diff_refs": {"base_sha": "abc123", "head_sha": "def456", "start_sha": "ghi789"},
    "pipeline": None,
}


class TestListMrs:
    """Tests for list_mrs method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that list_mrs calls GET /projects/{id}/merge_requests."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[SAMPLE_MR],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_mrs(project_id=42)

        assert route.called
        assert result["items"] == [SAMPLE_MR]

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that list_mrs returns page, per_page, total, and total_pages."""
        respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[SAMPLE_MR],
            headers={"x-total": "50", "x-total-pages": "3"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_mrs(project_id=42, page=2, per_page=20)

        assert result["page"] == 2
        assert result["per_page"] == 20
        assert result["total"] == 50
        assert result["total_pages"] == 3

    @respx.mock
    async def test_forwards_pagination_params(self) -> None:
        """Test that page and per_page are forwarded as query params."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id=42, page=3, per_page=50)

        request = route.calls[0].request
        assert b"page=3" in request.url.raw_path
        assert b"per_page=50" in request.url.raw_path

    @respx.mock
    async def test_state_filter_opened(self) -> None:
        """Test that state=opened is forwarded as query param."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id=42, state="opened")

        request = route.calls[0].request
        assert b"state=opened" in request.url.raw_path

    @respx.mock
    async def test_state_filter_closed(self) -> None:
        """Test that state=closed is forwarded as query param."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id=42, state="closed")

        request = route.calls[0].request
        assert b"state=closed" in request.url.raw_path

    @respx.mock
    async def test_state_filter_merged(self) -> None:
        """Test that state=merged is forwarded as query param."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id=42, state="merged")

        request = route.calls[0].request
        assert b"state=merged" in request.url.raw_path

    @respx.mock
    async def test_state_filter_all(self) -> None:
        """Test that state=all is forwarded as query param."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id=42, state="all")

        request = route.calls[0].request
        assert b"state=all" in request.url.raw_path

    @respx.mock
    async def test_no_state_filter(self) -> None:
        """Test that no state param is sent when state is None."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id=42)

        request = route.calls[0].request
        assert b"state=" not in request.url.raw_path

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default_project_id is used when project_id is None."""
        route = respx.get(f"{BASE_API}/projects/999/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.list_mrs()

        assert route.called

    @respx.mock
    async def test_project_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with PROJECT_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/9999/merge_requests").respond(
            404, json={"message": "404 Project Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_mrs(project_id=9999)

        assert exc_info.value.error_code == ErrorCode.PROJECT_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_string_project_path(self) -> None:
        """Test that string project paths are URL-encoded in the request."""
        route = respx.get(f"{BASE_API}/projects/group%2Fsubgroup%2Fproject/merge_requests").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_mrs(project_id="group/subgroup/project")

        assert route.called

    async def test_raises_when_no_project_id(self) -> None:
        """Test that GitLabAPIError is raised when no project_id and no default."""
        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_mrs()

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR


class TestGetMr:
    """Tests for get_mr method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_mr calls GET /projects/{id}/merge_requests/{mr_iid}."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr(project_id=42, mr_iid=1)

        assert route.called
        assert result == SAMPLE_MR_DETAIL

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default project ID is used when not provided."""
        route = respx.get(f"{BASE_API}/projects/999/merge_requests/5").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.get_mr(mr_iid=5)

        assert route.called

    @respx.mock
    async def test_mr_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with MERGE_REQUEST_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/999").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr(project_id=42, mr_iid=999)

        assert exc_info.value.error_code == ErrorCode.MERGE_REQUEST_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_string_project_path(self) -> None:
        """Test that string project paths are URL-encoded."""
        route = respx.get(f"{BASE_API}/projects/group%2Fproject/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.get_mr(project_id="group/project", mr_iid=1)

        assert route.called


class TestGetMrDiffs:
    """Tests for get_mr_diffs method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_mr_diffs calls GET /projects/{id}/merge_requests/{mr_iid}/diffs."""
        diff = {
            "old_path": "README.md",
            "new_path": "README.md",
            "diff": "@@ -1 +1 @@\n-old\n+new",
            "new_file": False,
            "renamed_file": False,
            "deleted_file": False,
        }
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1/diffs").respond(
            200,
            json=[diff],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_diffs(project_id=42, mr_iid=1)

        assert route.called
        assert result["items"] == [diff]

    @respx.mock
    async def test_forwards_pagination_params(self) -> None:
        """Test that page and per_page are forwarded as query params."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1/diffs").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.get_mr_diffs(project_id=42, mr_iid=1, page=2, per_page=10)

        request = route.calls[0].request
        assert b"page=2" in request.url.raw_path
        assert b"per_page=10" in request.url.raw_path

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that pagination metadata is included in the response."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/diffs").respond(
            200,
            json=[],
            headers={"x-total": "25", "x-total-pages": "5"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_diffs(project_id=42, mr_iid=1, page=1, per_page=5)

        assert result["page"] == 1
        assert result["per_page"] == 5
        assert result["total"] == 25
        assert result["total_pages"] == 5

    @respx.mock
    async def test_empty_diffs_list(self) -> None:
        """Test that an MR with no changes returns an empty items list."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/diffs").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_diffs(project_id=42, mr_iid=1)

        assert result["items"] == []
        assert result["total"] == 0

    @respx.mock
    async def test_mr_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with MERGE_REQUEST_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/999/diffs").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_diffs(project_id=42, mr_iid=999)

        assert exc_info.value.error_code == ErrorCode.MERGE_REQUEST_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default project ID is used when not provided."""
        route = respx.get(f"{BASE_API}/projects/999/merge_requests/1/diffs").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.get_mr_diffs(mr_iid=1)

        assert route.called


class TestGetMrCommits:
    """Tests for get_mr_commits method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_mr_commits calls GET /projects/{id}/merge_requests/{mr_iid}/commits."""
        commit = {
            "id": "abc123def456",
            "short_id": "abc123d",
            "title": "Fix bug",
            "author_name": "Developer",
            "authored_date": "2025-01-15T10:00:00Z",
            "message": "Fix bug in feature X",
        }
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1/commits").respond(
            200,
            json=[commit],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_commits(project_id=42, mr_iid=1)

        assert route.called
        assert result["items"] == [commit]

    @respx.mock
    async def test_forwards_pagination_params(self) -> None:
        """Test that page and per_page are forwarded as query params."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1/commits").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.get_mr_commits(project_id=42, mr_iid=1, page=3, per_page=25)

        request = route.calls[0].request
        assert b"page=3" in request.url.raw_path
        assert b"per_page=25" in request.url.raw_path

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that pagination metadata is included in the response."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/commits").respond(
            200,
            json=[],
            headers={"x-total": "100", "x-total-pages": "10"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_commits(project_id=42, mr_iid=1, page=5, per_page=10)

        assert result["page"] == 5
        assert result["per_page"] == 10
        assert result["total"] == 100
        assert result["total_pages"] == 10

    @respx.mock
    async def test_mr_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with MERGE_REQUEST_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/999/commits").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_commits(project_id=42, mr_iid=999)

        assert exc_info.value.error_code == ErrorCode.MERGE_REQUEST_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default project ID is used when not provided."""
        route = respx.get(f"{BASE_API}/projects/999/merge_requests/1/commits").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.get_mr_commits(mr_iid=1)

        assert route.called


class TestCreateMr:
    """Tests for create_mr method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that create_mr calls POST /projects/{id}/merge_requests."""
        route = respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.create_mr(
                project_id=42,
                title="Add feature X",
                source_branch="feature-x",
                target_branch="main",
            )

        assert route.called
        assert result == SAMPLE_MR_DETAIL

    @respx.mock
    async def test_sends_required_fields(self) -> None:
        """Test that title, source_branch, and target_branch are sent in the body."""
        route = respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_mr(
                project_id=42,
                title="New MR",
                source_branch="feature",
                target_branch="main",
            )

        request = route.calls[0].request
        body = request.content.decode()
        assert '"title"' in body
        assert '"source_branch"' in body
        assert '"target_branch"' in body

    @respx.mock
    async def test_sends_all_optional_fields(self) -> None:
        """Test that all optional fields are included when provided."""
        route = respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_mr(
                project_id=42,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                description="Some description",
                assignee_ids=[1, 2],
                reviewer_ids=[3],
                labels=["bug", "priority"],
            )

        request = route.calls[0].request
        body = request.content.decode()
        assert '"description"' in body
        assert '"assignee_ids"' in body
        assert '"reviewer_ids"' in body
        assert '"labels"' in body

    @respx.mock
    async def test_omits_optional_fields_when_none(self) -> None:
        """Test that optional fields are not sent when they are None."""
        route = respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_mr(
                project_id=42,
                title="New MR",
                source_branch="feature",
                target_branch="main",
            )

        request = route.calls[0].request
        body = request.content.decode()
        assert '"description"' not in body
        assert '"assignee_ids"' not in body
        assert '"reviewer_ids"' not in body
        assert '"labels"' not in body

    @respx.mock
    async def test_labels_as_comma_separated_string(self) -> None:
        """Test that labels are converted to comma-separated string for GitLab API."""
        route = respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_mr(
                project_id=42,
                title="MR",
                source_branch="f",
                target_branch="main",
                labels=["bug", "urgent", "v2"],
            )

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["labels"] == "bug,urgent,v2"

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default project ID is used when not provided."""
        route = respx.post(f"{BASE_API}/projects/999/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.create_mr(
                title="MR",
                source_branch="feature",
                target_branch="main",
            )

        assert route.called

    @respx.mock
    async def test_project_not_found(self) -> None:
        """Test that 404 with non-branch message raises PROJECT_NOT_FOUND."""
        respx.post(f"{BASE_API}/projects/9999/merge_requests").respond(
            404, json={"message": "404 Project Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.create_mr(
                    project_id=9999,
                    title="MR",
                    source_branch="feature",
                    target_branch="main",
                )

        assert exc_info.value.error_code == ErrorCode.PROJECT_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_branch_not_found(self) -> None:
        """Test that 404 with branch-related message raises BRANCH_NOT_FOUND."""
        respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            404, json={"message": "Source branch not found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.create_mr(
                    project_id=42,
                    title="MR",
                    source_branch="nonexistent-branch",
                    target_branch="main",
                )

        assert exc_info.value.error_code == ErrorCode.BRANCH_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_string_project_path(self) -> None:
        """Test that string project paths are URL-encoded."""
        route = respx.post(f"{BASE_API}/projects/group%2Fproject/merge_requests").respond(
            201, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.create_mr(
                project_id="group/project",
                title="MR",
                source_branch="feature",
                target_branch="main",
            )

        assert route.called


class TestUpdateMr:
    """Tests for update_mr method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that update_mr calls PUT /projects/{id}/merge_requests/{mr_iid}."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.update_mr(project_id=42, mr_iid=1, title="Updated title")

        assert route.called
        assert result == SAMPLE_MR_DETAIL

    @respx.mock
    async def test_only_sends_provided_fields(self) -> None:
        """Test that update_mr only sends fields that were explicitly provided."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(project_id=42, mr_iid=1, title="New title")

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body == {"title": "New title"}

    @respx.mock
    async def test_sends_all_fields_when_provided(self) -> None:
        """Test that all optional fields are included when explicitly provided."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(
                project_id=42,
                mr_iid=1,
                title="Updated",
                description="New desc",
                assignee_ids=[1, 2],
                reviewer_ids=[3],
                labels=["bug"],
                state_event="close",
            )

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["title"] == "Updated"
        assert body["description"] == "New desc"
        assert body["assignee_ids"] == [1, 2]
        assert body["reviewer_ids"] == [3]
        assert body["labels"] == "bug"
        assert body["state_event"] == "close"

    @respx.mock
    async def test_labels_as_comma_separated_string(self) -> None:
        """Test that labels are converted to comma-separated string for GitLab API."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(
                project_id=42,
                mr_iid=1,
                labels=["enhancement", "v2", "docs"],
            )

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["labels"] == "enhancement,v2,docs"

    @respx.mock
    async def test_state_event_close(self) -> None:
        """Test that state_event=close is sent in the body."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json={**SAMPLE_MR_DETAIL, "state": "closed"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(project_id=42, mr_iid=1, state_event="close")

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["state_event"] == "close"

    @respx.mock
    async def test_state_event_reopen(self) -> None:
        """Test that state_event=reopen is sent in the body."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json={**SAMPLE_MR_DETAIL, "state": "opened"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(project_id=42, mr_iid=1, state_event="reopen")

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["state_event"] == "reopen"

    @respx.mock
    async def test_mr_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with MERGE_REQUEST_NOT_FOUND."""
        respx.put(f"{BASE_API}/projects/42/merge_requests/999").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.update_mr(project_id=42, mr_iid=999, title="Updated")

        assert exc_info.value.error_code == ErrorCode.MERGE_REQUEST_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default project ID is used when not provided."""
        route = respx.put(f"{BASE_API}/projects/999/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.update_mr(mr_iid=1, title="Updated")

        assert route.called

    @respx.mock
    async def test_empty_body_when_no_fields_changed(self) -> None:
        """Test that an empty body is sent when no fields are provided."""
        route = respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(project_id=42, mr_iid=1)

        import json

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body == {}

    @respx.mock
    async def test_string_project_path(self) -> None:
        """Test that string project paths are URL-encoded."""
        route = respx.put(f"{BASE_API}/projects/group%2Fproject/merge_requests/1").respond(
            200, json=SAMPLE_MR_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.update_mr(project_id="group/project", mr_iid=1, title="Updated")

        assert route.called


# Sample pipeline data for MR pipeline tests
SAMPLE_PIPELINE = {
    "id": 200,
    "iid": 10,
    "status": "success",
    "ref": "feature-x",
    "sha": "abc123def456",
    "created_at": "2025-01-15T10:00:00Z",
    "updated_at": "2025-01-15T10:30:00Z",
    "web_url": "https://gitlab.example.com/group/project/-/pipelines/200",
}


class TestGetMrPipelines:
    """Tests for get_mr_pipelines method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_mr_pipelines calls GET /projects/{id}/merge_requests/{mr_iid}/pipelines."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1/pipelines").respond(
            200,
            json=[SAMPLE_PIPELINE],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_pipelines(project_id=42, mr_iid=1)

        assert route.called
        assert result["items"] == [SAMPLE_PIPELINE]

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that get_mr_pipelines returns page, per_page, total, and total_pages."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/pipelines").respond(
            200,
            json=[SAMPLE_PIPELINE],
            headers={"x-total": "15", "x-total-pages": "2"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_pipelines(project_id=42, mr_iid=1, page=1, per_page=10)

        assert result["page"] == 1
        assert result["per_page"] == 10
        assert result["total"] == 15
        assert result["total_pages"] == 2

    @respx.mock
    async def test_forwards_pagination_params(self) -> None:
        """Test that page and per_page are forwarded as query params."""
        route = respx.get(f"{BASE_API}/projects/42/merge_requests/1/pipelines").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.get_mr_pipelines(project_id=42, mr_iid=1, page=2, per_page=5)

        request = route.calls[0].request
        assert b"page=2" in request.url.raw_path
        assert b"per_page=5" in request.url.raw_path

    @respx.mock
    async def test_empty_pipelines_list(self) -> None:
        """Test that an MR with no pipelines returns an empty items list."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/pipelines").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_pipelines(project_id=42, mr_iid=1)

        assert result["items"] == []
        assert result["total"] == 0

    @respx.mock
    async def test_mr_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with MERGE_REQUEST_NOT_FOUND."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/999/pipelines").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_pipelines(project_id=42, mr_iid=999)

        assert exc_info.value.error_code == ErrorCode.MERGE_REQUEST_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_uses_default_project_id(self) -> None:
        """Test that default project ID is used when not provided."""
        route = respx.get(f"{BASE_API}/projects/999/merge_requests/1/pipelines").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client, default_project_id=999)
            await service.get_mr_pipelines(mr_iid=1)

        assert route.called

    @respx.mock
    async def test_string_project_path(self) -> None:
        """Test that string project paths are URL-encoded in the request."""
        route = respx.get(
            f"{BASE_API}/projects/group%2Fproject/merge_requests/1/pipelines"
        ).respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.get_mr_pipelines(project_id="group/project", mr_iid=1)

        assert route.called

    async def test_raises_when_no_project_id(self) -> None:
        """Test that GitLabAPIError is raised when no project_id and no default."""
        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_pipelines(mr_iid=1)

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    @respx.mock
    async def test_multiple_pipelines(self) -> None:
        """Test that multiple pipelines are returned correctly."""
        pipeline2 = {
            **SAMPLE_PIPELINE,
            "id": 201,
            "iid": 11,
            "status": "failed",
        }
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/pipelines").respond(
            200,
            json=[SAMPLE_PIPELINE, pipeline2],
            headers={"x-total": "2", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_mr_pipelines(project_id=42, mr_iid=1)

        assert len(result["items"]) == 2
        assert result["items"][0]["status"] == "success"
        assert result["items"][1]["status"] == "failed"


class TestNon404ErrorReRaise:
    """Tests verifying non-404 errors are re-raised unchanged through each method."""

    @respx.mock
    async def test_list_mrs_reraises_non_404(self) -> None:
        """Test that list_mrs re-raises non-404 GitLabAPIError unchanged."""
        respx.get(f"{BASE_API}/projects/42/merge_requests").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.list_mrs(project_id=42)

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_get_mr_reraises_non_404(self) -> None:
        """Test that get_mr re-raises non-404 GitLabAPIError unchanged."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr(project_id=42, mr_iid=1)

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_get_mr_diffs_reraises_non_404(self) -> None:
        """Test that get_mr_diffs re-raises non-404 GitLabAPIError unchanged."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/diffs").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_diffs(project_id=42, mr_iid=1)

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_get_mr_commits_reraises_non_404(self) -> None:
        """Test that get_mr_commits re-raises non-404 GitLabAPIError unchanged."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/commits").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_commits(project_id=42, mr_iid=1)

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_create_mr_reraises_non_404(self) -> None:
        """Test that create_mr re-raises non-404 GitLabAPIError unchanged."""
        respx.post(f"{BASE_API}/projects/42/merge_requests").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.create_mr(
                    project_id=42,
                    title="MR",
                    source_branch="feature",
                    target_branch="main",
                )

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_update_mr_reraises_non_404(self) -> None:
        """Test that update_mr re-raises non-404 GitLabAPIError unchanged."""
        respx.put(f"{BASE_API}/projects/42/merge_requests/1").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.update_mr(project_id=42, mr_iid=1, title="Updated")

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_get_mr_pipelines_reraises_non_404(self) -> None:
        """Test that get_mr_pipelines re-raises non-404 GitLabAPIError unchanged."""
        respx.get(f"{BASE_API}/projects/42/merge_requests/1/pipelines").respond(
            500, json={"message": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_mr_pipelines(project_id=42, mr_iid=1)

        assert exc_info.value.status_code == 500


class TestMergeRequestServiceInheritance:
    """Tests verifying MergeRequestService inherits from GitLabService."""

    def test_is_subclass_of_gitlab_service(self) -> None:
        """Test that MergeRequestService is a subclass of GitLabService."""
        from mamba_mcp_gitlab.services.base import GitLabService

        assert issubclass(MergeRequestService, GitLabService)

    def test_has_base_url(self) -> None:
        """Test that service instance has base_url from GitLabService."""
        service = _make_service()
        assert service.base_url == f"{GITLAB_URL}/api/v4"

    def test_has_settings(self) -> None:
        """Test that service instance has settings from GitLabService."""
        service = _make_service()
        assert isinstance(service.settings, Settings)
