"""Tests for read-only mode and project/group scoping.

Covers:
- check_read_only helper function
- Write tools blocked in read-only mode (create_mr, update_mr, create_issue,
  update_issue, add_issue_comment)
- Write tools allowed when read_only=false
- Read tools unaffected by read-only mode
- Default project ID injection via _resolve_project_id
- Default group ID injection for search scope
- WRITE_TOOL_NAMES constant
- Both defaults set simultaneously
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_gitlab.errors import (
    ERROR_SUGGESTIONS,
    WRITE_TOOL_NAMES,
    ErrorCode,
    check_read_only,
    create_tool_error,
)
from mamba_mcp_gitlab.services.base import GitLabAPIError, GitLabService
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
    list_mrs,
    update_mr,
)
from mamba_mcp_gitlab.tools.pipeline_tools import (
    list_pipelines,
)
from mamba_mcp_gitlab.tools.search_tools import search

from tests.gitlab.conftest import make_settings

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

TEST_PROJECT_ID = 42
TEST_GITLAB_URL = "https://gitlab.example.com"


@dataclass
class _FakeAppContext:
    """Minimal AppContext for tool handler tests."""

    client: Any = None
    settings: Any = None


@dataclass
class _FakeRequestContext:
    """Minimal RequestContext for tool handler tests."""

    lifespan_context: _FakeAppContext


def _make_ctx(
    *,
    read_only: bool = False,
    default_project_id: int | None = None,
    default_group_id: int | None = None,
) -> MagicMock:
    """Build a mock MCP context with configurable read-only and default scoping."""
    settings = make_settings(
        read_only=read_only,
        default_project_id=default_project_id,
        default_group_id=default_group_id,
    )
    app_ctx = _FakeAppContext(client=MagicMock(), settings=settings)
    ctx = MagicMock()
    ctx.request_context = _FakeRequestContext(lifespan_context=app_ctx)
    return ctx


def _make_mr_detail() -> dict[str, Any]:
    """Build a minimal MR detail dict for service mock returns."""
    return {
        "id": 101,
        "iid": 1,
        "title": "Test MR",
        "state": "opened",
        "author": {"id": 1, "username": "dev", "name": "Dev"},
        "source_branch": "feature",
        "target_branch": "main",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "web_url": f"{TEST_GITLAB_URL}/project/-/merge_requests/1",
        "description": "A merge request",
        "assignees": [],
        "reviewers": [],
        "labels": [],
        "merge_status": "can_be_merged",
        "diff_refs": None,
        "pipeline": None,
    }


def _make_issue_detail() -> dict[str, Any]:
    """Build a minimal issue detail dict for service mock returns."""
    return {
        "id": 201,
        "iid": 1,
        "title": "Test Issue",
        "state": "opened",
        "author": {"id": 1, "username": "dev", "name": "Dev", "avatar_url": None},
        "assignees": [],
        "labels": [],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "web_url": f"{TEST_GITLAB_URL}/project/issues/1",
        "description": "An issue",
        "milestone": None,
        "user_notes_count": 0,
        "upvotes": 0,
        "downvotes": 0,
    }


def _make_comment() -> dict[str, Any]:
    """Build a minimal comment dict for service mock returns."""
    return {
        "id": 501,
        "body": "A comment",
        "author": {"id": 1, "username": "dev", "name": "Dev", "avatar_url": None},
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "system": False,
    }


# ===========================================================================
# Tests: check_read_only helper
# ===========================================================================


class TestCheckReadOnly:
    """Tests for the check_read_only helper function."""

    def test_returns_none_when_not_read_only(self) -> None:
        """check_read_only returns None when read_only is False."""
        result = check_read_only(False, "create_mr")
        assert result is None

    def test_returns_error_dict_when_read_only(self) -> None:
        """check_read_only returns a structured error dict when read_only is True."""
        result = check_read_only(True, "create_mr")
        assert result is not None
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY
        assert "create_mr" in result["message"]
        assert "read-only" in result["message"]

    def test_error_includes_tool_name(self) -> None:
        """Error dict contains the correct tool_name."""
        result = check_read_only(True, "update_issue")
        assert result is not None
        assert result["tool_name"] == "update_issue"

    def test_error_includes_suggestion(self) -> None:
        """Error dict includes the default READ_ONLY suggestion."""
        result = check_read_only(True, "add_issue_comment")
        assert result is not None
        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.READ_ONLY]

    @pytest.mark.parametrize("tool_name", sorted(WRITE_TOOL_NAMES))
    def test_works_for_all_write_tools(self, tool_name: str) -> None:
        """check_read_only works for every write tool name."""
        result = check_read_only(True, tool_name)
        assert result is not None
        assert result["code"] == ErrorCode.READ_ONLY
        assert tool_name in result["message"]


# ===========================================================================
# Tests: WRITE_TOOL_NAMES constant
# ===========================================================================


class TestWriteToolNames:
    """Tests for the WRITE_TOOL_NAMES constant."""

    def test_contains_exactly_five_tools(self) -> None:
        """WRITE_TOOL_NAMES has exactly 5 write tools."""
        assert len(WRITE_TOOL_NAMES) == 5

    def test_contains_expected_tools(self) -> None:
        """WRITE_TOOL_NAMES contains all expected write tool names."""
        expected = {"create_mr", "update_mr", "create_issue", "update_issue", "add_issue_comment"}
        assert WRITE_TOOL_NAMES == expected

    def test_is_frozenset(self) -> None:
        """WRITE_TOOL_NAMES is a frozenset (immutable)."""
        assert isinstance(WRITE_TOOL_NAMES, frozenset)


# ===========================================================================
# Tests: READ_ONLY error code
# ===========================================================================


class TestReadOnlyErrorCode:
    """Tests for the READ_ONLY error code and its suggestion."""

    def test_error_code_exists(self) -> None:
        """ErrorCode.READ_ONLY is defined."""
        assert ErrorCode.READ_ONLY == "READ_ONLY"

    def test_suggestion_exists(self) -> None:
        """ERROR_SUGGESTIONS has a mapping for READ_ONLY."""
        assert ErrorCode.READ_ONLY in ERROR_SUGGESTIONS

    def test_suggestion_mentions_env_var(self) -> None:
        """READ_ONLY suggestion mentions the environment variable to change."""
        suggestion = ERROR_SUGGESTIONS[ErrorCode.READ_ONLY]
        assert "MAMBA_MCP_GITLAB_READ_ONLY" in suggestion

    def test_create_tool_error_uses_read_only_code(self) -> None:
        """create_tool_error produces correct error with READ_ONLY code."""
        error = create_tool_error(
            ErrorCode.READ_ONLY,
            "Tool disabled",
            "create_mr",
        )
        assert error["code"] == "READ_ONLY"


# ===========================================================================
# Tests: MR write tools blocked in read-only mode
# ===========================================================================


class TestMrWriteToolsReadOnly:
    """Tests that MR write tools are blocked in read-only mode."""

    async def test_create_mr_blocked(self) -> None:
        """create_mr returns READ_ONLY error when read_only=true."""
        ctx = _make_ctx(read_only=True)
        result = await create_mr(
            project_id=TEST_PROJECT_ID,
            title="New MR",
            source_branch="feature",
            target_branch="main",
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY
        assert "create_mr" in result["message"]

    async def test_update_mr_blocked(self) -> None:
        """update_mr returns READ_ONLY error when read_only=true."""
        ctx = _make_ctx(read_only=True)
        result = await update_mr(
            project_id=TEST_PROJECT_ID,
            mr_iid=1,
            title="Updated Title",
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY
        assert "update_mr" in result["message"]

    async def test_create_mr_blocked_does_not_call_service(self) -> None:
        """create_mr does not create a service when read_only=true."""
        ctx = _make_ctx(read_only=True)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                ctx=ctx,
            )
            mock_svc.assert_not_called()

    async def test_update_mr_blocked_does_not_call_service(self) -> None:
        """update_mr does not create a service when read_only=true."""
        ctx = _make_ctx(read_only=True)
        with patch("mamba_mcp_gitlab.tools.mr_tools.MergeRequestService") as mock_svc:
            await update_mr(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                ctx=ctx,
            )
            mock_svc.assert_not_called()


# ===========================================================================
# Tests: Issue write tools blocked in read-only mode
# ===========================================================================


class TestIssueWriteToolsReadOnly:
    """Tests that issue write tools are blocked in read-only mode."""

    async def test_create_issue_blocked(self) -> None:
        """create_issue returns READ_ONLY error when read_only=true."""
        ctx = _make_ctx(read_only=True)
        result = await create_issue(
            project_id=TEST_PROJECT_ID,
            title="New Issue",
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY
        assert "create_issue" in result["message"]

    async def test_update_issue_blocked(self) -> None:
        """update_issue returns READ_ONLY error when read_only=true."""
        ctx = _make_ctx(read_only=True)
        result = await update_issue(
            project_id=TEST_PROJECT_ID,
            issue_iid=1,
            title="Updated Title",
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY
        assert "update_issue" in result["message"]

    async def test_add_issue_comment_blocked(self) -> None:
        """add_issue_comment returns READ_ONLY error when read_only=true."""
        ctx = _make_ctx(read_only=True)
        result = await add_issue_comment(
            project_id=TEST_PROJECT_ID,
            issue_iid=1,
            body="A comment",
            ctx=ctx,
        )
        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.READ_ONLY
        assert "add_issue_comment" in result["message"]

    async def test_create_issue_blocked_does_not_call_service(self) -> None:
        """create_issue does not create a service when read_only=true."""
        ctx = _make_ctx(read_only=True)
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService") as mock_svc:
            await create_issue(
                project_id=TEST_PROJECT_ID,
                title="New Issue",
                ctx=ctx,
            )
            mock_svc.assert_not_called()

    async def test_update_issue_blocked_does_not_call_service(self) -> None:
        """update_issue does not create a service when read_only=true."""
        ctx = _make_ctx(read_only=True)
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService") as mock_svc:
            await update_issue(
                project_id=TEST_PROJECT_ID,
                issue_iid=1,
                ctx=ctx,
            )
            mock_svc.assert_not_called()

    async def test_add_comment_blocked_does_not_call_service(self) -> None:
        """add_issue_comment does not create a service when read_only=true."""
        ctx = _make_ctx(read_only=True)
        with patch("mamba_mcp_gitlab.tools.issue_tools.IssueService") as mock_svc:
            await add_issue_comment(
                project_id=TEST_PROJECT_ID,
                issue_iid=1,
                body="A comment",
                ctx=ctx,
            )
            mock_svc.assert_not_called()


# ===========================================================================
# Tests: Write tools allowed when read_only=false
# ===========================================================================


class TestWriteToolsAllowedWhenNotReadOnly:
    """Tests that write tools work normally when read_only=false."""

    async def test_create_mr_succeeds(self) -> None:
        """create_mr delegates to service when read_only=false."""
        ctx = _make_ctx(read_only=False)
        mock_service = AsyncMock()
        mock_service.create_mr.return_value = _make_mr_detail()

        with patch(
            "mamba_mcp_gitlab.tools.mr_tools.MergeRequestService",
            return_value=mock_service,
        ):
            result = await create_mr(
                project_id=TEST_PROJECT_ID,
                title="New MR",
                source_branch="feature",
                target_branch="main",
                ctx=ctx,
            )

        assert not isinstance(result, dict) or result.get("code") != ErrorCode.READ_ONLY
        mock_service.create_mr.assert_called_once()

    async def test_update_mr_succeeds(self) -> None:
        """update_mr delegates to service when read_only=false."""
        ctx = _make_ctx(read_only=False)
        mock_service = AsyncMock()
        mock_service.update_mr.return_value = _make_mr_detail()

        with patch(
            "mamba_mcp_gitlab.tools.mr_tools.MergeRequestService",
            return_value=mock_service,
        ):
            result = await update_mr(
                project_id=TEST_PROJECT_ID,
                mr_iid=1,
                title="Updated",
                ctx=ctx,
            )

        assert not isinstance(result, dict) or result.get("code") != ErrorCode.READ_ONLY
        mock_service.update_mr.assert_called_once()

    async def test_create_issue_succeeds(self) -> None:
        """create_issue delegates to service when read_only=false."""
        ctx = _make_ctx(read_only=False)
        mock_service = AsyncMock()
        mock_service.create_issue.return_value = _make_issue_detail()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await create_issue(
                project_id=TEST_PROJECT_ID,
                title="New Issue",
                ctx=ctx,
            )

        assert not isinstance(result, dict) or result.get("code") != ErrorCode.READ_ONLY
        mock_service.create_issue.assert_called_once()

    async def test_update_issue_succeeds(self) -> None:
        """update_issue delegates to service when read_only=false."""
        ctx = _make_ctx(read_only=False)
        mock_service = AsyncMock()
        mock_service.update_issue.return_value = _make_issue_detail()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await update_issue(
                project_id=TEST_PROJECT_ID,
                issue_iid=1,
                title="Updated",
                ctx=ctx,
            )

        assert not isinstance(result, dict) or result.get("code") != ErrorCode.READ_ONLY
        mock_service.update_issue.assert_called_once()

    async def test_add_issue_comment_succeeds(self) -> None:
        """add_issue_comment delegates to service when read_only=false."""
        ctx = _make_ctx(read_only=False)
        mock_service = AsyncMock()
        mock_service.add_issue_comment.return_value = _make_comment()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await add_issue_comment(
                project_id=TEST_PROJECT_ID,
                issue_iid=1,
                body="A comment",
                ctx=ctx,
            )

        assert not isinstance(result, dict) or result.get("code") != ErrorCode.READ_ONLY
        mock_service.add_issue_comment.assert_called_once()


# ===========================================================================
# Tests: Read tools unaffected by read-only mode
# ===========================================================================


class TestReadToolsUnaffectedByReadOnly:
    """Tests that read tools work normally regardless of read-only mode."""

    async def test_list_mrs_works_in_read_only(self) -> None:
        """list_mrs delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True, default_project_id=TEST_PROJECT_ID)
        mock_service = AsyncMock()
        mock_service.list_mrs.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch(
            "mamba_mcp_gitlab.tools.mr_tools.MergeRequestService",
            return_value=mock_service,
        ):
            result = await list_mrs(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.list_mrs.assert_called_once()

    async def test_get_mr_works_in_read_only(self) -> None:
        """get_mr delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True)
        mock_service = AsyncMock()
        mock_service.get_mr.return_value = _make_mr_detail()

        with patch(
            "mamba_mcp_gitlab.tools.mr_tools.MergeRequestService",
            return_value=mock_service,
        ):
            result = await get_mr(project_id=TEST_PROJECT_ID, mr_iid=1, ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.get_mr.assert_called_once()

    async def test_list_issues_works_in_read_only(self) -> None:
        """list_issues delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True)
        mock_service = AsyncMock()
        mock_service.list_issues.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issues(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.list_issues.assert_called_once()

    async def test_get_issue_works_in_read_only(self) -> None:
        """get_issue delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True)
        mock_service = AsyncMock()
        mock_service.get_issue.return_value = _make_issue_detail()

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await get_issue(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.get_issue.assert_called_once()

    async def test_list_issue_comments_works_in_read_only(self) -> None:
        """list_issue_comments delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True)
        mock_service = AsyncMock()
        mock_service.list_issue_comments.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch(
            "mamba_mcp_gitlab.tools.issue_tools.IssueService",
            return_value=mock_service,
        ):
            result = await list_issue_comments(project_id=TEST_PROJECT_ID, issue_iid=1, ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.list_issue_comments.assert_called_once()

    async def test_list_pipelines_works_in_read_only(self) -> None:
        """list_pipelines delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True)
        mock_service = AsyncMock()
        mock_service.list_pipelines.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }

        with patch(
            "mamba_mcp_gitlab.tools.pipeline_tools.PipelineService",
            return_value=mock_service,
        ):
            result = await list_pipelines(project_id=TEST_PROJECT_ID, ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.list_pipelines.assert_called_once()

    async def test_search_works_in_read_only(self) -> None:
        """search delegates to service even in read-only mode."""
        ctx = _make_ctx(read_only=True, default_project_id=TEST_PROJECT_ID)
        mock_service = AsyncMock()
        mock_service.search.return_value = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
            "query": "test",
            "scope": "issues",
        }

        with patch(
            "mamba_mcp_gitlab.tools.search_tools.SearchService",
            return_value=mock_service,
        ):
            result = await search(query="test", scope="issues", ctx=ctx)

        assert not isinstance(result, dict)
        mock_service.search.assert_called_once()


# ===========================================================================
# Tests: Default project ID scoping
# ===========================================================================


class TestDefaultProjectIdScoping:
    """Tests for default_project_id injection via _resolve_project_id."""

    def test_explicit_project_id_overrides_default(self) -> None:
        """Explicit project_id always takes priority over default."""
        settings = make_settings(default_project_id=99)
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        resolved = service._resolve_project_id(42)
        assert resolved == 42

    def test_default_used_when_none_provided(self) -> None:
        """Default project_id used when explicit is None."""
        settings = make_settings(default_project_id=99)
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        resolved = service._resolve_project_id(None)
        assert resolved == 99

    def test_default_used_when_omitted(self) -> None:
        """Default project_id used when no argument is passed."""
        settings = make_settings(default_project_id=99)
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        resolved = service._resolve_project_id()
        assert resolved == 99

    def test_raises_when_no_default_and_none_provided(self) -> None:
        """Raises VALIDATION_ERROR when no project_id and no default."""
        settings = make_settings(default_project_id=None)
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        with pytest.raises(GitLabAPIError) as exc_info:
            service._resolve_project_id(None)
        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert "No project_id" in str(exc_info.value)

    def test_string_project_id_overrides_default(self) -> None:
        """String project path overrides default integer ID."""
        settings = make_settings(default_project_id=99)
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        resolved = service._resolve_project_id("my-group/my-project")
        assert resolved == "my-group/my-project"


# ===========================================================================
# Tests: Default group ID scoping for search
# ===========================================================================


class TestDefaultGroupIdScoping:
    """Tests for default_group_id injection in search scope."""

    def test_search_uses_default_group_when_no_explicit(self) -> None:
        """SearchService._resolve_search_path uses default_group_id."""
        from mamba_mcp_gitlab.services.search_service import SearchService

        settings = make_settings(default_group_id=55)
        service = SearchService(
            http_client=MagicMock(),
            settings=settings,
        )
        path = service._resolve_search_path()
        assert path == "/groups/55/search"

    def test_search_uses_default_project_over_default_group(self) -> None:
        """default_project_id takes priority over default_group_id."""
        from mamba_mcp_gitlab.services.search_service import SearchService

        settings = make_settings(default_project_id=42, default_group_id=55)
        service = SearchService(
            http_client=MagicMock(),
            settings=settings,
        )
        path = service._resolve_search_path()
        assert path == "/projects/42/search"

    def test_explicit_group_overrides_defaults(self) -> None:
        """Explicit group_id overrides both default_project_id and default_group_id."""
        from mamba_mcp_gitlab.services.search_service import SearchService

        settings = make_settings(default_project_id=42, default_group_id=55)
        service = SearchService(
            http_client=MagicMock(),
            settings=settings,
        )
        path = service._resolve_search_path(group_id=77)
        assert path == "/groups/77/search"

    def test_explicit_project_overrides_all(self) -> None:
        """Explicit project_id overrides everything."""
        from mamba_mcp_gitlab.services.search_service import SearchService

        settings = make_settings(default_project_id=42, default_group_id=55)
        service = SearchService(
            http_client=MagicMock(),
            settings=settings,
        )
        path = service._resolve_search_path(project_id=100)
        assert path == "/projects/100/search"

    def test_instance_wide_when_no_defaults(self) -> None:
        """Falls back to instance-wide search when no defaults."""
        from mamba_mcp_gitlab.services.search_service import SearchService

        settings = make_settings()
        service = SearchService(
            http_client=MagicMock(),
            settings=settings,
        )
        path = service._resolve_search_path()
        assert path == "/search"


# ===========================================================================
# Tests: Both defaults set simultaneously
# ===========================================================================


class TestBothDefaultsSimultaneously:
    """Tests that both default_project_id and default_group_id can be set."""

    def test_both_defaults_in_settings(self) -> None:
        """Settings accept both default_project_id and default_group_id."""
        settings = make_settings(default_project_id=42, default_group_id=55)
        assert settings.gitlab.default_project_id == 42
        assert settings.gitlab.default_group_id == 55

    def test_project_scoping_uses_project_default(self) -> None:
        """_resolve_project_id uses default_project_id even when group_id is set."""
        settings = make_settings(default_project_id=42, default_group_id=55)
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        resolved = service._resolve_project_id()
        assert resolved == 42

    def test_search_scoping_uses_project_over_group(self) -> None:
        """Search uses default_project_id over default_group_id."""
        from mamba_mcp_gitlab.services.search_service import SearchService

        settings = make_settings(default_project_id=42, default_group_id=55)
        service = SearchService(
            http_client=MagicMock(),
            settings=settings,
        )
        path = service._resolve_search_path()
        assert path == "/projects/42/search"

    def test_read_only_with_both_defaults(self) -> None:
        """Read-only mode works alongside both default project and group IDs."""
        settings = make_settings(
            read_only=True,
            default_project_id=42,
            default_group_id=55,
        )
        assert settings.gitlab.read_only is True
        assert settings.gitlab.default_project_id == 42
        assert settings.gitlab.default_group_id == 55


# ===========================================================================
# Tests: Missing project_id validation error
# ===========================================================================


class TestMissingProjectIdValidation:
    """Tests for clear VALIDATION_ERROR when project_id is missing."""

    def test_validation_error_message_is_clear(self) -> None:
        """Error message explains what is missing and what to configure."""
        settings = make_settings()
        service = GitLabService(
            http_client=MagicMock(),
            settings=settings,
        )
        with pytest.raises(GitLabAPIError) as exc_info:
            service._resolve_project_id()
        assert "project_id" in str(exc_info.value)
        assert "default_project_id" in str(exc_info.value)
        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
