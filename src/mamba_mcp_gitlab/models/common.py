"""Shared Pydantic models used across multiple resource categories.

Provides reusable models for pagination and common entities like Author.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Author(BaseModel):
    """A GitLab user reference, reused across MRs, Issues, and Pipelines."""

    id: int = Field(description="GitLab user ID")
    username: str = Field(description="GitLab username")
    name: str = Field(description="Display name")
    avatar_url: str | None = Field(default=None, description="URL to user avatar image")


class PaginatedOutput(BaseModel):
    """Base model for paginated list responses.

    All list endpoints return pagination metadata alongside their items.
    Subclasses must define an `items` field with the appropriate list type.
    """

    page: int = Field(description="Current page number (1-based)")
    per_page: int = Field(description="Number of items per page")
    total: int = Field(description="Total number of items across all pages")
    total_pages: int = Field(description="Total number of pages")
