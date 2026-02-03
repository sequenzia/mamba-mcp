"""Service for GitLab merge request API operations.

Wraps GitLab REST API v4 merge request endpoints. All methods use the
inherited HTTP helpers from GitLabService and resolve project IDs via
the configured default when not explicitly provided.

Based on Spec Section 5.1 and Section 4.2 (User Journey).
"""

from __future__ import annotations

from typing import Any

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError, GitLabService


class MergeRequestService(GitLabService):
    """Service for merge request CRUD and query operations.

    Provides methods for listing, viewing, creating, and updating merge
    requests, as well as retrieving diffs and commits for a given MR.
    """

    async def list_mrs(
        self,
        project_id: int | str | None = None,
        state: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List merge requests for a project.

        GET /projects/{id}/merge_requests

        Args:
            project_id: Project ID or path (uses default if None).
            state: Filter by state: opened, closed, merged, all.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with 'items', 'page', 'per_page', 'total', 'total_pages'.

        Raises:
            GitLabAPIError: On API error or missing project ID.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, "merge_requests")

        params: dict[str, Any] = {}
        if state is not None:
            params["state"] = state

        try:
            items, total, total_pages = await self._get_paginated(
                path, params=params, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Project not found: {resolved_id}",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
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

    async def get_mr(
        self,
        project_id: int | str | None = None,
        mr_iid: int | None = None,
    ) -> dict[str, Any]:
        """Get a single merge request by IID.

        GET /projects/{id}/merge_requests/{mr_iid}

        Args:
            project_id: Project ID or path (uses default if None).
            mr_iid: Merge request IID (project-level).

        Returns:
            Dict with full merge request details.

        Raises:
            GitLabAPIError: On API error, missing project ID, or MR not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"merge_requests/{mr_iid}")

        try:
            return await self._get(path)
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Merge request !{mr_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise

    async def get_mr_diffs(
        self,
        project_id: int | str | None = None,
        mr_iid: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Get diffs for a merge request.

        GET /projects/{id}/merge_requests/{mr_iid}/diffs

        Args:
            project_id: Project ID or path (uses default if None).
            mr_iid: Merge request IID (project-level).
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with 'items', 'page', 'per_page', 'total', 'total_pages'.

        Raises:
            GitLabAPIError: On API error or MR not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"merge_requests/{mr_iid}/diffs")

        try:
            items, total, total_pages = await self._get_paginated(
                path, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Merge request !{mr_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
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

    async def get_mr_commits(
        self,
        project_id: int | str | None = None,
        mr_iid: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Get commits for a merge request.

        GET /projects/{id}/merge_requests/{mr_iid}/commits

        Args:
            project_id: Project ID or path (uses default if None).
            mr_iid: Merge request IID (project-level).
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with 'items', 'page', 'per_page', 'total', 'total_pages'.

        Raises:
            GitLabAPIError: On API error or MR not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"merge_requests/{mr_iid}/commits")

        try:
            items, total, total_pages = await self._get_paginated(
                path, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Merge request !{mr_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
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

    async def create_mr(
        self,
        project_id: int | str | None = None,
        title: str | None = None,
        source_branch: str | None = None,
        target_branch: str | None = None,
        description: str | None = None,
        assignee_ids: list[int] | None = None,
        reviewer_ids: list[int] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new merge request.

        POST /projects/{id}/merge_requests

        Args:
            project_id: Project ID or path (uses default if None).
            title: MR title (required).
            source_branch: Source branch name (required).
            target_branch: Target branch name (required).
            description: MR description (Markdown).
            assignee_ids: List of user IDs to assign.
            reviewer_ids: List of user IDs to request review from.
            labels: List of label names (sent as comma-separated string).

        Returns:
            Dict with created merge request details.

        Raises:
            GitLabAPIError: On API error, missing project, or branch not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, "merge_requests")

        body: dict[str, Any] = {
            "title": title,
            "source_branch": source_branch,
            "target_branch": target_branch,
        }

        if description is not None:
            body["description"] = description
        if assignee_ids is not None:
            body["assignee_ids"] = assignee_ids
        if reviewer_ids is not None:
            body["reviewer_ids"] = reviewer_ids
        if labels is not None:
            body["labels"] = ",".join(labels)

        try:
            return await self._post(path, json=body)
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                # Determine if it's a project or branch not found
                response_msg = str(exc).lower()
                if "branch" in response_msg or "source" in response_msg:
                    raise GitLabAPIError(
                        message=(
                            f"Branch not found for merge request creation in project {resolved_id}"
                        ),
                        error_code=ErrorCode.BRANCH_NOT_FOUND,
                        status_code=404,
                        response_body=exc.response_body,
                    ) from exc
                raise GitLabAPIError(
                    message=f"Project not found: {resolved_id}",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise

    async def update_mr(
        self,
        project_id: int | str | None = None,
        mr_iid: int | None = None,
        title: str | None = None,
        description: str | None = None,
        assignee_ids: list[int] | None = None,
        reviewer_ids: list[int] | None = None,
        labels: list[str] | None = None,
        state_event: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing merge request.

        PUT /projects/{id}/merge_requests/{mr_iid}

        Only sends fields that are explicitly provided (not None).

        Args:
            project_id: Project ID or path (uses default if None).
            mr_iid: Merge request IID (project-level).
            title: New title.
            description: New description.
            assignee_ids: New list of assignee user IDs.
            reviewer_ids: New list of reviewer user IDs.
            labels: New list of label names (sent as comma-separated string).
            state_event: State transition: close or reopen.

        Returns:
            Dict with updated merge request details.

        Raises:
            GitLabAPIError: On API error or MR not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"merge_requests/{mr_iid}")

        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if assignee_ids is not None:
            body["assignee_ids"] = assignee_ids
        if reviewer_ids is not None:
            body["reviewer_ids"] = reviewer_ids
        if labels is not None:
            body["labels"] = ",".join(labels)
        if state_event is not None:
            body["state_event"] = state_event

        try:
            return await self._put(path, json=body)
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Merge request !{mr_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise

    async def get_mr_pipelines(
        self,
        project_id: int | str | None = None,
        mr_iid: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Get pipelines associated with a merge request.

        GET /projects/{id}/merge_requests/{mr_iid}/pipelines

        This cross-resource query enables checking pipeline status from
        MR context, supporting the user journey: "Is the pipeline passing?"

        Args:
            project_id: Project ID or path (uses default if None).
            mr_iid: Merge request IID (project-level).
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with 'items', 'page', 'per_page', 'total', 'total_pages'.

        Raises:
            GitLabAPIError: On API error or MR not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"merge_requests/{mr_iid}/pipelines")

        try:
            items, total, total_pages = await self._get_paginated(
                path, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Merge request !{mr_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
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
