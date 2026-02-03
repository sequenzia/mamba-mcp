"""Tests for merge request MCP tool handlers.

Covers all 7 tool handlers: list_mrs, get_mr, get_mr_diffs,
get_mr_commits, get_mr_pipelines, create_mr, update_mr.

Tests verify:
- Each handler calls the correct service method
- Context None returns CONNECTION_ERROR
- GitLabAPIError is caught and returned as structured error
- Generic exceptions are caught and returned as structured error
- Empty results produce valid output
- Pagination clamping is applied
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.models.merge_requests import (
    ListMergeRequestsOutput,
    MergeRequestCommitsOutput,
    MergeRequestDetail,
    MergeRequestDiffsOutput,
)
from mamba_mcp_gitlab.models.pipelines import ListPipelinesOutput
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.tools.mr_tools import (
    create_mr,
    get_mr,
    get_mr_commits,
    get_mr_diffs,
    get_mr_pipelines,
    list_mrs,
    update_mr,
)

from tests.conftest import make_settings

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

TEST_GITLAB_URL = "https://gitlab.example.com"
TEST_PROJECT_ID = 42


def _make_mr_summary(iid: int = 1) -> dict[str, Any]:
    """Build a minimal MR summary dict matching MergeRequestSummary fields."""
    return {
        "id": 100 + iid,
        "iid": iid,
        "title": f"MR !{iid}",
        "state": "opened",
        "author": {"id": 1, "username": "dev", "name": "Dev User"},
        "source_branch": "feature",
        "target_branch": "main",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "web_url": f"{TEST_GITLAB_URL}/project/-/merge_requests/{iid}",
    }


def _make_mr_detail(iid: int = 1) -> dict[str, Any]:
    """Build a minimal MR detail dict matching MergeRequestDetail fields."""
    base = _make_mr_summary(iid)
    base.update(
        {
            "description": "A merge request",
            "assignees": [],
            "reviewers": [],
            "labels": ["bug"],
            "merge_status": "can_be_merged",
            "diff_refs": None,
            "pipeline": None,
        }
    )
    return base


def _make_diff_item() -> dict[str, Any]:
    """Build a minimal diff dict matching MergeRequestDiff fields."""
    return {
        "old_path": "src/old.py",
        "new_path": "src/new.py",
        "diff": "@@ -1 +1 @@\n-old\n+new",
        "new_file": False,
        "renamed_file": True,
        "deleted_file": False,
    }


def _make_commit_item(sha: str = "abc123") -> dict[str, Any]:
    """Build a minimal commit dict matching MergeRequestCommit fields."""
    return {
        "id": sha,
        "short_id": sha[:7],
        "title": "Fix bug",
        "author_name": "Dev User",
        "authored_date": "2025-01-01T00:00:00Z",
        "message": "Fix bug\n\nFull description here.",
    }


def _make_pipeline_item(pipeline_id: int = 200, status: str = "success") -> dict[str, Any]:
    """Build a minimal pipeline dict matching PipelineSummary fields."""
    return {
        "id": pipeline_id,
        "iid": pipeline_id - 190,
        "status": status,
        "ref": "feature",
        "sha": "abc123def456",
        "created_at": "2025-01-15T10:00:00Z",
        "updated_at": "2025-01-15T10:30:00Z",
        "web_url": f"{TEST_GITLAB_URL}/project/-/pipelines/{pipeline_id}",
    }


@dataclass
class _MockRequestContext:
    """Mock for ctx.request_context."""

    lifespan_context: Any


@dataclass
class _MockCtx:
    """Mock for the MCP Context object passed to tool handlers."""

    request_context: _MockRequestContext


@dataclass
class _MockAppContext:
    """Minimal AppContext for tool handler tests."""

    client: Any
    settings: Any


def _make_ctx(
    *,
    default_project_id: int | None = None,
) -> _MockCtx:
    """Build a mock context for tool handler calls."""
    settings = make_settings(default_project_id=default_project_id)
    app_ctx = _MockAppContext(client=MagicMock(), settings=settings)
    return _MockCtx(request_context=_MockRequestContext(lifespan_context=app_ctx))


# ---------------------------------------------------------------------------
# list_mrs tests
# ---------------------------------------------------------------------------


class TestListMrs:
    """Tests for the list_mrs tool handler."""

    async def test_returns_paginated_output(self) -> None:
        """list_mrs returns ListMergeRequestsOutput on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [_make_mr_summary(1), _make_mr_summary(2)],
            "page": 1,
            "per_page": 20,
            "total": 2,
            "total_pages": 1,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.list_mrs = AsyncMock(return_value=service_result)
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, ListMergeRequestsOutput)
        assert len(result.items) == 2
        assert result.items[0].iid == 1
        assert result.total == 2

    async def test_calls_service_with_correct_args(self) -> None:
        """list_mrs passes state and clamped pagination to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.list_mrs = AsyncMock(return_value=service_result)
            await list_mrs(
                project_id=TEST_PROJECT_ID,
                state="opened",
                page=2,
                per_page=50,
                ctx=ctx,
            )

            mock_service.return_value.list_mrs.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                state="opened",
                page=2,
                per_page=50,
            )

    async def test_empty_results(self) -> None:
        """list_mrs returns valid output with empty items list."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.list_mrs = AsyncMock(return_value=service_result)
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, ListMergeRequestsOutput)
        assert len(result.items) == 0
        assert result.total == 0

    async def test_context_none_returns_connection_error(self) -> None:
        """list_mrs returns CONNECTION_ERROR when ctx is None."""
        result = await list_mrs(ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_gitlab_api_error_returns_structured_error(self) -> None:
        """list_mrs returns structured error on GitLabAPIError."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.list_mrs = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Project not found: 42",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PROJECT_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """list_mrs returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.list_mrs = AsyncMock(side_effect=RuntimeError("network down"))
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "network down" in result["message"]

    async def test_pagination_clamping_applied(self) -> None:
        """list_mrs clamps per_page to [1, 100] and page to >= 1."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 100,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.list_mrs = AsyncMock(return_value=service_result)
            await list_mrs(
                project_id=TEST_PROJECT_ID,
                page=-5,
                per_page=999,
                ctx=ctx,
            )

            mock_service.return_value.list_mrs.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                state=None,
                page=1,
                per_page=100,
            )


# ---------------------------------------------------------------------------
# get_mr tests
# ---------------------------------------------------------------------------


class TestGetMr:
    """Tests for the get_mr tool handler."""

    async def test_returns_mr_detail(self) -> None:
        """get_mr returns MergeRequestDetail on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr = AsyncMock(return_value=_make_mr_detail(5))
            result = await get_mr(project_id=TEST_PROJECT_ID, mr_iid=5, ctx=ctx)

        assert isinstance(result, MergeRequestDetail)
        assert result.iid == 5
        assert result.description == "A merge request"

    async def test_calls_service_with_correct_args(self) -> None:
        """get_mr passes project_id and mr_iid to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr = AsyncMock(return_value=_make_mr_detail(10))
            await get_mr(project_id=TEST_PROJECT_ID, mr_iid=10, ctx=ctx)

            mock_service.return_value.get_mr.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                mr_iid=10,
            )

    async def test_context_none_returns_connection_error(self) -> None:
        """get_mr returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr(mr_iid=1, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_mr_not_found_returns_structured_error(self) -> None:
        """get_mr returns structured error when MR not found."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Merge request !999 not found",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_mr(project_id=TEST_PROJECT_ID, mr_iid=999, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.MERGE_REQUEST_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """get_mr returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr = AsyncMock(side_effect=ValueError("unexpected"))
            result = await get_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# ---------------------------------------------------------------------------
# get_mr_diffs tests
# ---------------------------------------------------------------------------


class TestGetMrDiffs:
    """Tests for the get_mr_diffs tool handler."""

    async def test_returns_paginated_diffs(self) -> None:
        """get_mr_diffs returns MergeRequestDiffsOutput on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [_make_diff_item()],
            "page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_diffs = AsyncMock(return_value=service_result)
            result = await get_mr_diffs(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, MergeRequestDiffsOutput)
        assert len(result.items) == 1
        assert result.items[0].old_path == "src/old.py"

    async def test_empty_diffs(self) -> None:
        """get_mr_diffs returns valid output with no diffs."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_diffs = AsyncMock(return_value=service_result)
            result = await get_mr_diffs(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, MergeRequestDiffsOutput)
        assert len(result.items) == 0

    async def test_context_none_returns_connection_error(self) -> None:
        """get_mr_diffs returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr_diffs(mr_iid=1, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_gitlab_api_error_returns_structured_error(self) -> None:
        """get_mr_diffs returns structured error on GitLabAPIError."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_diffs = AsyncMock(
                side_effect=GitLabAPIError(
                    message="MR not found",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_mr_diffs(project_id=TEST_PROJECT_ID, mr_iid=99, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.MERGE_REQUEST_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """get_mr_diffs returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_diffs = AsyncMock(side_effect=OSError("timeout"))
            result = await get_mr_diffs(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_pagination_clamping_applied(self) -> None:
        """get_mr_diffs clamps pagination values before passing to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_diffs = AsyncMock(return_value=service_result)
            await get_mr_diffs(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                page=0,
                per_page=-10,
                ctx=ctx,
            )

            mock_service.return_value.get_mr_diffs.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                page=1,
                per_page=1,
            )


# ---------------------------------------------------------------------------
# get_mr_commits tests
# ---------------------------------------------------------------------------


class TestGetMrCommits:
    """Tests for the get_mr_commits tool handler."""

    async def test_returns_paginated_commits(self) -> None:
        """get_mr_commits returns MergeRequestCommitsOutput on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [_make_commit_item("abc123"), _make_commit_item("def456")],
            "page": 1,
            "per_page": 20,
            "total": 2,
            "total_pages": 1,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_commits = AsyncMock(return_value=service_result)
            result = await get_mr_commits(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, MergeRequestCommitsOutput)
        assert len(result.items) == 2
        assert result.items[0].id == "abc123"

    async def test_empty_commits(self) -> None:
        """get_mr_commits returns valid output with no commits."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_commits = AsyncMock(return_value=service_result)
            result = await get_mr_commits(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, MergeRequestCommitsOutput)
        assert len(result.items) == 0

    async def test_context_none_returns_connection_error(self) -> None:
        """get_mr_commits returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr_commits(mr_iid=1, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_gitlab_api_error_returns_structured_error(self) -> None:
        """get_mr_commits returns structured error on GitLabAPIError."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_commits = AsyncMock(
                side_effect=GitLabAPIError(
                    message="MR not found",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_mr_commits(project_id=TEST_PROJECT_ID, mr_iid=99, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.MERGE_REQUEST_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """get_mr_commits returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_commits = AsyncMock(side_effect=TypeError("bad data"))
            result = await get_mr_commits(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_pagination_clamping_applied(self) -> None:
        """get_mr_commits clamps pagination values before passing to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_commits = AsyncMock(return_value=service_result)
            await get_mr_commits(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                page=None,
                per_page=None,
                ctx=ctx,
            )

            # None values should be clamped to defaults (1, 20)
            mock_service.return_value.get_mr_commits.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                page=1,
                per_page=20,
            )


# ---------------------------------------------------------------------------
# get_mr_pipelines tests
# ---------------------------------------------------------------------------


class TestGetMrPipelines:
    """Tests for the get_mr_pipelines tool handler."""

    async def test_returns_paginated_pipelines(self) -> None:
        """get_mr_pipelines returns ListPipelinesOutput on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [_make_pipeline_item(200), _make_pipeline_item(201, "failed")],
            "page": 1,
            "per_page": 20,
            "total": 2,
            "total_pages": 1,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(return_value=service_result)
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, ListPipelinesOutput)
        assert len(result.items) == 2
        assert result.items[0].status == "success"
        assert result.items[1].status == "failed"
        assert result.total == 2

    async def test_calls_service_with_correct_args(self) -> None:
        """get_mr_pipelines passes project_id, mr_iid, and clamped pagination."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 2,
            "per_page": 10,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(return_value=service_result)
            await get_mr_pipelines(
                project_id=TEST_PROJECT_ID,
                mr_iid=5,
                page=2,
                per_page=10,
                ctx=ctx,
            )

            mock_service.return_value.get_mr_pipelines.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                mr_iid=5,
                page=2,
                per_page=10,
            )

    async def test_empty_pipelines(self) -> None:
        """get_mr_pipelines returns valid output with no pipelines."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(return_value=service_result)
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, ListPipelinesOutput)
        assert len(result.items) == 0
        assert result.total == 0

    async def test_context_none_returns_connection_error(self) -> None:
        """get_mr_pipelines returns CONNECTION_ERROR when ctx is None."""
        result = await get_mr_pipelines(mr_iid=1, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_mr_not_found_returns_structured_error(self) -> None:
        """get_mr_pipelines returns structured error when MR not found."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Merge request !999 not found",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=999, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.MERGE_REQUEST_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """get_mr_pipelines returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(
                side_effect=RuntimeError("network failure")
            )
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert "network failure" in result["message"]

    async def test_pagination_clamping_applied(self) -> None:
        """get_mr_pipelines clamps pagination values before passing to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 100,
            "total": 0,
            "total_pages": 0,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(return_value=service_result)
            await get_mr_pipelines(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                page=-1,
                per_page=500,
                ctx=ctx,
            )

            mock_service.return_value.get_mr_pipelines.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                page=1,
                per_page=100,
            )

    async def test_error_includes_input_received(self) -> None:
        """get_mr_pipelines structured error includes input_received."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Error",
                    error_code=ErrorCode.API_ERROR,
                    status_code=500,
                )
            )
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=3, ctx=ctx)

        assert isinstance(result, dict)
        assert result["input_received"]["project_id"] == TEST_PROJECT_ID
        assert result["input_received"]["mr_iid"] == 3

    async def test_reuses_list_pipelines_output_model(self) -> None:
        """get_mr_pipelines returns ListPipelinesOutput, same model as list_pipelines."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        service_result = {
            "items": [_make_pipeline_item()],
            "page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
        }

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.get_mr_pipelines = AsyncMock(return_value=service_result)
            result = await get_mr_pipelines(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, ListPipelinesOutput)
        assert hasattr(result, "items")
        assert hasattr(result, "page")
        assert hasattr(result, "per_page")
        assert hasattr(result, "total")
        assert hasattr(result, "total_pages")


# ---------------------------------------------------------------------------
# create_mr tests
# ---------------------------------------------------------------------------


class TestCreateMr:
    """Tests for the create_mr tool handler."""

    async def test_returns_mr_detail_on_success(self) -> None:
        """create_mr returns MergeRequestDetail on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.create_mr = AsyncMock(return_value=_make_mr_detail(42))
            result = await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                ctx=ctx,
            )

        assert isinstance(result, MergeRequestDetail)
        assert result.iid == 42

    async def test_passes_all_optional_params(self) -> None:
        """create_mr passes optional params to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.create_mr = AsyncMock(return_value=_make_mr_detail(1))
            await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                description="Description",
                assignee_ids=[1, 2],
                reviewer_ids=[3],
                labels=["bug", "urgent"],
                ctx=ctx,
            )

            mock_service.return_value.create_mr.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                description="Description",
                assignee_ids=[1, 2],
                reviewer_ids=[3],
                labels=["bug", "urgent"],
            )

    async def test_context_none_returns_connection_error(self) -> None:
        """create_mr returns CONNECTION_ERROR when ctx is None."""
        result = await create_mr(
            title="New MR",
            source_branch="feature",
            target_branch="main",
            ctx=None,
        )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_branch_not_found_returns_structured_error(self) -> None:
        """create_mr returns structured error when branch not found."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.create_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Branch not found",
                    error_code=ErrorCode.BRANCH_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="nonexistent",
                target_branch="main",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.BRANCH_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """create_mr returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.create_mr = AsyncMock(
                side_effect=RuntimeError("connection lost")
            )
            result = await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_error_includes_elapsed_time_in_context(self) -> None:
        """create_mr structured errors include elapsed_ms in context."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.create_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Error",
                    error_code=ErrorCode.API_ERROR,
                    status_code=500,
                )
            )
            result = await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                ctx=ctx,
            )

        assert isinstance(result, dict)
        assert "context" in result
        assert "elapsed_ms" in result["context"]


# ---------------------------------------------------------------------------
# update_mr tests
# ---------------------------------------------------------------------------


class TestUpdateMr:
    """Tests for the update_mr tool handler."""

    async def test_returns_mr_detail_on_success(self) -> None:
        """update_mr returns MergeRequestDetail on success."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)
        detail = _make_mr_detail(5)
        detail["title"] = "Updated Title"

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.update_mr = AsyncMock(return_value=detail)
            result = await update_mr(
                project_id=TEST_PROJECT_ID,
                mr_iid=5,
                title="Updated Title",
                ctx=ctx,
            )

        assert isinstance(result, MergeRequestDetail)
        assert result.title == "Updated Title"

    async def test_passes_all_params_to_service(self) -> None:
        """update_mr passes all optional params to service."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.update_mr = AsyncMock(return_value=_make_mr_detail(5))
            await update_mr(
                project_id=TEST_PROJECT_ID,
                mr_iid=5,
                title="New Title",
                description="New desc",
                assignee_ids=[1],
                reviewer_ids=[2, 3],
                labels=["feature"],
                state_event="close",
                ctx=ctx,
            )

            mock_service.return_value.update_mr.assert_called_once_with(
                project_id=TEST_PROJECT_ID,
                mr_iid=5,
                title="New Title",
                description="New desc",
                assignee_ids=[1],
                reviewer_ids=[2, 3],
                labels=["feature"],
                state_event="close",
            )

    async def test_context_none_returns_connection_error(self) -> None:
        """update_mr returns CONNECTION_ERROR when ctx is None."""
        result = await update_mr(mr_iid=1, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_mr_not_found_returns_structured_error(self) -> None:
        """update_mr returns structured error when MR not found."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.update_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message="MR !999 not found",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await update_mr(project_id=TEST_PROJECT_ID, mr_iid=999, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.MERGE_REQUEST_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """update_mr returns CONNECTION_ERROR on unexpected exception."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.update_mr = AsyncMock(side_effect=KeyError("missing field"))
            result = await update_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_error_includes_input_received(self) -> None:
        """update_mr structured error includes input_received with project_id and mr_iid."""
        ctx = _make_ctx(default_project_id=TEST_PROJECT_ID)

        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_service:
            mock_service.return_value.update_mr = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Error",
                    error_code=ErrorCode.API_ERROR,
                    status_code=500,
                )
            )
            result = await update_mr(project_id=TEST_PROJECT_ID, mr_iid=7, ctx=ctx)

        assert isinstance(result, dict)
        assert result["input_received"]["project_id"] == TEST_PROJECT_ID
        assert result["input_received"]["mr_iid"] == 7


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests that all 7 MR tools are registered on the mcp instance."""

    def test_all_tools_registered(self) -> None:
        """Verify all 7 MR tools are registered with the MCP server."""
        # Import triggers tool registration via @mcp.tool() decorators
        from mamba_mcp_gitlab.server import mcp as server_mcp
        from mamba_mcp_gitlab.tools import mr_tools  # noqa: F401

        # Access tool names via the internal tool manager (synchronous)
        tool_names = list(server_mcp._tool_manager._tools.keys())
        expected = [
            "list_mrs",
            "get_mr",
            "get_mr_diffs",
            "get_mr_commits",
            "get_mr_pipelines",
            "create_mr",
            "update_mr",
        ]
        for name in expected:
            assert name in tool_names, f"Tool '{name}' not registered"
