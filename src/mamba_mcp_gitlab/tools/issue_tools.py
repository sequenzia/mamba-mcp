"""MCP tool handlers for issue operations.

Provides 6 tools following the 7-step handler skeleton:

Read tools (always registered):
  - list_issues: Paginated issue listing with filters
  - get_issue: Full issue detail by IID
  - list_issue_comments: Paginated comments on an issue

Write tools (conditionally registered when read_only=false):
  - create_issue: Create a new issue
  - update_issue: Update an existing issue
  - add_issue_comment: Add a comment to an issue

Based on Spec Section 5.2.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from mamba_mcp_gitlab.errors import (
    ErrorCode,
    build_error_context,
    check_read_only,
    clamp_pagination,
    create_tool_error,
)
from mamba_mcp_gitlab.models.issues import (
    IssueComment,
    IssueCommentsOutput,
    IssueDetail,
    IssueSummary,
    ListIssuesOutput,
)
from mamba_mcp_gitlab.server import AppContext, mcp
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.issue_service import IssueService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read tools (always registered)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_issues(
    project_id: str | int,
    state: str | None = None,
    labels: str | None = None,
    assignee_id: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListIssuesOutput | dict[str, Any]:
    """List issues for a GitLab project with optional filters.

    Returns a paginated list of issues. Use state, labels, and assignee_id
    to narrow results. Labels should be passed as a comma-separated string
    (e.g., "bug,urgent"). The assignee_id filter accepts a single user ID.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        state: Filter by state: "opened", "closed", or "all". Default: all.
        labels: Comma-separated label names to filter by (e.g., "bug,urgent").
        assignee_id: Filter by a single assignee user ID.
        page: Page number (1-indexed). Default: 1.
        per_page: Items per page (1-100). Default: 20.

    Returns:
        Paginated list of issue summaries with metadata.

    Example:
        list_issues(project_id=42, state="opened", labels="bug")
    """
    start_time = time.perf_counter()
    page, per_page = clamp_pagination(page, per_page)
    logger.debug(
        "list_issues called: project_id=%s, state=%s, labels=%s, "
        "assignee_id=%s, page=%d, per_page=%d",
        project_id,
        state,
        labels,
        assignee_id,
        page,
        per_page,
    )

    # Step 1: Null-check context
    if ctx is None:
        logger.error("list_issues: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "list_issues",
        )

    # Step 2: Extract app context
    app_ctx: AppContext = ctx.request_context.lifespan_context

    try:
        # Step 3: Create service
        service = IssueService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        # Step 4: Delegate to service
        result = await service.list_issues(
            project_id=project_id,
            state=state,
            labels=labels,
            assignee_id=assignee_id,
            page=page,
            per_page=per_page,
        )

        # Step 5: Convert to output model
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_issues completed in %.2fms, returned %d items",
            elapsed_ms,
            len(result["items"]),
        )
        return ListIssuesOutput(
            items=[IssueSummary(**item) for item in result["items"]],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        # Step 6: Map service errors to structured response
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_issues failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "list_issues",
            {"project_id": project_id, "state": state},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )
    except Exception as exc:
        # Step 7: Catch-all for unexpected errors
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_issues failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "list_issues",
            {"project_id": project_id},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_issue(
    project_id: str | int,
    issue_iid: int,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> IssueDetail | dict[str, Any]:
    """Get full details of a single issue by its project-level IID.

    Returns comprehensive issue information including title, description,
    author, assignees, labels, milestone, state, and comment count.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        issue_iid: Project-level issue IID (the number shown in the GitLab UI).

    Returns:
        Full issue details including description and metadata.

    Example:
        get_issue(project_id=42, issue_iid=7)
    """
    start_time = time.perf_counter()
    logger.debug("get_issue called: project_id=%s, issue_iid=%d", project_id, issue_iid)

    if ctx is None:
        logger.error("get_issue: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_issue",
        )

    app_ctx: AppContext = ctx.request_context.lifespan_context

    try:
        service = IssueService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.get_issue(
            project_id=project_id,
            issue_iid=issue_iid,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("get_issue completed in %.2fms", elapsed_ms)
        return IssueDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_issue failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_issue",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_issue failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_issue",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_issue_comments(
    project_id: str | int,
    issue_iid: int,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> IssueCommentsOutput | dict[str, Any]:
    """List comments (notes) on a specific issue.

    Returns a paginated list of comments on the given issue. Includes
    both user comments and system-generated notes.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        issue_iid: Project-level issue IID.
        page: Page number (1-indexed). Default: 1.
        per_page: Items per page (1-100). Default: 20.

    Returns:
        Paginated list of issue comments.

    Example:
        list_issue_comments(project_id=42, issue_iid=7)
    """
    start_time = time.perf_counter()
    page, per_page = clamp_pagination(page, per_page)
    logger.debug(
        "list_issue_comments called: project_id=%s, issue_iid=%d, page=%d, per_page=%d",
        project_id,
        issue_iid,
        page,
        per_page,
    )

    if ctx is None:
        logger.error("list_issue_comments: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "list_issue_comments",
        )

    app_ctx: AppContext = ctx.request_context.lifespan_context

    try:
        service = IssueService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.list_issue_comments(
            project_id=project_id,
            issue_iid=issue_iid,
            page=page,
            per_page=per_page,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_issue_comments completed in %.2fms, returned %d comments",
            elapsed_ms,
            len(result["items"]),
        )
        return IssueCommentsOutput(
            items=[IssueComment(**item) for item in result["items"]],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_issue_comments failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "list_issue_comments",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_issue_comments failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "list_issue_comments",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


# ---------------------------------------------------------------------------
# Write tools (gated at runtime by read-only mode check)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def create_issue(
    project_id: str | int,
    title: str,
    description: str | None = None,
    assignee_ids: list[int] | None = None,
    labels: str | None = None,
    milestone_id: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> IssueDetail | dict[str, Any]:
    """Create a new issue in a GitLab project.

    Creates an issue with the given title and optional fields. Use labels
    as a comma-separated string (e.g., "bug,urgent"). Assignee IDs is a
    list of user IDs to assign (multiple assignees supported).

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        title: Issue title (required).
        description: Issue description in Markdown format.
        assignee_ids: List of user IDs to assign to the issue.
        labels: Comma-separated label names (e.g., "bug,urgent").
        milestone_id: Milestone ID to associate with the issue.

    Returns:
        Full details of the newly created issue.

    Example:
        create_issue(project_id=42, title="Fix login bug", labels="bug,high-priority")
    """
    start_time = time.perf_counter()
    logger.debug(
        "create_issue called: project_id=%s, title=%s, labels=%s, milestone_id=%s",
        project_id,
        title,
        labels,
        milestone_id,
    )

    if ctx is None:
        logger.error("create_issue: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "create_issue",
        )

    app_ctx: AppContext = ctx.request_context.lifespan_context

    # Read-only mode gate
    read_only_error = check_read_only(app_ctx.settings.gitlab.read_only, "create_issue")
    if read_only_error is not None:
        return read_only_error

    try:
        service = IssueService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.create_issue(
            project_id=project_id,
            title=title,
            description=description,
            assignee_ids=assignee_ids,
            labels=labels,
            milestone_id=milestone_id,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("create_issue completed in %.2fms", elapsed_ms)
        return IssueDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("create_issue failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "create_issue",
            {"project_id": project_id, "title": title},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("create_issue failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "create_issue",
            {"project_id": project_id, "title": title},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def update_issue(
    project_id: str | int,
    issue_iid: int,
    title: str | None = None,
    description: str | None = None,
    assignee_ids: list[int] | None = None,
    labels: str | None = None,
    state_event: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> IssueDetail | dict[str, Any]:
    """Update an existing issue in a GitLab project.

    Modify any combination of issue fields. Only fields that are provided
    will be updated. Use state_event to close ("close") or reopen ("reopen")
    an issue. Labels replace the full set when provided.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        issue_iid: Project-level issue IID to update.
        title: New issue title.
        description: New issue description in Markdown format.
        assignee_ids: New list of assignee user IDs.
        labels: New comma-separated label names (replaces existing labels).
        state_event: State transition: "close" or "reopen".

    Returns:
        Full details of the updated issue.

    Example:
        update_issue(project_id=42, issue_iid=7, state_event="close")
    """
    start_time = time.perf_counter()
    logger.debug(
        "update_issue called: project_id=%s, issue_iid=%d, state_event=%s",
        project_id,
        issue_iid,
        state_event,
    )

    if ctx is None:
        logger.error("update_issue: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "update_issue",
        )

    app_ctx: AppContext = ctx.request_context.lifespan_context

    # Read-only mode gate
    read_only_error = check_read_only(app_ctx.settings.gitlab.read_only, "update_issue")
    if read_only_error is not None:
        return read_only_error

    try:
        service = IssueService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.update_issue(
            project_id=project_id,
            issue_iid=issue_iid,
            title=title,
            description=description,
            assignee_ids=assignee_ids,
            labels=labels,
            state_event=state_event,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("update_issue completed in %.2fms", elapsed_ms)
        return IssueDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("update_issue failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "update_issue",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("update_issue failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "update_issue",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def add_issue_comment(
    project_id: str | int,
    issue_iid: int,
    body: str,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> IssueComment | dict[str, Any]:
    """Add a comment (note) to an existing issue.

    Posts a new comment on the specified issue. The comment body supports
    Markdown formatting.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        issue_iid: Project-level issue IID to comment on.
        body: Comment text in Markdown format.

    Returns:
        The newly created comment with metadata.

    Example:
        add_issue_comment(project_id=42, issue_iid=7, body="Fixed in commit abc123")
    """
    start_time = time.perf_counter()
    logger.debug(
        "add_issue_comment called: project_id=%s, issue_iid=%d",
        project_id,
        issue_iid,
    )

    if ctx is None:
        logger.error("add_issue_comment: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "add_issue_comment",
        )

    app_ctx: AppContext = ctx.request_context.lifespan_context

    # Read-only mode gate
    read_only_error = check_read_only(app_ctx.settings.gitlab.read_only, "add_issue_comment")
    if read_only_error is not None:
        return read_only_error

    try:
        service = IssueService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.add_issue_comment(
            project_id=project_id,
            issue_iid=issue_iid,
            body=body,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("add_issue_comment completed in %.2fms", elapsed_ms)
        return IssueComment(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("add_issue_comment failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "add_issue_comment",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("add_issue_comment failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "add_issue_comment",
            {"project_id": project_id, "issue_iid": issue_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )
