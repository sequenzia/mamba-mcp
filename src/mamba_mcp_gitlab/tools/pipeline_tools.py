"""MCP tool handlers for pipeline operations.

Provides 4 read-only tools for inspecting GitLab CI/CD pipelines:
list_pipelines, get_pipeline, get_pipeline_jobs, and get_job_log.

All pipeline tools are always registered (no read-only gating required).
Based on Spec Section 5.3.
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
    clamp_pagination,
    create_tool_error,
)
from mamba_mcp_gitlab.models.pipelines import (
    JobLogOutput,
    ListPipelinesOutput,
    PipelineDetail,
    PipelineJob,
    PipelineJobsOutput,
    PipelineSummary,
)
from mamba_mcp_gitlab.server import AppContext, mcp
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.pipeline_service import PipelineService

logger = logging.getLogger(__name__)

# Valid pipeline status filter values per GitLab API
VALID_PIPELINE_STATUSES = frozenset(
    {"running", "pending", "success", "failed", "canceled", "skipped"}
)

# Job log max_bytes bounds
_MIN_MAX_BYTES = 1024  # 1KB minimum
_MAX_MAX_BYTES = 1_048_576  # 1MB maximum
_DEFAULT_MAX_BYTES = 102400  # 100KB default


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def list_pipelines(
    project_id: int | str,
    status: str | None = None,
    ref: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> ListPipelinesOutput | dict[str, Any]:
    """List pipelines for a GitLab project.

    Returns a paginated list of CI/CD pipelines. Filter by status (e.g.,
    "running", "failed") or git ref (branch/tag) to narrow results.
    Use this to check recent pipeline activity or find failing builds.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path
            (e.g., "my-group/my-project").
        status: Filter by pipeline status. Valid values: running, pending,
            success, failed, canceled, skipped. Leave empty for all statuses.
        ref: Filter by git ref (branch or tag name).
        page: Page number for pagination (1-indexed). Default: 1.
        per_page: Number of pipelines per page (1-100). Default: 20.

    Returns:
        Paginated list of pipeline summaries with status, ref, SHA, and URLs.

    Example:
        list_pipelines(project_id=42, status="failed")
        -> {"items": [...], "page": 1, "per_page": 20, "total": 5, ...}
    """
    start_time = time.perf_counter()
    logger.debug(
        "list_pipelines called with project_id=%s, status=%s, ref=%s",
        project_id,
        status,
        ref,
    )

    # Step 2: ctx null-check
    if ctx is None:
        logger.error("list_pipelines: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "list_pipelines",
        )

    # Step 3: Extract app_ctx
    app_ctx = ctx.request_context.lifespan_context

    # Clamp pagination
    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    try:
        # Step 4: Create service
        service = PipelineService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        # Step 5: Delegate to service
        result = await service.list_pipelines(
            project_id=project_id,
            status=status,
            ref=ref,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        # Step 6: Convert to output model
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "list_pipelines completed in %.2fms, returned %d items",
            elapsed_ms,
            len(result["items"]),
        )
        return ListPipelinesOutput(
            items=[PipelineSummary(**p) for p in result["items"]],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        # Step 7: Catch service exceptions -> structured error
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_pipelines failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            exc.error_code,
            str(exc),
            "list_pipelines",
            input_received={"project_id": project_id, "status": status, "ref": ref},
            context=build_error_context(
                elapsed_ms=elapsed_ms,
                status_code=exc.status_code,
            ),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("list_pipelines failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "list_pipelines",
            input_received={"project_id": project_id},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_pipeline(
    project_id: int | str,
    pipeline_id: int,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> PipelineDetail | dict[str, Any]:
    """Get full details of a single pipeline.

    Returns comprehensive pipeline information including status, duration,
    coverage, timestamps, and the user who triggered it. Use this after
    list_pipelines to drill into a specific pipeline's details.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        pipeline_id: The pipeline ID to retrieve.

    Returns:
        Full pipeline details with status, duration, coverage, and user info.

    Example:
        get_pipeline(project_id=42, pipeline_id=1001)
        -> {"id": 1001, "status": "success", "duration": 342, ...}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_pipeline called with project_id=%s, pipeline_id=%d",
        project_id,
        pipeline_id,
    )

    if ctx is None:
        logger.error("get_pipeline: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_pipeline",
        )

    app_ctx = ctx.request_context.lifespan_context

    try:
        service = PipelineService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.get_pipeline(
            project_id=project_id,
            pipeline_id=pipeline_id,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_pipeline completed in %.2fms, pipeline_id=%d",
            elapsed_ms,
            pipeline_id,
        )
        return PipelineDetail(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_pipeline failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_pipeline",
            input_received={
                "project_id": project_id,
                "pipeline_id": pipeline_id,
            },
            context=build_error_context(
                elapsed_ms=elapsed_ms,
                status_code=exc.status_code,
            ),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_pipeline failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_pipeline",
            input_received={
                "project_id": project_id,
                "pipeline_id": pipeline_id,
            },
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_pipeline_jobs(
    project_id: int | str,
    pipeline_id: int,
    page: int | None = None,
    per_page: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> PipelineJobsOutput | dict[str, Any]:
    """Get jobs for a specific pipeline.

    Returns a paginated list of jobs within a pipeline, including each job's
    name, stage, status, duration, and runner info. Use this to understand
    which specific jobs passed or failed in a pipeline.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        pipeline_id: The pipeline ID whose jobs to retrieve.
        page: Page number for pagination (1-indexed). Default: 1.
        per_page: Number of jobs per page (1-100). Default: 20.

    Returns:
        Paginated list of pipeline jobs with stage, status, and duration.

    Example:
        get_pipeline_jobs(project_id=42, pipeline_id=1001)
        -> {"items": [{"name": "test", "stage": "test", "status": "success"}], ...}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_pipeline_jobs called with project_id=%s, pipeline_id=%d",
        project_id,
        pipeline_id,
    )

    if ctx is None:
        logger.error("get_pipeline_jobs: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_pipeline_jobs",
        )

    app_ctx = ctx.request_context.lifespan_context
    clamped_page, clamped_per_page = clamp_pagination(page, per_page)

    try:
        service = PipelineService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.get_pipeline_jobs(
            project_id=project_id,
            pipeline_id=pipeline_id,
            page=clamped_page,
            per_page=clamped_per_page,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_pipeline_jobs completed in %.2fms, returned %d jobs",
            elapsed_ms,
            len(result["items"]),
        )
        return PipelineJobsOutput(
            items=[PipelineJob(**j) for j in result["items"]],
            page=result["page"],
            per_page=result["per_page"],
            total=result["total"],
            total_pages=result["total_pages"],
        )

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_pipeline_jobs failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_pipeline_jobs",
            input_received={
                "project_id": project_id,
                "pipeline_id": pipeline_id,
            },
            context=build_error_context(
                elapsed_ms=elapsed_ms,
                status_code=exc.status_code,
            ),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_pipeline_jobs failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_pipeline_jobs",
            input_received={
                "project_id": project_id,
                "pipeline_id": pipeline_id,
            },
            context=build_error_context(elapsed_ms=elapsed_ms),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
    )
)
async def get_job_log(
    project_id: int | str,
    job_id: int,
    max_bytes: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> JobLogOutput | dict[str, Any]:
    """Get the log output of a specific CI/CD job.

    Returns the text log of a job's execution. Large logs are automatically
    truncated to the specified max_bytes limit (default 100KB). Use this
    to inspect test failures, build errors, or deployment output.

    Args:
        project_id: GitLab project ID (numeric) or URL-encoded path.
        job_id: The job ID whose log to retrieve.
        max_bytes: Maximum log size in bytes (1024-1048576). Default: 102400
            (100KB). Logs exceeding this limit are truncated with a notice.

    Returns:
        Job log content with truncation status and total byte count.

    Example:
        get_job_log(project_id=42, job_id=5001)
        -> {"content": "Running tests...\nAll 42 tests passed", "truncated": false, ...}
    """
    start_time = time.perf_counter()
    logger.debug(
        "get_job_log called with project_id=%s, job_id=%d, max_bytes=%s",
        project_id,
        job_id,
        max_bytes,
    )

    if ctx is None:
        logger.error("get_job_log: No context available")
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            "No context available",
            "get_job_log",
        )

    app_ctx = ctx.request_context.lifespan_context

    # Clamp max_bytes to reasonable range
    if max_bytes is None:
        clamped_max_bytes = _DEFAULT_MAX_BYTES
    else:
        clamped_max_bytes = max(_MIN_MAX_BYTES, min(max_bytes, _MAX_MAX_BYTES))

    try:
        service = PipelineService(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )

        result = await service.get_job_log(
            project_id=project_id,
            job_id=job_id,
            max_bytes=clamped_max_bytes,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "get_job_log completed in %.2fms, job_id=%d, truncated=%s, bytes=%d",
            elapsed_ms,
            job_id,
            result["truncated"],
            result["byte_count"],
        )
        return JobLogOutput(**result)

    except GitLabAPIError as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_job_log failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            exc.error_code,
            str(exc),
            "get_job_log",
            input_received={"project_id": project_id, "job_id": job_id},
            context=build_error_context(
                elapsed_ms=elapsed_ms,
                status_code=exc.status_code,
            ),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("get_job_log failed after %.2fms: %s", elapsed_ms, exc)
        return create_tool_error(
            ErrorCode.CONNECTION_ERROR,
            str(exc),
            "get_job_log",
            input_received={"project_id": project_id, "job_id": job_id},
            context=build_error_context(elapsed_ms=elapsed_ms),
        )
