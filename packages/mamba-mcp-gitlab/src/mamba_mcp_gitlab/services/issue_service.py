"""Service for GitLab issue API operations.

Wraps GitLab REST API v4 issue endpoints with typed methods.
Inherits shared HTTP, pagination, and error handling from GitLabService.

Based on Spec Section 5.2.
"""

from __future__ import annotations

from typing import Any

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError, GitLabService


class IssueService(GitLabService):
    """Service for GitLab issue API operations.

    Provides methods for listing, viewing, creating, updating issues
    and managing issue comments (notes). Inherits HTTP methods, pagination,
    URL construction, and error mapping from GitLabService.
    """

    async def list_issues(
        self,
        project_id: int | str | None = None,
        state: str | None = None,
        labels: str | None = None,
        assignee_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List issues for a project with optional filters.

        Args:
            project_id: Project ID or path. Falls back to configured default.
            state: Filter by state (opened, closed, all).
            labels: Comma-separated label names to filter by.
            assignee_id: Filter by assignee user ID.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with items, page, per_page, total, and total_pages.

        Raises:
            GitLabAPIError: On API error or missing project ID.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, "issues")

        params: dict[str, Any] = {}
        if state is not None:
            params["state"] = state
        if labels is not None:
            params["labels"] = labels
        if assignee_id is not None:
            params["assignee_id"] = assignee_id

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

    async def get_issue(
        self,
        project_id: int | str | None = None,
        issue_iid: int = 0,
    ) -> dict[str, Any]:
        """Get full details of a single issue.

        Args:
            project_id: Project ID or path. Falls back to configured default.
            issue_iid: Project-level issue IID.

        Returns:
            Dict with full issue details from GitLab API.

        Raises:
            GitLabAPIError: On API error, missing project ID, or issue not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"issues/{issue_iid}")

        try:
            return await self._get(path)
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Issue !{issue_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.ISSUE_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise

    async def list_issue_comments(
        self,
        project_id: int | str | None = None,
        issue_iid: int = 0,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List comments (notes) on an issue.

        Args:
            project_id: Project ID or path. Falls back to configured default.
            issue_iid: Project-level issue IID.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with items, page, per_page, total, and total_pages.

        Raises:
            GitLabAPIError: On API error, missing project ID, or issue not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"issues/{issue_iid}/notes")

        try:
            items, total, total_pages = await self._get_paginated(
                path, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Issue !{issue_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.ISSUE_NOT_FOUND,
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

    async def create_issue(
        self,
        project_id: int | str | None = None,
        title: str = "",
        description: str | None = None,
        assignee_ids: list[int] | None = None,
        labels: str | None = None,
        milestone_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a new issue in a project.

        Args:
            project_id: Project ID or path. Falls back to configured default.
            title: Issue title (required).
            description: Issue description in Markdown.
            assignee_ids: List of user IDs to assign.
            labels: Comma-separated label names.
            milestone_id: Milestone ID to associate.

        Returns:
            Dict with the created issue details from GitLab API.

        Raises:
            GitLabAPIError: On API error, missing project ID, or validation error.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, "issues")

        body: dict[str, Any] = {"title": title}
        if description is not None:
            body["description"] = description
        if assignee_ids is not None:
            body["assignee_ids"] = assignee_ids
        if labels is not None:
            body["labels"] = labels
        if milestone_id is not None:
            body["milestone_id"] = milestone_id

        try:
            return await self._post(path, json=body)
        except GitLabAPIError as exc:
            if exc.status_code == 400:
                raise GitLabAPIError(
                    message=str(exc),
                    error_code=ErrorCode.VALIDATION_ERROR,
                    status_code=400,
                    response_body=exc.response_body,
                ) from exc
            raise

    async def update_issue(
        self,
        project_id: int | str | None = None,
        issue_iid: int = 0,
        title: str | None = None,
        description: str | None = None,
        assignee_ids: list[int] | None = None,
        labels: str | None = None,
        state_event: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing issue.

        Args:
            project_id: Project ID or path. Falls back to configured default.
            issue_iid: Project-level issue IID.
            title: New issue title.
            description: New issue description in Markdown.
            assignee_ids: New list of assignee user IDs.
            labels: New comma-separated label names.
            state_event: State transition event (close, reopen).

        Returns:
            Dict with the updated issue details from GitLab API.

        Raises:
            GitLabAPIError: On API error, missing project ID, issue not found,
                or validation error.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"issues/{issue_iid}")

        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if assignee_ids is not None:
            body["assignee_ids"] = assignee_ids
        if labels is not None:
            body["labels"] = labels
        if state_event is not None:
            body["state_event"] = state_event

        try:
            return await self._put(path, json=body)
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Issue !{issue_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.ISSUE_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            if exc.status_code == 400:
                raise GitLabAPIError(
                    message=str(exc),
                    error_code=ErrorCode.VALIDATION_ERROR,
                    status_code=400,
                    response_body=exc.response_body,
                ) from exc
            raise

    async def add_issue_comment(
        self,
        project_id: int | str | None = None,
        issue_iid: int = 0,
        body: str = "",
    ) -> dict[str, Any]:
        """Add a comment (note) to an issue.

        Args:
            project_id: Project ID or path. Falls back to configured default.
            issue_iid: Project-level issue IID.
            body: Comment body in Markdown.

        Returns:
            Dict with the created comment details from GitLab API.

        Raises:
            GitLabAPIError: On API error, missing project ID, or issue not found.
        """
        resolved_id = self._resolve_project_id(project_id)
        path = self._build_project_url(resolved_id, f"issues/{issue_iid}/notes")

        try:
            return await self._post(path, json={"body": body})
        except GitLabAPIError as exc:
            if exc.status_code == 404:
                raise GitLabAPIError(
                    message=f"Issue !{issue_iid} not found in project {resolved_id}",
                    error_code=ErrorCode.ISSUE_NOT_FOUND,
                    status_code=404,
                    response_body=exc.response_body,
                ) from exc
            raise
