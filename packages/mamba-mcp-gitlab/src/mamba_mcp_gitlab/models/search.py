"""Pydantic models for search tools.

Based on spec Section 5.4.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mamba_mcp_gitlab.models.common import PaginatedOutput

# === Search Result ===


class SearchResult(BaseModel):
    """A single search result item.

    The `type` field acts as a discriminator indicating the resource kind
    (issues, merge_requests, projects, etc.). The `data` field holds the
    resource-specific payload from the GitLab API.
    """

    type: str = Field(description="Result type: issues, merge_requests, projects, milestones, etc.")
    data: dict[str, Any] = Field(description="Resource-specific result data from the GitLab API")


# === Search Output ===


class SearchOutput(PaginatedOutput):
    """Paginated search results."""

    items: list[SearchResult] = Field(description="List of search result items")
    query: str = Field(description="The search query that was executed")
    scope: str = Field(description="Search scope used: issues, merge_requests, projects, etc.")
