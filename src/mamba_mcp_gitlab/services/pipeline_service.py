"""Service for GitLab pipeline API operations.

Wraps GitLab REST API v4 pipeline endpoints: list pipelines, get pipeline
details, get pipeline jobs, and retrieve job logs (plain text).

Based on Spec Section 5.3.
"""

from __future__ import annotations

from typing import Any

import httpx

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError, GitLabService, _map_status_to_error_code

DEFAULT_MAX_LOG_BYTES = 102400  # 100KB


class PipelineService(GitLabService):
    """Service for GitLab pipeline API operations.

    Provides methods to list pipelines, get pipeline details, get pipeline
    jobs, and retrieve job logs. Inherits HTTP client and error handling
    from GitLabService.
    """

    async def list_pipelines(
        self,
        project_id: int | str,
        status: str | None = None,
        ref: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List pipelines for a project with optional filters.

        Args:
            project_id: Project ID or URL-encoded path.
            status: Filter by pipeline status (e.g., "running", "success", "failed").
            ref: Filter by git ref (branch or tag name).
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with items, page, per_page, total, total_pages keys.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        path = self._build_project_url(project_id, "pipelines")
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if ref is not None:
            params["ref"] = ref

        items, total, total_pages = await self._get_paginated(
            path, params=params, page=page, per_page=per_page
        )

        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

    async def get_pipeline(
        self,
        project_id: int | str,
        pipeline_id: int,
    ) -> dict[str, Any]:
        """Get full details of a single pipeline.

        Args:
            project_id: Project ID or URL-encoded path.
            pipeline_id: Pipeline ID.

        Returns:
            Dict with pipeline detail fields.

        Raises:
            GitLabAPIError: With PIPELINE_NOT_FOUND on 404, or other error codes.
        """
        path = self._build_project_url(project_id, f"pipelines/{pipeline_id}")
        try:
            result = await self._get(path)
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Pipeline {pipeline_id} not found",
                    error_code=ErrorCode.PIPELINE_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise
        return result  # type: ignore[no-any-return]

    async def get_pipeline_jobs(
        self,
        project_id: int | str,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Get jobs for a specific pipeline.

        Args:
            project_id: Project ID or URL-encoded path.
            pipeline_id: Pipeline ID.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with items, page, per_page, total, total_pages keys.

        Raises:
            GitLabAPIError: With PIPELINE_NOT_FOUND on 404, or other error codes.
        """
        path = self._build_project_url(project_id, f"pipelines/{pipeline_id}/jobs")
        try:
            items, total, total_pages = await self._get_paginated(
                path, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Pipeline {pipeline_id} not found",
                    error_code=ErrorCode.PIPELINE_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise

        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

    async def get_job_log(
        self,
        project_id: int | str,
        job_id: int,
        max_bytes: int = DEFAULT_MAX_LOG_BYTES,
    ) -> dict[str, Any]:
        """Get the log output of a specific job.

        The GitLab job trace endpoint returns plain text, not JSON.
        If the log exceeds max_bytes, it is truncated with a notice.

        Args:
            project_id: Project ID or URL-encoded path.
            job_id: Job ID.
            max_bytes: Maximum bytes to return (default 100KB). Log is
                truncated with a notice if it exceeds this limit.

        Returns:
            Dict with content, truncated, and byte_count keys.

        Raises:
            GitLabAPIError: With NOT_FOUND on 404, or other error codes.
        """
        path = self._build_project_url(project_id, f"jobs/{job_id}/trace")
        content = await self._get_text(path)

        byte_count = len(content.encode("utf-8"))
        truncated = byte_count > max_bytes

        if truncated:
            # Truncate at byte boundary, then decode safely
            truncated_bytes = content.encode("utf-8")[:max_bytes]
            content = truncated_bytes.decode("utf-8", errors="ignore")
            content += f"\n\n--- Log truncated (showing first {max_bytes}/{byte_count} bytes) ---"

        return {
            "content": content,
            "truncated": truncated,
            "byte_count": byte_count,
        }

    async def _get_text(self, path: str) -> str:
        """Send a GET request and return the response as plain text.

        Used for endpoints that return non-JSON responses (e.g., job trace).

        Args:
            path: API path relative to /api/v4.

        Returns:
            Response body as a string.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        url = self.base_url + path

        try:
            response = await self.http_client.get(url)
        except httpx.TimeoutException as exc:
            raise GitLabAPIError(
                message=f"Connection timeout: {exc}",
                error_code=ErrorCode.CONNECTION_ERROR,
            ) from exc
        except httpx.HTTPError as exc:
            raise GitLabAPIError(
                message=f"Connection error: {exc}",
                error_code=ErrorCode.CONNECTION_ERROR,
            ) from exc

        if response.status_code >= 400:
            error_code = _map_status_to_error_code(response.status_code)
            raise GitLabAPIError(
                message=f"HTTP {response.status_code}",
                error_code=error_code,
                status_code=response.status_code,
            )

        return response.text
