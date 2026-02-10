"""Tests for issue tool handlers (tools/issue_tools.py).

Covers all 6 issue tools: list_issues, get_issue, list_issue_comments,
create_issue, update_issue, and add_issue_comment.

Tests verify:
- Each tool calls the correct service method with proper arguments
- Context None returns CONNECTION_ERROR
- Service exceptions produce structured error responses
- Output models are correctly constructed from service results
- Edge cases: labels as comma-separated string, assignee_id vs assignee_ids
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.models.issues import (
    IssueComment,
    IssueCommentsOutput,
    IssueDetail,
    IssueSummary,
    ListIssuesOutput,
)
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.tools.issue_tools import (
    add_issue_comment,
    create_issue,
    get_issue,
    list_issue_comments,
    list_issues,
    update_issue,
)

from tests.conftest import make_settings

# ---------------------------------------------------------------------------
# Sample data matching the issue models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Mock helpers for MCP context
# ---------------------------------------------------------------------------


@dataclass
class FakeAppContext:
    """Minimal AppContext stand-in for tool handler tests."""

    client: Any = None
    settings: Any = None


@dataclass
class FakeRequestContext:
    """Minimal RequestContext stand-in for tool handler tests."""

    lifespan_context: FakeAppContext


def _make_ctx(app_ctx: FakeAppContext | None = None) -> MagicMock:
    """Build a mock MCP Context object that returns the given AppContext.

    Default AppContext has read_only=False settings so write tools work.
    """
    if app_ctx is None:
        app_ctx = FakeAppContext(settings=make_settings())
    ctx = MagicMock()
    ctx.request_context = FakeRequestContext(lifespan_context=app_ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tests: list_issues
# ---------------------------------------------------------------------------


class TestListIssues:
    """Tests for the list_issues tool handler."""

    async def test_returns_connection_error_when_ctx_is_none(self) -> None:
        """Test that None context returns CONNECTION_ERROR dict."""
        result = await list_issues(project_id=42, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_calls_service_and_returns_output_model(self) -> None:
        """Test happy path: service called, result converted to ListIssuesOutput."""
        service_result = {
            "items": [SAMPLE_ISSUE],
            "page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
        }
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = service_result
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issues(project_id=42, ctx=ctx)

        assert isinstance(result, ListIssuesOutput)
        assert len(result.items) == 1
        assert isinstance(result.items[0], IssueSummary)
        assert result.items[0].iid == 1
        assert result.page == 1
        assert result.per_page == 20
        assert result.total == 1
        assert result.total_pages == 1

    async def test_passes_all_filters_to_service(self) -> None:
        """Test that state, labels, and assignee_id are forwarded to the service."""
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await list_issues(
                project_id=42,
                state="opened",
                labels="bug,critical",
                assignee_id=7,
                page=2,
                per_page=50,
                ctx=ctx,
            )

        mock_service.list_issues.assert_called_once_with(
            project_id=42,
            state="opened",
            labels="bug,critical",
            assignee_id=7,
            page=2,
            per_page=50,
        )

    async def test_labels_passed_as_comma_separated_string(self) -> None:
        """Test that labels filter is passed as comma-separated string."""
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await list_issues(
                project_id=42,
                labels="bug,enhancement,docs",
                ctx=ctx,
            )

        call_kwargs = mock_service.list_issues.call_args.kwargs
        assert call_kwargs["labels"] == "bug,enhancement,docs"

    async def test_assignee_id_filter_is_single_int(self) -> None:
        """Test that assignee_id is a single integer filter (not a list)."""
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await list_issues(project_id=42, assignee_id=5, ctx=ctx)

        call_kwargs = mock_service.list_issues.call_args.kwargs
        assert call_kwargs["assignee_id"] == 5

    async def test_gitlab_api_error_returns_structured_error(self) -> None:
        """Test that GitLabAPIError is converted to structured error dict."""
        mock_service = AsyncMock()
        mock_service.list_issues.side_effect = GitLabAPIError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            status_code=404,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issues(project_id=999, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PROJECT_NOT_FOUND

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        mock_service = AsyncMock()
        mock_service.list_issues.side_effect = RuntimeError("Unexpected failure")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issues(project_id=42, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "Unexpected failure" in result["message"]

    async def test_pagination_clamped(self) -> None:
        """Test that pagination params are clamped to valid ranges."""
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = {
            "items": [],
            "page": 1,
            "per_page": 100,
            "total": 0,
            "total_pages": 0,
        }
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await list_issues(project_id=42, page=-1, per_page=500, ctx=ctx)

        call_kwargs = mock_service.list_issues.call_args.kwargs
        assert call_kwargs["page"] == 1
        assert call_kwargs["per_page"] == 100


# ---------------------------------------------------------------------------
# Tests: get_issue
# ---------------------------------------------------------------------------


class TestGetIssue:
    """Tests for the get_issue tool handler."""

    async def test_returns_connection_error_when_ctx_is_none(self) -> None:
        """Test that None context returns CONNECTION_ERROR dict."""
        result = await get_issue(project_id=42, issue_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_calls_service_and_returns_issue_detail(self) -> None:
        """Test happy path: service called, result converted to IssueDetail."""
        mock_service = AsyncMock()
        mock_service.get_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await get_issue(project_id=42, issue_iid=1, ctx=ctx)

        assert isinstance(result, IssueDetail)
        assert result.iid == 1
        assert result.title == "Fix login bug"
        assert result.description == "Login page throws 500 error"
        assert result.user_notes_count == 3

    async def test_passes_correct_params_to_service(self) -> None:
        """Test that project_id and issue_iid are forwarded to the service."""
        mock_service = AsyncMock()
        mock_service.get_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await get_issue(project_id=42, issue_iid=7, ctx=ctx)

        mock_service.get_issue.assert_called_once_with(
            project_id=42,
            issue_iid=7,
        )

    async def test_issue_not_found_returns_structured_error(self) -> None:
        """Test that ISSUE_NOT_FOUND error is returned as structured dict."""
        mock_service = AsyncMock()
        mock_service.get_issue.side_effect = GitLabAPIError(
            message="Issue !999 not found",
            error_code=ErrorCode.ISSUE_NOT_FOUND,
            status_code=404,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await get_issue(project_id=42, issue_iid=999, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.ISSUE_NOT_FOUND

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        mock_service = AsyncMock()
        mock_service.get_issue.side_effect = RuntimeError("Unexpected")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await get_issue(project_id=42, issue_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# ---------------------------------------------------------------------------
# Tests: list_issue_comments
# ---------------------------------------------------------------------------


class TestListIssueComments:
    """Tests for the list_issue_comments tool handler."""

    async def test_returns_connection_error_when_ctx_is_none(self) -> None:
        """Test that None context returns CONNECTION_ERROR dict."""
        result = await list_issue_comments(project_id=42, issue_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_calls_service_and_returns_comments_output(self) -> None:
        """Test happy path: service called, result converted to IssueCommentsOutput."""
        service_result = {
            "items": [SAMPLE_COMMENT],
            "page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
        }
        mock_service = AsyncMock()
        mock_service.list_issue_comments.return_value = service_result
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issue_comments(project_id=42, issue_iid=1, ctx=ctx)

        assert isinstance(result, IssueCommentsOutput)
        assert len(result.items) == 1
        assert isinstance(result.items[0], IssueComment)
        assert result.items[0].id == 501
        assert result.items[0].body == "I can reproduce this"

    async def test_passes_correct_params_to_service(self) -> None:
        """Test that all parameters are forwarded to the service."""
        mock_service = AsyncMock()
        mock_service.list_issue_comments.return_value = {
            "items": [],
            "page": 2,
            "per_page": 10,
            "total": 0,
            "total_pages": 0,
        }
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await list_issue_comments(project_id=42, issue_iid=7, page=2, per_page=10, ctx=ctx)

        mock_service.list_issue_comments.assert_called_once_with(
            project_id=42,
            issue_iid=7,
            page=2,
            per_page=10,
        )

    async def test_issue_not_found_returns_structured_error(self) -> None:
        """Test that ISSUE_NOT_FOUND error returns a structured dict."""
        mock_service = AsyncMock()
        mock_service.list_issue_comments.side_effect = GitLabAPIError(
            message="Issue !999 not found",
            error_code=ErrorCode.ISSUE_NOT_FOUND,
            status_code=404,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issue_comments(project_id=42, issue_iid=999, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.ISSUE_NOT_FOUND

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        mock_service = AsyncMock()
        mock_service.list_issue_comments.side_effect = RuntimeError("Timeout")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issue_comments(project_id=42, issue_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_pagination_clamped(self) -> None:
        """Test that pagination params are clamped to valid ranges."""
        mock_service = AsyncMock()
        mock_service.list_issue_comments.return_value = {
            "items": [],
            "page": 1,
            "per_page": 100,
            "total": 0,
            "total_pages": 0,
        }
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await list_issue_comments(project_id=42, issue_iid=1, page=0, per_page=200, ctx=ctx)

        call_kwargs = mock_service.list_issue_comments.call_args.kwargs
        assert call_kwargs["page"] == 1
        assert call_kwargs["per_page"] == 100


# ---------------------------------------------------------------------------
# Tests: create_issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    """Tests for the create_issue tool handler."""

    async def test_returns_connection_error_when_ctx_is_none(self) -> None:
        """Test that None context returns CONNECTION_ERROR dict."""
        result = await create_issue(project_id=42, title="Test", ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_calls_service_and_returns_issue_detail(self) -> None:
        """Test happy path: service called, result converted to IssueDetail."""
        mock_service = AsyncMock()
        mock_service.create_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await create_issue(project_id=42, title="New bug", ctx=ctx)

        assert isinstance(result, IssueDetail)
        assert result.title == "Fix login bug"

    async def test_passes_all_fields_to_service(self) -> None:
        """Test that all optional fields are forwarded to the service."""
        mock_service = AsyncMock()
        mock_service.create_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await create_issue(
                project_id=42,
                title="Full issue",
                description="Detailed",
                assignee_ids=[1, 2, 3],
                labels="bug,critical",
                milestone_id=5,
                ctx=ctx,
            )

        mock_service.create_issue.assert_called_once_with(
            project_id=42,
            title="Full issue",
            description="Detailed",
            assignee_ids=[1, 2, 3],
            labels="bug,critical",
            milestone_id=5,
        )

    async def test_assignee_ids_accepts_multiple(self) -> None:
        """Test that assignee_ids accepts a list of multiple user IDs."""
        mock_service = AsyncMock()
        mock_service.create_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await create_issue(
                project_id=42,
                title="Multi-assign",
                assignee_ids=[10, 20, 30],
                ctx=ctx,
            )

        call_kwargs = mock_service.create_issue.call_args.kwargs
        assert call_kwargs["assignee_ids"] == [10, 20, 30]

    async def test_labels_passed_as_comma_separated_string(self) -> None:
        """Test that labels for create are passed as comma-separated string."""
        mock_service = AsyncMock()
        mock_service.create_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await create_issue(
                project_id=42,
                title="Labeled issue",
                labels="bug,urgent",
                ctx=ctx,
            )

        call_kwargs = mock_service.create_issue.call_args.kwargs
        assert call_kwargs["labels"] == "bug,urgent"

    async def test_validation_error_returns_structured_error(self) -> None:
        """Test that VALIDATION_ERROR from service returns structured dict."""
        mock_service = AsyncMock()
        mock_service.create_issue.side_effect = GitLabAPIError(
            message="Title can't be blank",
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await create_issue(project_id=42, title="", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.VALIDATION_ERROR

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        mock_service = AsyncMock()
        mock_service.create_issue.side_effect = RuntimeError("Connection reset")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await create_issue(project_id=42, title="Test", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# ---------------------------------------------------------------------------
# Tests: update_issue
# ---------------------------------------------------------------------------


class TestUpdateIssue:
    """Tests for the update_issue tool handler."""

    async def test_returns_connection_error_when_ctx_is_none(self) -> None:
        """Test that None context returns CONNECTION_ERROR dict."""
        result = await update_issue(project_id=42, issue_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_calls_service_and_returns_issue_detail(self) -> None:
        """Test happy path: service called, result converted to IssueDetail."""
        updated = {**SAMPLE_ISSUE_DETAIL, "title": "Updated title"}
        mock_service = AsyncMock()
        mock_service.update_issue.return_value = updated
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await update_issue(project_id=42, issue_iid=1, title="Updated title", ctx=ctx)

        assert isinstance(result, IssueDetail)
        assert result.title == "Updated title"

    async def test_passes_all_fields_to_service(self) -> None:
        """Test that all optional fields are forwarded to the service."""
        mock_service = AsyncMock()
        mock_service.update_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await update_issue(
                project_id=42,
                issue_iid=1,
                title="Updated",
                description="New desc",
                assignee_ids=[5],
                labels="enhancement",
                state_event="close",
                ctx=ctx,
            )

        mock_service.update_issue.assert_called_once_with(
            project_id=42,
            issue_iid=1,
            title="Updated",
            description="New desc",
            assignee_ids=[5],
            labels="enhancement",
            state_event="close",
        )

    async def test_assignee_ids_accepts_multiple_in_update(self) -> None:
        """Test that update_issue passes assignee_ids as a list (not single ID)."""
        mock_service = AsyncMock()
        mock_service.update_issue.return_value = SAMPLE_ISSUE_DETAIL
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await update_issue(
                project_id=42,
                issue_iid=1,
                assignee_ids=[10, 20],
                ctx=ctx,
            )

        call_kwargs = mock_service.update_issue.call_args.kwargs
        assert call_kwargs["assignee_ids"] == [10, 20]

    async def test_issue_not_found_returns_structured_error(self) -> None:
        """Test that ISSUE_NOT_FOUND error returns structured dict."""
        mock_service = AsyncMock()
        mock_service.update_issue.side_effect = GitLabAPIError(
            message="Issue !999 not found",
            error_code=ErrorCode.ISSUE_NOT_FOUND,
            status_code=404,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await update_issue(project_id=42, issue_iid=999, title="x", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.ISSUE_NOT_FOUND

    async def test_validation_error_returns_structured_error(self) -> None:
        """Test that VALIDATION_ERROR from service returns structured dict."""
        mock_service = AsyncMock()
        mock_service.update_issue.side_effect = GitLabAPIError(
            message="Invalid labels",
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await update_issue(project_id=42, issue_iid=1, labels="nonexistent", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.VALIDATION_ERROR

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        mock_service = AsyncMock()
        mock_service.update_issue.side_effect = RuntimeError("Network error")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await update_issue(project_id=42, issue_iid=1, title="x", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# ---------------------------------------------------------------------------
# Tests: add_issue_comment
# ---------------------------------------------------------------------------


class TestAddIssueComment:
    """Tests for the add_issue_comment tool handler."""

    async def test_returns_connection_error_when_ctx_is_none(self) -> None:
        """Test that None context returns CONNECTION_ERROR dict."""
        result = await add_issue_comment(project_id=42, issue_iid=1, body="Test", ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_calls_service_and_returns_comment(self) -> None:
        """Test happy path: service called, result converted to IssueComment."""
        mock_service = AsyncMock()
        mock_service.add_issue_comment.return_value = SAMPLE_COMMENT
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await add_issue_comment(project_id=42, issue_iid=1, body="Looks good", ctx=ctx)

        assert isinstance(result, IssueComment)
        assert result.id == 501
        assert result.body == "I can reproduce this"

    async def test_passes_correct_params_to_service(self) -> None:
        """Test that project_id, issue_iid, and body are forwarded."""
        mock_service = AsyncMock()
        mock_service.add_issue_comment.return_value = SAMPLE_COMMENT
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            await add_issue_comment(project_id=42, issue_iid=7, body="Fixed in abc123", ctx=ctx)

        mock_service.add_issue_comment.assert_called_once_with(
            project_id=42,
            issue_iid=7,
            body="Fixed in abc123",
        )

    async def test_issue_not_found_returns_structured_error(self) -> None:
        """Test that ISSUE_NOT_FOUND error returns structured dict."""
        mock_service = AsyncMock()
        mock_service.add_issue_comment.side_effect = GitLabAPIError(
            message="Issue !999 not found",
            error_code=ErrorCode.ISSUE_NOT_FOUND,
            status_code=404,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await add_issue_comment(project_id=42, issue_iid=999, body="Comment", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.ISSUE_NOT_FOUND

    async def test_unexpected_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions are caught and return CONNECTION_ERROR."""
        mock_service = AsyncMock()
        mock_service.add_issue_comment.side_effect = RuntimeError("Kaboom")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await add_issue_comment(project_id=42, issue_iid=1, body="Comment", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# ---------------------------------------------------------------------------
# Tests: Tool registration and annotations
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests verifying tool registration with correct annotations."""

    def test_all_six_tools_are_importable(self) -> None:
        """Test that all 6 tool functions can be imported from the module."""
        from mamba_mcp_gitlab.tools import issue_tools

        assert hasattr(issue_tools, "list_issues")
        assert hasattr(issue_tools, "get_issue")
        assert hasattr(issue_tools, "list_issue_comments")
        assert hasattr(issue_tools, "create_issue")
        assert hasattr(issue_tools, "update_issue")
        assert hasattr(issue_tools, "add_issue_comment")

    def test_all_tools_are_async_functions(self) -> None:
        """Test that all tools are async (coroutine) functions."""
        import inspect

        assert inspect.iscoroutinefunction(list_issues)
        assert inspect.iscoroutinefunction(get_issue)
        assert inspect.iscoroutinefunction(list_issue_comments)
        assert inspect.iscoroutinefunction(create_issue)
        assert inspect.iscoroutinefunction(update_issue)
        assert inspect.iscoroutinefunction(add_issue_comment)

    def test_all_tools_have_docstrings(self) -> None:
        """Test that all tools have clear docstrings for AI assistant consumption."""
        assert list_issues.__doc__ is not None
        assert get_issue.__doc__ is not None
        assert list_issue_comments.__doc__ is not None
        assert create_issue.__doc__ is not None
        assert update_issue.__doc__ is not None
        assert add_issue_comment.__doc__ is not None

        # Verify docstrings are meaningful (not just empty)
        for tool_fn in [
            list_issues,
            get_issue,
            list_issue_comments,
            create_issue,
            update_issue,
            add_issue_comment,
        ]:
            assert len(tool_fn.__doc__) > 50, f"{tool_fn.__name__} docstring too short"


# ---------------------------------------------------------------------------
# Tests: Error context in structured errors
# ---------------------------------------------------------------------------


class TestErrorContext:
    """Tests verifying error context is included in error responses."""

    async def test_gitlab_api_error_includes_status_code_in_context(self) -> None:
        """Test that GitLabAPIError responses include status_code in context."""
        mock_service = AsyncMock()
        mock_service.list_issues.side_effect = GitLabAPIError(
            message="Forbidden",
            error_code=ErrorCode.FORBIDDEN,
            status_code=403,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issues(project_id=42, ctx=ctx)

        assert isinstance(result, dict)
        assert "context" in result
        assert result["context"]["status_code"] == 403

    async def test_gitlab_api_error_includes_elapsed_ms_in_context(self) -> None:
        """Test that error responses include elapsed_ms in context."""
        mock_service = AsyncMock()
        mock_service.get_issue.side_effect = GitLabAPIError(
            message="Not found",
            error_code=ErrorCode.ISSUE_NOT_FOUND,
            status_code=404,
        )
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await get_issue(project_id=42, issue_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert "context" in result
        assert "elapsed_ms" in result["context"]
        assert isinstance(result["context"]["elapsed_ms"], float)

    async def test_unexpected_error_includes_elapsed_ms(self) -> None:
        """Test that unexpected exception errors include elapsed_ms."""
        mock_service = AsyncMock()
        mock_service.create_issue.side_effect = RuntimeError("oops")
        ctx = _make_ctx()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await create_issue(project_id=42, title="Test", ctx=ctx)

        assert isinstance(result, dict)
        assert "context" in result
        assert "elapsed_ms" in result["context"]
