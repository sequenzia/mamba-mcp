"""Pydantic models for issue tools.

Based on spec Section 5.2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mamba_mcp_gitlab.models.common import Author, PaginatedOutput

# === Issue Summary (list responses) ===


class Milestone(BaseModel):
    """A GitLab milestone reference."""

    id: int = Field(description="Milestone ID")
    iid: int = Field(description="Project-level milestone IID")
    title: str = Field(description="Milestone title")
    state: str = Field(description="Milestone state: active or closed")
    due_date: str | None = Field(default=None, description="Due date (ISO 8601 date)")
    web_url: str | None = Field(default=None, description="URL to the milestone in GitLab UI")


class IssueSummary(BaseModel):
    """Summary of an issue, used in list responses."""

    id: int = Field(description="Global issue ID")
    iid: int = Field(description="Project-level issue IID")
    title: str = Field(description="Issue title")
    state: str = Field(description="Issue state: opened or closed")
    author: Author | None = Field(default=None, description="User who created the issue")
    assignees: list[Author] = Field(default_factory=list, description="Users assigned to the issue")
    labels: list[str] = Field(default_factory=list, description="Labels applied to the issue")
    created_at: str = Field(description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(description="Last update timestamp (ISO 8601)")
    web_url: str = Field(description="URL to the issue in GitLab UI")


# === Issue Detail (single issue response) ===


class IssueDetail(IssueSummary):
    """Full issue details, extends IssueSummary."""

    description: str | None = Field(default=None, description="Issue description (Markdown)")
    milestone: Milestone | None = Field(default=None, description="Milestone the issue belongs to")
    user_notes_count: int = Field(
        default=0, description="Number of user comments (non-system notes)"
    )
    upvotes: int = Field(default=0, description="Number of upvotes")
    downvotes: int = Field(default=0, description="Number of downvotes")


# === Issue Comment ===


class IssueComment(BaseModel):
    """A single comment (note) on an issue."""

    id: int = Field(description="Note ID")
    body: str = Field(description="Comment body (Markdown)")
    author: Author | None = Field(default=None, description="User who wrote the comment")
    created_at: str = Field(description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(description="Last update timestamp (ISO 8601)")
    system: bool = Field(default=False, description="Whether this is a system-generated note")


# === Paginated Output Models ===


class ListIssuesOutput(PaginatedOutput):
    """Paginated list of issue summaries."""

    items: list[IssueSummary] = Field(description="List of issue summaries")


class IssueCommentsOutput(PaginatedOutput):
    """Paginated list of issue comments."""

    items: list[IssueComment] = Field(description="List of comments on the issue")
