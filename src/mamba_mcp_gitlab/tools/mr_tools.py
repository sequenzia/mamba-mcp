"""MCP tool handlers for merge request operations.

Implements 7 tools following the 7-step handler skeleton:
- Read tools: list_mrs, get_mr, get_mr_diffs, get_mr_commits, get_mr_pipelines
- Write tools: create_mr, update_mr

Based on Spec Section 5.1 and Section 4.2 (User Journey).
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
from mamba_mcp_gitlab.models.merge_requests import (
    ListMergeRequestsOutput,
    MergeRequestCommit,
    MergeRequestCommitsOutput,
    MergeRequestDetail,
    MergeRequestDiff,
    MergeRequestDiffsOutput,
    MergeRequestSummary,
)
from mamba_mcp_gitlab.models.pipelines import ListPipelinesOutput, PipelineSummary
from mamba_mcp_gitlab.server import AppContext, mcp
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.merge_request_service import MergeRequestService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read Tools (always registered)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def list_mrs(
    project_id: int | str | None = None,
    state: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListMergeRequestsOutput | dict[str, Any]:
    """List merge requests for a GitLab project.

    Returns a paginated list of merge request summaries. Filter by state
    (opened, closed, merged, all) to narrow results. Use this tool to
    discover available merge requests before fetching details.

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        state: Filter by MR state: opened, closed, merged, all.
        page: Page number (1-based). Defaults to 1.
        per_page: Items per page (1-100). Defaults to 20.
    """
    start_time = time.perf_counter()
    logger.debug(
        "list_mrs called with project_id=%s, state=%s, page=%s, per_page=%s",
        project_id,
        state,
        page,
        per_page,
    )

    if ctx is None:
        logger.error("list_mrs: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "list_mrs",
        )

    app_ctx = ctx.request_context.lifespan_context
    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    try:
        result = await service.list_mrs(
            project_id=project_id,
            state=state,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        items = result["items"]
        logger.debug(
            "list_mrs completed in %.2fms, returned %d items",
            elapsed_ms,
            len(items),
        )

        return ListMergeRequestsOutput(
            items=[MergeRequestSummary(**item) for item in items],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_mrs failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "list_mrs",
            {"project_id": project_id, "state": state},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_mrs failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "list_mrs",
            {"project_id": project_id, "state": state},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_mr(
    project_id: int | str | None = None,
    mr_iid: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> MergeRequestDetail | dict[str, Any]:
    """Get full details of a single merge request.

    Returns comprehensive merge request information including description,
    assignees, reviewers, labels, merge status, diff refs, and pipeline.
    Use list_mrs first to find the MR IID.

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        mr_iid: Merge request IID (project-level identifier).
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_mr called with project_id=%s, mr_iid=%s",
        project_id,
        mr_iid,
    )

    if ctx is None:
        logger.error("get_mr: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_mr",
        )

    app_ctx = ctx.request_context.lifespan_context
    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    try:
        result = await service.get_mr(
            project_id=project_id,
            mr_iid=mr_iid,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("get_mr completed in %.2fms", elapsed_ms)

        return MergeRequestDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_mr",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_mr",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_mr_diffs(
    project_id: int | str | None = None,
    mr_iid: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> MergeRequestDiffsOutput | dict[str, Any]:
    """Get file diffs for a merge request.

    Returns a paginated list of file-level diffs showing changes introduced
    by the merge request. Each diff includes old/new paths and unified diff
    content. Useful for code review and understanding what changed.

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        mr_iid: Merge request IID (project-level identifier).
        page: Page number (1-based). Defaults to 1.
        per_page: Items per page (1-100). Defaults to 20.
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_mr_diffs called with project_id=%s, mr_iid=%s, page=%s, per_page=%s",
        project_id,
        mr_iid,
        page,
        per_page,
    )

    if ctx is None:
        logger.error("get_mr_diffs: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_mr_diffs",
        )

    app_ctx = ctx.request_context.lifespan_context
    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    try:
        result = await service.get_mr_diffs(
            project_id=project_id,
            mr_iid=mr_iid,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        items = result["items"]
        logger.debug(
            "get_mr_diffs completed in %.2fms, returned %d diffs",
            elapsed_ms,
            len(items),
        )

        return MergeRequestDiffsOutput(
            items=[MergeRequestDiff(**item) for item in items],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr_diffs failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_mr_diffs",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr_diffs failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_mr_diffs",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_mr_commits(
    project_id: int | str | None = None,
    mr_iid: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> MergeRequestCommitsOutput | dict[str, Any]:
    """Get commits in a merge request.

    Returns a paginated list of commits included in the merge request.
    Each commit includes SHA, title, author, date, and full message.
    Useful for understanding the history of changes in an MR.

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        mr_iid: Merge request IID (project-level identifier).
        page: Page number (1-based). Defaults to 1.
        per_page: Items per page (1-100). Defaults to 20.
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_mr_commits called with project_id=%s, mr_iid=%s, page=%s, per_page=%s",
        project_id,
        mr_iid,
        page,
        per_page,
    )

    if ctx is None:
        logger.error("get_mr_commits: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_mr_commits",
        )

    app_ctx = ctx.request_context.lifespan_context
    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    try:
        result = await service.get_mr_commits(
            project_id=project_id,
            mr_iid=mr_iid,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        items = result["items"]
        logger.debug(
            "get_mr_commits completed in %.2fms, returned %d commits",
            elapsed_ms,
            len(items),
        )

        return MergeRequestCommitsOutput(
            items=[MergeRequestCommit(**item) for item in items],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr_commits failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_mr_commits",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr_commits failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_mr_commits",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_mr_pipelines(
    project_id: int | str | None = None,
    mr_iid: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListPipelinesOutput | dict[str, Any]:
    """Get pipelines associated with a merge request.

    Retrieves the list of pipelines that have run for a specific merge
    request. Use this to check if the MR's CI pipeline is passing before
    merging. Supports the user journey: "Is the pipeline passing?"

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        mr_iid: Merge request IID (project-level identifier).
        page: Page number (1-based). Defaults to 1.
        per_page: Items per page (1-100). Defaults to 20.
    """
    start_time = time.perf_counter()
    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    logger.debug(
        "get_mr_pipelines called with project_id=%s, mr_iid=%s, page=%s, per_page=%s",
        project_id,
        mr_iid,
        clamped_page,
        clamped_per_page,
    )

    if ctx is None:
        logger.error("get_mr_pipelines: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_mr_pipelines",
        )

    app_ctx = ctx.request_context.lifespan_context
    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    try:
        result = await service.get_mr_pipelines(
            project_id=project_id,
            mr_iid=mr_iid,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        items = result["items"]
        logger.debug(
            "get_mr_pipelines completed in %.2fms, returned %d pipelines",
            elapsed_ms,
            len(items),
        )

        return ListPipelinesOutput(
            items=[PipelineSummary(**item) for item in items],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr_pipelines failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_mr_pipelines",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_mr_pipelines failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_mr_pipelines",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


# ---------------------------------------------------------------------------
# Write Tools (gated at runtime by read-only mode check)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
    )
)
async def create_mr(
    project_id: int | str | None = None,
    title: str | None = None,
    source_branch: str | None = None,
    target_branch: str | None = None,
    description: str | None = None,
    assignee_ids: list[int] | None = None,
    reviewer_ids: list[int] | None = None,
    labels: list[str] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> MergeRequestDetail | dict[str, Any]:
    """Create a new merge request in a GitLab project.

    Creates an MR from source_branch to target_branch with the given title.
    Optionally set description, assignees, reviewers, and labels. Returns
    the full details of the created merge request.

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        title: Merge request title (required).
        source_branch: Source branch name (required).
        target_branch: Target branch name (required).
        description: MR description in Markdown format.
        assignee_ids: List of user IDs to assign.
        reviewer_ids: List of user IDs to request review from.
        labels: List of label names to apply.
    """
    start_time = time.perf_counter()
    logger.debug(
        "create_mr called with project_id=%s, title=%s, source_branch=%s, target_branch=%s",
        project_id,
        title,
        source_branch,
        target_branch,
    )

    if ctx is None:
        logger.error("create_mr: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "create_mr",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Read-only mode gate
    read_only_error = check_read_only(app_ctx.settings.gitlab.read_only, "create_mr")
    if read_only_error is not None:
        return read_only_error

    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    try:
        result = await service.create_mr(
            project_id=project_id,
            title=title,
            source_branch=source_branch,
            target_branch=target_branch,
            description=description,
            assignee_ids=assignee_ids,
            reviewer_ids=reviewer_ids,
            labels=labels,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("create_mr completed in %.2fms", elapsed_ms)

        return MergeRequestDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("create_mr failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "create_mr",
            {
                "project_id": project_id,
                "title": title,
                "source_branch": source_branch,
                "target_branch": target_branch,
            },
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("create_mr failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "create_mr",
            {
                "project_id": project_id,
                "title": title,
                "source_branch": source_branch,
                "target_branch": target_branch,
            },
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
    )
)
async def update_mr(
    project_id: int | str | None = None,
    mr_iid: int | None = None,
    title: str | None = None,
    description: str | None = None,
    assignee_ids: list[int] | None = None,
    reviewer_ids: list[int] | None = None,
    labels: list[str] | None = None,
    state_event: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> MergeRequestDetail | dict[str, Any]:
    """Update an existing merge request.

    Modifies one or more fields of an existing MR. Only provided fields
    are updated; omitted fields remain unchanged. Can also change state
    via state_event (close or reopen).

    Args:
        project_id: Project ID or URL-encoded path. Uses configured default if omitted.
        mr_iid: Merge request IID (project-level identifier).
        title: New title for the MR.
        description: New description in Markdown format.
        assignee_ids: New list of assignee user IDs.
        reviewer_ids: New list of reviewer user IDs.
        labels: New list of label names.
        state_event: State transition: 'close' or 'reopen'.
    """
    start_time = time.perf_counter()
    logger.debug(
        "update_mr called with project_id=%s, mr_iid=%s",
        project_id,
        mr_iid,
    )

    if ctx is None:
        logger.error("update_mr: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "update_mr",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Read-only mode gate
    read_only_error = check_read_only(app_ctx.settings.gitlab.read_only, "update_mr")
    if read_only_error is not None:
        return read_only_error

    service = MergeRequestService(app_ctx.client, app_ctx.settings)

    try:
        result = await service.update_mr(
            project_id=project_id,
            mr_iid=mr_iid,
            title=title,
            description=description,
            assignee_ids=assignee_ids,
            reviewer_ids=reviewer_ids,
            labels=labels,
            state_event=state_event,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("update_mr completed in %.2fms", elapsed_ms)

        return MergeRequestDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("update_mr failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            exc.error_code,
            str(exc),
            "update_mr",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms, status_code=exc.status_code),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("update_mr failed after %.2fms: %s", elapsed_ms, str(exc))
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "update_mr",
            {"project_id": project_id, "mr_iid": mr_iid},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )
