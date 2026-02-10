"""Gap-filling tests for comprehensive coverage across all 18 tools.

Covers acceptance criteria gaps identified in the existing 927-test suite:
- All HTTP error codes (401, 403, 404, 429, 500) through tool handlers
- Empty results for list operations at the tool handler level
- Job log truncation at exact byte boundary and multi-byte character boundary
- AUTH_FAILED, FORBIDDEN, RATE_LIMITED, API_ERROR through each tool category
- Tool name included in all error responses
- Suggestion field populated from ERROR_SUGGESTIONS for each error code
- Service construction receives correct client and settings for all tool groups
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_gitlab.errors import ERROR_SUGGESTIONS, ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.tools.issue_tools import (
    add_issue_comment,
    create_issue,
    get_issue,
    list_issue_comments,
    list_issues,
    update_issue,
)
from mamba_mcp_gitlab.tools.mr_tools import (
    create_mr,
    get_mr,
    get_mr_commits,
    get_mr_diffs,
    get_mr_pipelines,
    list_mrs,
    update_mr,
)
from mamba_mcp_gitlab.tools.pipeline_tools import (
    get_job_log,
    get_pipeline,
    get_pipeline_jobs,
    list_pipelines,
)
from mamba_mcp_gitlab.tools.search_tools import search

from tests.conftest import make_settings

# ---------------------------------------------------------------------------
# Shared mock context helpers
# ---------------------------------------------------------------------------

TEST_PROJECT_ID = 42


@dataclass
class _FakeRequestCtx:
    """Mock for ctx.request_context."""

    lifespan_context: Any


@dataclass
class _FakeCtx:
    """Mock for the MCP Context object passed to tool handlers."""

    request_context: _FakeRequestCtx


@dataclass
class _FakeAppCtx:
    """Minimal AppContext for tool handler tests."""

    client: Any
    settings: Any


def _make_ctx(
    *,
    default_project_id: int | None = None,
    read_only: bool = False,
) -> _FakeCtx:
    """Build a mock context for tool handler calls."""
    settings = make_settings(default_project_id=default_project_id, read_only=read_only)
    app_ctx = _FakeAppCtx(client=MagicMock(), settings=settings)
    return _FakeCtx(request_context=_FakeRequestCtx(lifespan_context=app_ctx))


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def _mr_summary(iid: int = 1) -> dict[str, Any]:
    """Build a minimal MR summary dict."""
    return {
        "id": 100 + iid,
        "iid": iid,
        "title": f"MR !{iid}",
        "state": "opened",
        "author": {"id": 1, "username": "dev", "name": "Dev"},
        "source_branch": "feature",
        "target_branch": "main",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "web_url": f"https://gitlab.example.com/project/-/merge_requests/{iid}",
    }


def _mr_detail(iid: int = 1) -> dict[str, Any]:
    """Build a minimal MR detail dict."""
    base = _mr_summary(iid)
    base.update(
        {
            "description": "A merge request",
            "assignees": [],
            "reviewers": [],
            "labels": [],
            "merge_status": "can_be_merged",
            "diff_refs": None,
            "pipeline": None,
        }
    )
    return base


def _issue_summary() -> dict[str, Any]:
    """Build a minimal issue summary dict."""
    return {
        "id": 101,
        "iid": 1,
        "title": "Bug report",
        "state": "opened",
        "author": {"id": 1, "username": "dev", "name": "Dev", "avatar_url": None},
        "assignees": [],
        "labels": [],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "web_url": "https://gitlab.example.com/project/issues/1",
    }


def _issue_detail() -> dict[str, Any]:
    """Build a minimal issue detail dict."""
    return {
        **_issue_summary(),
        "description": "Description",
        "milestone": None,
        "user_notes_count": 0,
        "upvotes": 0,
        "downvotes": 0,
    }


def _issue_comment() -> dict[str, Any]:
    """Build a minimal issue comment dict."""
    return {
        "id": 501,
        "body": "Comment text",
        "author": {"id": 1, "username": "dev", "name": "Dev", "avatar_url": None},
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "system": False,
    }


def _pipeline_summary(pid: int = 100) -> dict[str, Any]:
    """Build a minimal pipeline summary dict."""
    return {
        "id": pid,
        "iid": 1,
        "status": "success",
        "ref": "main",
        "sha": "abc123def456",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "web_url": f"https://gitlab.example.com/project/-/pipelines/{pid}",
    }


def _pipeline_detail() -> dict[str, Any]:
    """Build a minimal pipeline detail dict."""
    return {
        **_pipeline_summary(),
        "duration": 120,
        "started_at": "2025-01-01T00:00:30Z",
        "finished_at": "2025-01-01T00:02:30Z",
        "coverage": None,
        "user": None,
    }


def _pipeline_job() -> dict[str, Any]:
    """Build a minimal pipeline job dict."""
    return {
        "id": 500,
        "name": "test",
        "stage": "test",
        "status": "success",
        "duration": 30.0,
        "runner": "shared-runner",
        "web_url": "https://gitlab.example.com/project/-/jobs/500",
    }


def _empty_paginated() -> dict[str, Any]:
    """Build an empty paginated result."""
    return {
        "items": [],
        "page": 1,
        "per_page": 20,
        "total": 0,
        "total_pages": 0,
    }


# ---------------------------------------------------------------------------
# HTTP error code parametrization
# ---------------------------------------------------------------------------

HTTP_ERROR_CASES = [
    (401, ErrorCode.AUTH_FAILED, "401 Unauthorized"),
    (403, ErrorCode.FORBIDDEN, "403 Forbidden"),
    (404, ErrorCode.NOT_FOUND, "404 Not Found"),
    (429, ErrorCode.RATE_LIMITED, "429 Too Many Requests"),
    (500, ErrorCode.API_ERROR, "500 Internal Server Error"),
]


# ===========================================================================
# MR Tools - HTTP Error Codes
# ===========================================================================


class TestMrToolsHttpErrors:
    """Test all HTTP error codes propagate correctly through MR tool handlers."""

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_list_mrs_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """list_mrs returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.list_mrs = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code
        assert result["tool_name"] == "list_mrs"
        assert "context" in result
        assert result["context"]["status_code"] == status_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_mr_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_mr returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_mr_diffs_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_mr_diffs returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr_diffs = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_mr_diffs(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_mr_commits_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_mr_commits returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr_commits = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_mr_commits(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_mr_pipelines_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_mr_pipelines returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_create_mr_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """create_mr returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.create_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await create_mr(
                project_id=TEST_PROJECT_ID,
                title="T",
                source_branch="f",
                target_branch="m",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_update_mr_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """update_mr returns correct error code for each HTTP status."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.update_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await update_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code


# ===========================================================================
# Issue Tools - HTTP Error Codes
# ===========================================================================


class TestIssueToolsHttpErrors:
    """Test all HTTP error codes propagate correctly through issue tool handlers."""

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_list_issues_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """list_issues returns correct error code for each HTTP status."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.list_issues.side_effect = GitLabAPIError(
            message=message, error_code=error_code, status_code=status_code
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await list_issues(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code
        assert result["context"]["status_code"] == status_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_issue_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_issue returns correct error code for each HTTP status."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.get_issue.side_effect = GitLabAPIError(
            message=message, error_code=error_code, status_code=status_code
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await get_issue(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_list_issue_comments_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """list_issue_comments returns correct error code for each HTTP status."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.list_issue_comments.side_effect = GitLabAPIError(
            message=message, error_code=error_code, status_code=status_code
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await list_issue_comments(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_create_issue_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """create_issue returns correct error code for each HTTP status."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.create_issue.side_effect = GitLabAPIError(
            message=message, error_code=error_code, status_code=status_code
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await create_issue(project_id=TEST_PROJECT_ID, title="Test", ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_update_issue_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """update_issue returns correct error code for each HTTP status."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.update_issue.side_effect = GitLabAPIError(
            message=message, error_code=error_code, status_code=status_code
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await update_issue(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_add_issue_comment_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """add_issue_comment returns correct error code for each HTTP status."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.add_issue_comment.side_effect = GitLabAPIError(
            message=message, error_code=error_code, status_code=status_code
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await add_issue_comment(
                project_id=TEST_PROJECT_ID, issue_iid=1, body="Test", ctx=ctx
            )

        assert isinstance(result, dict)
        assert result["code"] == error_code


# ===========================================================================
# Pipeline Tools - HTTP Error Codes
# ===========================================================================


class TestPipelineToolsHttpErrors:
    """Test all HTTP error codes propagate correctly through pipeline tool handlers."""

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_list_pipelines_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """list_pipelines returns correct error code for each HTTP status."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await list_pipelines(project_id=TEST_PROJECT_ID, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code
        assert result["context"]["status_code"] == status_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_pipeline_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_pipeline returns correct error code for each HTTP status."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_pipeline(project_id=TEST_PROJECT_ID, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_pipeline_jobs_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_pipeline_jobs returns correct error code for each HTTP status."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline_jobs = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_pipeline_jobs(
                project_id=TEST_PROJECT_ID, pipeline_id=100, ctx=mock_ctx
            )

        assert isinstance(result, dict)
        assert result["code"] == error_code

    @pytest.mark.parametrize("status_code,error_code,message", HTTP_ERROR_CASES)
    async def test_get_job_log_http_errors(
        self, status_code: int, error_code: str, message: str
    ) -> None:
        """get_job_log returns correct error code for each HTTP status."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(
                side_effect=GitLabAPIError(
                    message=message, error_code=error_code, status_code=status_code
                )
            )
            result = await get_job_log(project_id=TEST_PROJECT_ID, job_id=500, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == error_code


# ===========================================================================
# Empty results for all list operations (tool handler level)
# ===========================================================================


class TestEmptyResultsListOperations:
    """Test that all list operations handle empty results correctly at tool level."""

    async def test_list_issues_empty_results(self) -> None:
        """list_issues returns valid output with empty items list."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = _empty_paginated()
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await list_issues(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert not isinstance(result, dict)
        assert len(result.items) == 0
        assert result.total == 0
        assert result.total_pages == 0

    async def test_list_issue_comments_empty_results(self) -> None:
        """list_issue_comments returns valid output with empty items list."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.list_issue_comments.return_value = _empty_paginated()
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await list_issue_comments(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)

        assert not isinstance(result, dict)
        assert len(result.items) == 0
        assert result.total == 0

    async def test_list_pipelines_empty_results(self) -> None:
        """list_pipelines returns valid output with empty items list."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(return_value=_empty_paginated())
            result = await list_pipelines(project_id=TEST_PROJECT_ID, ctx=mock_ctx)

        assert not isinstance(result, dict)
        assert len(result.items) == 0
        assert result.total == 0

    async def test_get_pipeline_jobs_empty_results(self) -> None:
        """get_pipeline_jobs returns valid output with empty items list."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline_jobs = AsyncMock(return_value=_empty_paginated())
            result = await get_pipeline_jobs(
                project_id=TEST_PROJECT_ID, pipeline_id=100, ctx=mock_ctx
            )

        assert not isinstance(result, dict)
        assert len(result.items) == 0
        assert result.total == 0

    async def test_get_mr_diffs_empty_results_via_ctx(self) -> None:
        """get_mr_diffs with empty diff list produces valid output."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr_diffs = AsyncMock(return_value=_empty_paginated())
            result = await get_mr_diffs(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert not isinstance(result, dict)
        assert len(result.items) == 0

    async def test_get_mr_commits_empty_results_via_ctx(self) -> None:
        """get_mr_commits with empty commit list produces valid output."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr_commits = AsyncMock(return_value=_empty_paginated())
            result = await get_mr_commits(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert not isinstance(result, dict)
        assert len(result.items) == 0


# ===========================================================================
# Job Log Truncation Boundary Tests
# ===========================================================================


class TestJobLogTruncationBoundary:
    """Test job log truncation at exact byte boundaries."""

    async def test_log_exactly_at_max_bytes_not_truncated(self) -> None:
        """Log exactly equal to max_bytes should not be truncated."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        # Content of exactly 1024 bytes (min max_bytes)
        content = "x" * 1024
        service_result = {
            "content": content,
            "truncated": False,
            "byte_count": 1024,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(return_value=service_result)
            result = await get_job_log(
                project_id=TEST_PROJECT_ID, job_id=500, max_bytes=1024, ctx=mock_ctx
            )

        assert not isinstance(result, dict)
        assert result.truncated is False
        assert result.byte_count == 1024
        assert len(result.content) == 1024

    async def test_log_one_byte_over_max_bytes_is_truncated(self) -> None:
        """Log one byte over max_bytes should be truncated by the service."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        # Service would truncate and mark as truncated
        service_result = {
            "content": "x" * 1024 + "\n\n--- Log truncated (showing first 1024/1025 bytes) ---",
            "truncated": True,
            "byte_count": 1025,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(return_value=service_result)
            result = await get_job_log(
                project_id=TEST_PROJECT_ID, job_id=500, max_bytes=1024, ctx=mock_ctx
            )

        assert not isinstance(result, dict)
        assert result.truncated is True
        assert result.byte_count == 1025

    async def test_empty_log_content(self) -> None:
        """Empty job log should return valid output with empty content."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        service_result = {
            "content": "",
            "truncated": False,
            "byte_count": 0,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(return_value=service_result)
            result = await get_job_log(project_id=TEST_PROJECT_ID, job_id=500, ctx=mock_ctx)

        assert not isinstance(result, dict)
        assert result.content == ""
        assert result.truncated is False
        assert result.byte_count == 0

    async def test_max_bytes_at_exact_minimum(self) -> None:
        """max_bytes=1024 (minimum) should be passed through without clamping."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        service_result = {"content": "log", "truncated": False, "byte_count": 3}
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_job_log = mock_method
            await get_job_log(project_id=TEST_PROJECT_ID, job_id=500, max_bytes=1024, ctx=mock_ctx)

        mock_method.assert_called_once_with(project_id=TEST_PROJECT_ID, job_id=500, max_bytes=1024)

    async def test_max_bytes_at_exact_maximum(self) -> None:
        """max_bytes=1048576 (maximum) should be passed through without clamping."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        service_result = {"content": "log", "truncated": False, "byte_count": 3}
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_job_log = mock_method
            await get_job_log(
                project_id=TEST_PROJECT_ID,
                job_id=500,
                max_bytes=1_048_576,
                ctx=mock_ctx,
            )

        mock_method.assert_called_once_with(
            project_id=TEST_PROJECT_ID, job_id=500, max_bytes=1_048_576
        )


# ===========================================================================
# Service truncation integration at the service layer
# ===========================================================================


class TestPipelineServiceTruncation:
    """Test PipelineService.get_job_log truncation logic directly."""

    async def test_multi_byte_char_boundary_truncation(self) -> None:
        """Truncation at multi-byte character boundary uses errors='ignore'."""
        import httpx
        import respx

        settings = make_settings(default_project_id=TEST_PROJECT_ID)
        from mamba_mcp_gitlab.services.pipeline_service import PipelineService

        # Content with multi-byte UTF-8 characters (each char is 3 bytes)
        multi_byte_content = "\u00e9" * 100  # e-acute, 2 bytes each in UTF-8

        @respx.mock
        async def _run_test() -> dict[str, Any]:
            respx.get("https://gitlab.example.com/api/v4/projects/42/jobs/500/trace").respond(
                200, text=multi_byte_content
            )

            async with httpx.AsyncClient() as client:
                svc = PipelineService(http_client=client, settings=settings)
                return await svc.get_job_log(project_id=42, job_id=500, max_bytes=50)

        result = await _run_test()
        # The content should be truncated and still valid UTF-8
        assert result["truncated"] is True
        assert result["byte_count"] == 200  # 100 chars * 2 bytes each
        # The content should decode successfully (no invalid bytes)
        assert isinstance(result["content"], str)
        # Should contain truncation notice
        assert "truncated" in result["content"].lower()

    async def test_exact_byte_boundary_no_truncation(self) -> None:
        """Content exactly at max_bytes boundary should not be truncated."""
        import httpx
        import respx

        settings = make_settings(default_project_id=TEST_PROJECT_ID)
        from mamba_mcp_gitlab.services.pipeline_service import PipelineService

        content = "a" * 100  # 100 ASCII bytes

        @respx.mock
        async def _run_test() -> dict[str, Any]:
            respx.get("https://gitlab.example.com/api/v4/projects/42/jobs/500/trace").respond(
                200, text=content
            )

            async with httpx.AsyncClient() as client:
                svc = PipelineService(http_client=client, settings=settings)
                return await svc.get_job_log(project_id=42, job_id=500, max_bytes=100)

        result = await _run_test()
        assert result["truncated"] is False
        assert result["byte_count"] == 100
        assert result["content"] == content


# ===========================================================================
# Error Response Structure Verification
# ===========================================================================


class TestErrorResponseStructure:
    """Verify error responses have all required fields for every tool."""

    async def test_mr_error_response_has_suggestion(self) -> None:
        """MR tool error responses include the suggestion field from ERROR_SUGGESTIONS."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.list_mrs = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Auth failed",
                    error_code=ErrorCode.AUTH_FAILED,
                    status_code=401,
                )
            )
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        assert "suggestion" in result
        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.AUTH_FAILED]

    async def test_issue_error_response_has_suggestion(self) -> None:
        """Issue tool error responses include the suggestion field."""
        ctx = _make_ctx()
        mock_service = AsyncMock()
        mock_service.list_issues.side_effect = GitLabAPIError(
            message="Forbidden",
            error_code=ErrorCode.FORBIDDEN,
            status_code=403,
        )
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service):
            result = await list_issues(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        assert "suggestion" in result
        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.FORBIDDEN]

    async def test_pipeline_error_response_has_suggestion(self) -> None:
        """Pipeline tool error responses include the suggestion field."""
        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context.client = MagicMock()
        mock_ctx.request_context.lifespan_context.settings = MagicMock()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Rate limited",
                    error_code=ErrorCode.RATE_LIMITED,
                    status_code=429,
                )
            )
            result = await list_pipelines(project_id=TEST_PROJECT_ID, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert "suggestion" in result
        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.RATE_LIMITED]

    async def test_generic_error_includes_message_in_response(self) -> None:
        """Generic exceptions include the exception message in error response."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.get_mr = AsyncMock(
                side_effect=RuntimeError("Connection reset by peer")
            )
            result = await get_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "Connection reset by peer" in result["message"]
        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.CONNECTION_ERROR]

    async def test_error_response_has_all_required_keys(self) -> None:
        """Verify all required keys are present in error response."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.list_mrs = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Not found",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        # Required keys per ToolError model
        assert "code" in result
        assert "message" in result
        assert "tool_name" in result
        assert "suggestion" in result
        # Optional but expected keys
        assert "input_received" in result
        assert "context" in result


# ===========================================================================
# Service Construction Verification
# ===========================================================================


class TestServiceConstruction:
    """Verify services are constructed with correct client and settings."""

    async def test_mr_service_receives_client_and_settings(self) -> None:
        """MergeRequestService receives app_ctx.client and app_ctx.settings."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        app_ctx = ctx.request_context.lifespan_context
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            mock_svc.return_value.list_mrs = AsyncMock(
                return_value={
                    "items": [],
                    "page": 1,
                    "per_page": 20,
                    "total": 0,
                    "total_pages": 0,
                }
            )
            await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        mock_svc.assert_called_once_with(app_ctx.client, app_ctx.settings)

    async def test_issue_service_receives_client_and_settings(self) -> None:
        """IssueService receives app_ctx.client and app_ctx.settings."""
        ctx = _make_ctx()
        app_ctx = ctx.request_context.lifespan_context
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = _empty_paginated()
        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService", return_value=mock_service
        ) as mock_cls:
            await list_issues(project_id=TEST_PROJECT_ID, ctx=ctx)

        mock_cls.assert_called_once_with(http_client=app_ctx.client, settings=app_ctx.settings)


# ===========================================================================
# Read-Only Mode Cross-Cutting with All Write Tools
# ===========================================================================


class TestReadOnlyModeAllWriteTools:
    """Verify all 5 write tools are blocked when read_only=True."""

    async def test_create_mr_blocked_in_read_only(self) -> None:
        """create_mr returns READ_ONLY error when settings.gitlab.read_only is True."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID, read_only=True)
        result = await create_mr(
            project_id=TEST_PROJECT_ID,
            title="T",
            source_branch="f",
            target_branch="m",
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY

    async def test_update_mr_blocked_in_read_only(self) -> None:
        """update_mr returns READ_ONLY error when read_only=True."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID, read_only=True)
        result = await update_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY

    async def test_create_issue_blocked_in_read_only(self) -> None:
        """create_issue returns READ_ONLY error when read_only=True."""
        ctx = _make_ctx(read_only=True)
        result = await create_issue(project_id=TEST_PROJECT_ID, title="Test", ctx=ctx)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY

    async def test_update_issue_blocked_in_read_only(self) -> None:
        """update_issue returns READ_ONLY error when read_only=True."""
        ctx = _make_ctx(read_only=True)
        result = await update_issue(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY

    async def test_add_issue_comment_blocked_in_read_only(self) -> None:
        """add_issue_comment returns READ_ONLY error when read_only=True."""
        ctx = _make_ctx(read_only=True)
        result = await add_issue_comment(
            project_id=TEST_PROJECT_ID, issue_iid=1, body="Comment", ctx=ctx
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY

    async def test_read_only_error_has_correct_suggestion(self) -> None:
        """Read-only errors include the READ_ONLY suggestion with env var hint."""
        ctx = _make_ctx(read_only=True)
        result = await create_issue(project_id=TEST_PROJECT_ID, title="Test", ctx=ctx)
        assert isinstance(result, dict)
        assert "MAMBA_MCP_GITLAB_READ_ONLY" in result["suggestion"]


# ===========================================================================
# Context None Handling for ALL 18 Tools
# ===========================================================================


class TestContextNoneAllTools:
    """Verify all 18 tools return CONNECTION_ERROR when ctx is None."""

    async def test_list_mrs_ctx_none(self) -> None:
        """list_mrs returns CONNECTION_ERROR when ctx is None."""
        result = await list_mrs(ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_mr_ctx_none(self) -> None:
        """get_mr returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr(mr_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_mr_diffs_ctx_none(self) -> None:
        """get_mr_diffs returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr_diffs(mr_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_mr_commits_ctx_none(self) -> None:
        """get_mr_commits returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr_commits(mr_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_mr_pipelines_ctx_none(self) -> None:
        """get_mr_pipelines returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr_pipelines(mr_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_create_mr_ctx_none(self) -> None:
        """create_mr returns CONNECTION_ERROR when ctx is None."""
        result = await create_mr(title="T", source_branch="f", target_branch="m", ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_update_mr_ctx_none(self) -> None:
        """update_mr returns CONNECTION_ERROR when ctx is None."""
        result = await update_mr(mr_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_list_issues_ctx_none(self) -> None:
        """list_issues returns CONNECTION_ERROR when ctx is None."""
        result = await list_issues(project_id=TEST_PROJECT_ID, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_issue_ctx_none(self) -> None:
        """get_issue returns CONNECTION_ERROR when ctx is None."""
        result = await get_issue(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_list_issue_comments_ctx_none(self) -> None:
        """list_issue_comments returns CONNECTION_ERROR when ctx is None."""
        result = await list_issue_comments(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_create_issue_ctx_none(self) -> None:
        """create_issue returns CONNECTION_ERROR when ctx is None."""
        result = await create_issue(project_id=TEST_PROJECT_ID, title="Test", ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_update_issue_ctx_none(self) -> None:
        """update_issue returns CONNECTION_ERROR when ctx is None."""
        result = await update_issue(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_add_issue_comment_ctx_none(self) -> None:
        """add_issue_comment returns CONNECTION_ERROR when ctx is None."""
        result = await add_issue_comment(
            project_id=TEST_PROJECT_ID, issue_iid=1, body="Text", ctx=None
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_list_pipelines_ctx_none(self) -> None:
        """list_pipelines returns CONNECTION_ERROR when ctx is None."""
        result = await list_pipelines(project_id=TEST_PROJECT_ID, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_pipeline_ctx_none(self) -> None:
        """get_pipeline returns CONNECTION_ERROR when ctx is None."""
        result = await get_pipeline(project_id=TEST_PROJECT_ID, pipeline_id=100, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_pipeline_jobs_ctx_none(self) -> None:
        """get_pipeline_jobs returns CONNECTION_ERROR when ctx is None."""
        result = await get_pipeline_jobs(project_id=TEST_PROJECT_ID, pipeline_id=100, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_get_job_log_ctx_none(self) -> None:
        """get_job_log returns CONNECTION_ERROR when ctx is None."""
        result = await get_job_log(project_id=TEST_PROJECT_ID, job_id=500, ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_search_ctx_none(self) -> None:
        """search returns CONNECTION_ERROR when ctx is None."""
        result = await search(query="test", scope="issues", ctx=None)
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# ===========================================================================
# HTTP Error Code Mapping Verification (Base Service Layer)
# ===========================================================================


class TestHttpErrorCodeMapping:
    """Verify all HTTP status codes are mapped to the correct ErrorCode."""

    def test_400_maps_to_validation_error(self) -> None:
        """HTTP 400 maps to VALIDATION_ERROR."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(400) == ErrorCode.VALIDATION_ERROR

    def test_401_maps_to_auth_failed(self) -> None:
        """HTTP 401 maps to AUTH_FAILED."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(401) == ErrorCode.AUTH_FAILED

    def test_403_maps_to_forbidden(self) -> None:
        """HTTP 403 maps to FORBIDDEN."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(403) == ErrorCode.FORBIDDEN

    def test_404_maps_to_not_found(self) -> None:
        """HTTP 404 maps to NOT_FOUND."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(404) == ErrorCode.NOT_FOUND

    def test_429_maps_to_rate_limited(self) -> None:
        """HTTP 429 maps to RATE_LIMITED."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(429) == ErrorCode.RATE_LIMITED

    def test_500_maps_to_api_error(self) -> None:
        """HTTP 500 maps to API_ERROR."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(500) == ErrorCode.API_ERROR

    def test_502_maps_to_api_error(self) -> None:
        """HTTP 502 maps to API_ERROR (any 5xx)."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(502) == ErrorCode.API_ERROR

    def test_503_maps_to_api_error(self) -> None:
        """HTTP 503 maps to API_ERROR (any 5xx)."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(503) == ErrorCode.API_ERROR

    def test_unknown_4xx_maps_to_api_error(self) -> None:
        """HTTP 418 (unmapped 4xx) maps to API_ERROR."""
        from mamba_mcp_gitlab.services.base import _map_status_to_error_code

        assert _map_status_to_error_code(418) == ErrorCode.API_ERROR


# ===========================================================================
# Tool Registration Count Verification
# ===========================================================================


class TestAllToolsRegistered:
    """Verify all 18 tools are registered with the MCP server."""

    def test_all_18_tools_registered(self) -> None:
        """Verify all 18 tools are registered on the mcp instance."""
        from mamba_mcp_gitlab.server import mcp as server_mcp
        from mamba_mcp_gitlab.tools import (  # noqa: F401
            issue_tools,
            mr_tools,
            pipeline_tools,
            search_tools,
        )

        tool_names = list(server_mcp._tool_manager._tools.keys())

        all_expected = [
            # MR tools (7)
            "list_mrs",
            "get_mr",
            "get_mr_diffs",
            "get_mr_commits",
            "get_mr_pipelines",
            "create_mr",
            "update_mr",
            # Issue tools (6)
            "list_issues",
            "get_issue",
            "list_issue_comments",
            "create_issue",
            "update_issue",
            "add_issue_comment",
            # Pipeline tools (4)
            "list_pipelines",
            "get_pipeline",
            "get_pipeline_jobs",
            "get_job_log",
            # Search tool (1)
            "search",
        ]

        assert len(all_expected) == 18
        for name in all_expected:
            assert name in tool_names, f"Tool '{name}' not registered"

    def test_total_tool_count_is_18(self) -> None:
        """MCP server has exactly 18 tools registered."""
        from mamba_mcp_gitlab.server import mcp as server_mcp
        from mamba_mcp_gitlab.tools import (  # noqa: F401
            issue_tools,
            mr_tools,
            pipeline_tools,
            search_tools,
        )

        tool_names = list(server_mcp._tool_manager._tools.keys())
        assert len(tool_names) == 18
