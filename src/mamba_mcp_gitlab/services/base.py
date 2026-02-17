"""Base service class for GitLab API interactions.

Provides shared HTTP communication, error mapping, pagination, and URL
construction that all resource-specific services inherit from.

Based on Spec Section 7.1 and 7.5.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.rate_limit import RateLimiter, RateLimitError


class GitLabAPIError(Exception):
    """Exception for GitLab API errors carrying error_code and status_code.

    Raised by base service methods when the GitLab API returns an error
    response or the request fails due to connection issues.
    """

    def __init__(
        self,
        message: str,
        error_code: str,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.response_body = response_body


# HTTP status code to ErrorCode mapping
_STATUS_CODE_MAP: dict[int, str] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.AUTH_FAILED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    429: ErrorCode.RATE_LIMITED,
}


def _map_status_to_error_code(status_code: int) -> str:
    """Map an HTTP status code to an ErrorCode constant.

    Args:
        status_code: HTTP response status code.

    Returns:
        The corresponding ErrorCode string.
    """
    if status_code in _STATUS_CODE_MAP:
        return _STATUS_CODE_MAP[status_code]
    if status_code >= 500:
        return ErrorCode.API_ERROR
    return ErrorCode.API_ERROR


def _parse_json_body(response: httpx.Response) -> Any:
    """Safely parse response body as JSON.

    Returns an empty dict if the body is empty or not valid JSON.
    """
    if not response.content:
        return {}
    try:
        return response.json()
    except (ValueError, TypeError):
        return {}


class GitLabService:
    """Base class for all GitLab API service classes.

    Provides shared HTTP methods (_get, _post, _put), pagination support,
    URL construction helpers, and error mapping. Resource-specific services
    (MergeRequestService, IssueService, etc.) inherit from this class.

    Args:
        http_client: Shared httpx.AsyncClient with connection pooling.
        settings: Server configuration including GitLab URL and project defaults.
        rate_limiter: Optional rate limiter for client-side request throttling.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.base_url = settings.gitlab.url.rstrip("/") + "/api/v4"

    async def _check_rate_limit(self) -> None:
        """Check and acquire a rate limit slot before making an HTTP request.

        If no rate limiter is configured, this is a no-op.

        Raises:
            GitLabAPIError: With RATE_LIMITED error code when limit is exceeded.
        """
        if self.rate_limiter is None:
            return
        try:
            await self.rate_limiter.acquire()
        except RateLimitError as exc:
            raise GitLabAPIError(
                message=str(exc),
                error_code=ErrorCode.RATE_LIMITED,
            ) from exc

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a GET request to the GitLab API.

        Args:
            path: API path relative to /api/v4 (e.g., "/projects/1/merge_requests").
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        result: dict[str, Any] = await self._request("GET", path, params=params)
        return result

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a POST request to the GitLab API.

        Args:
            path: API path relative to /api/v4.
            json: Optional JSON request body.

        Returns:
            Parsed JSON response body.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        result: dict[str, Any] = await self._request("POST", path, json=json)
        return result

    async def _put(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a PUT request to the GitLab API.

        Args:
            path: API path relative to /api/v4.
            json: Optional JSON request body.

        Returns:
            Parsed JSON response body.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        result: dict[str, Any] = await self._request("PUT", path, json=json)
        return result

    async def _get_paginated(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Send a paginated GET request to the GitLab API.

        Adds page and per_page to query params and extracts pagination
        metadata from GitLab response headers (x-total, x-total-pages).

        Args:
            path: API path relative to /api/v4.
            params: Optional additional query parameters.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Tuple of (items, total, total_pages) where items is the list
            of result dicts, total is the total item count, and total_pages
            is the total number of pages. Missing headers default to 0.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        merged_params = dict(params) if params else {}
        merged_params["page"] = page
        merged_params["per_page"] = per_page

        await self._check_rate_limit()

        url = self.base_url + path
        try:
            response = await self.http_client.get(url, params=merged_params)
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
            body = _parse_json_body(response)
            error_code = _map_status_to_error_code(response.status_code)
            message = body.get("message", body.get("error", f"HTTP {response.status_code}"))
            raise GitLabAPIError(
                message=str(message),
                error_code=error_code,
                status_code=response.status_code,
                response_body=body if isinstance(body, dict) else None,
            )

        items = _parse_json_body(response)
        if not isinstance(items, list):
            items = []

        total = _safe_int(response.headers.get("x-total"))
        total_pages = _safe_int(response.headers.get("x-total-pages"))

        return items, total, total_pages

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send an HTTP request to the GitLab API.

        Builds the full URL, executes the request, handles error responses,
        and returns the parsed JSON body.

        Args:
            method: HTTP method (GET, POST, PUT).
            path: API path relative to /api/v4.
            params: Optional query parameters.
            json: Optional JSON request body.

        Returns:
            Parsed JSON response body.

        Raises:
            GitLabAPIError: On HTTP error or connection failure.
        """
        url = self.base_url + path

        await self._check_rate_limit()

        try:
            response = await self.http_client.request(method, url, params=params, json=json)
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
            body = _parse_json_body(response)
            error_code = _map_status_to_error_code(response.status_code)
            message = body.get("message", body.get("error", f"HTTP {response.status_code}"))
            raise GitLabAPIError(
                message=str(message),
                error_code=error_code,
                status_code=response.status_code,
                response_body=body if isinstance(body, dict) else None,
            )

        return _parse_json_body(response)

    def _build_project_url(self, project_id: int | str, resource: str) -> str:
        """Build a GitLab API path for a project resource.

        Handles both integer project IDs and URL-encoded string paths
        (e.g., "group/subgroup/project" -> "group%2Fsubgroup%2Fproject").

        Args:
            project_id: Integer project ID or string project path.
            resource: Resource path (e.g., "merge_requests", "issues/1").

        Returns:
            API path string like "/projects/123/merge_requests".
        """
        if isinstance(project_id, int):
            encoded_id: str | int = project_id
        else:
            encoded_id = quote(str(project_id), safe="")
        return f"/projects/{encoded_id}/{resource}"

    def _resolve_project_id(self, project_id: int | str | None = None) -> int | str:
        """Resolve project ID, falling back to the configured default.

        Args:
            project_id: Explicit project ID, or None to use default.

        Returns:
            The resolved project ID.

        Raises:
            GitLabAPIError: If no project ID is provided and no default is configured.
        """
        if project_id is not None:
            return project_id
        if self.settings.gitlab.default_project_id is not None:
            return self.settings.gitlab.default_project_id
        raise GitLabAPIError(
            message="No project_id provided and no default_project_id configured",
            error_code=ErrorCode.VALIDATION_ERROR,
        )


def _safe_int(value: str | None) -> int:
    """Convert a string to int, returning 0 if missing or invalid."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0
