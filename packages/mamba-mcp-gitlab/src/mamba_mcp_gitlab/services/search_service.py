"""Service for GitLab search API operations.

Wraps GitLab REST API v4 search endpoints with typed methods.
Inherits shared HTTP, pagination, and error handling from GitLabService.

Supports three search levels:
- Instance-wide: GET /search
- Project-scoped: GET /projects/{id}/search
- Group-scoped: GET /groups/{id}/search

Based on Spec Section 5.4.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError, GitLabService

# Valid search scope values accepted by the GitLab API
VALID_SCOPES = {"issues", "merge_requests", "projects"}


class SearchService(GitLabService):
    """Service for GitLab search API operations.

    Provides a single search method that routes to instance-wide, project-scoped,
    or group-scoped GitLab search endpoints depending on the provided parameters.
    Inherits HTTP methods, pagination, URL construction, and error mapping from
    GitLabService.
    """

    async def search(
        self,
        query: str,
        scope: str,
        project_id: int | str | None = None,
        group_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search across GitLab resources.

        Routes to the appropriate search endpoint based on scoping:
        - If project_id is provided (or default exists): project-scoped search
        - Else if group_id is provided (or default exists): group-scoped search
        - Else: instance-wide search

        Priority: explicit project_id > explicit group_id > default project_id
        > default group_id > instance-wide.

        Args:
            query: Search query string.
            scope: Search scope -- one of "issues", "merge_requests", "projects".
            project_id: Optional project ID or path for project-scoped search.
            group_id: Optional group ID for group-scoped search.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Dict with items, page, per_page, total, total_pages, query, scope.

        Raises:
            GitLabAPIError: On invalid scope, API error, or connection failure.
        """
        # Validate scope
        if scope not in VALID_SCOPES:
            raise GitLabAPIError(
                message=(
                    f"Invalid search scope '{scope}'. "
                    f"Available scopes: {', '.join(sorted(VALID_SCOPES))}"
                ),
                error_code=ErrorCode.VALIDATION_ERROR,
            )

        # Determine the search endpoint path
        path = self._resolve_search_path(project_id, group_id)

        params: dict[str, Any] = {
            "search": query,
            "scope": scope,
        }

        try:
            items, total, total_pages = await self._get_paginated(
                path, params=params, page=page, per_page=per_page
            )
        except GitLabAPIError as exc:
            if exc.status_code == 429:
                raise GitLabAPIError(
                    message="GitLab API rate limit reached. Wait before retrying.",
                    error_code=ErrorCode.RATE_LIMITED,
                    status_code=429,
                    response_body=exc.response_body,
                ) from exc
            raise

        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "query": query,
            "scope": scope,
        }

    def _resolve_search_path(
        self,
        project_id: int | str | None = None,
        group_id: int | None = None,
    ) -> str:
        """Resolve the search API path based on scoping.

        Priority: explicit project_id > explicit group_id > default project_id
        from settings > default group_id from settings > instance-wide.

        Args:
            project_id: Explicit project ID or path.
            group_id: Explicit group ID.

        Returns:
            API path for the appropriate search endpoint.
        """
        # Explicit project_id takes highest priority
        if project_id is not None:
            if isinstance(project_id, int):
                encoded_id: str | int = project_id
            else:
                encoded_id = quote(str(project_id), safe="")
            return f"/projects/{encoded_id}/search"

        # Explicit group_id takes second priority
        if group_id is not None:
            return f"/groups/{group_id}/search"

        # Fall back to default project_id from settings
        default_project_id = self.settings.gitlab.default_project_id
        if default_project_id is not None:
            return f"/projects/{default_project_id}/search"

        # Fall back to default group_id from settings
        default_group_id = self.settings.gitlab.default_group_id
        if default_group_id is not None:
            return f"/groups/{default_group_id}/search"

        # Instance-wide search
        return "/search"
