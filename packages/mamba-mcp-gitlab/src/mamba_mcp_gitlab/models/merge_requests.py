"""Pydantic models for merge request tools.

Based on spec Section 5.1.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mamba_mcp_gitlab.models.common import Author, PaginatedOutput

# === Merge Request Summary (list responses) ===


class MergeRequestSummary(BaseModel):
    """Summary of a merge request, used in list responses."""

    id: int = Field(description="Global merge request ID")
    iid: int = Field(description="Project-level merge request IID")
    title: str = Field(description="Merge request title")
    state: str = Field(description="MR state: opened, closed, merged, or locked")
    author: Author | None = Field(default=None, description="User who created the MR")
    source_branch: str = Field(description="Source branch name")
    target_branch: str = Field(description="Target branch name")
    created_at: str = Field(description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(description="Last update timestamp (ISO 8601)")
    web_url: str = Field(description="URL to the merge request in GitLab UI")


# === Merge Request Detail (single MR response) ===


class DiffRefs(BaseModel):
    """Diff reference SHAs for a merge request."""

    base_sha: str | None = Field(default=None, description="Base commit SHA")
    head_sha: str | None = Field(default=None, description="Head commit SHA")
    start_sha: str | None = Field(default=None, description="Start commit SHA")


class PipelineRef(BaseModel):
    """Brief pipeline reference attached to a merge request."""

    id: int = Field(description="Pipeline ID")
    status: str = Field(description="Pipeline status (e.g., success, failed, running)")
    ref: str = Field(description="Git ref (branch or tag) for the pipeline")
    sha: str = Field(description="Commit SHA that triggered the pipeline")
    web_url: str = Field(description="URL to the pipeline in GitLab UI")


class MergeRequestDetail(MergeRequestSummary):
    """Full merge request details, extends MergeRequestSummary."""

    description: str | None = Field(default=None, description="MR description (Markdown)")
    assignees: list[Author] = Field(default_factory=list, description="Users assigned to the MR")
    reviewers: list[Author] = Field(
        default_factory=list, description="Users requested to review the MR"
    )
    labels: list[str] = Field(default_factory=list, description="Labels applied to the MR")
    merge_status: str | None = Field(
        default=None,
        description="Merge status: can_be_merged, cannot_be_merged, unchecked, etc.",
    )
    diff_refs: DiffRefs | None = Field(
        default=None, description="Diff reference SHAs (base, head, start)"
    )
    pipeline: PipelineRef | None = Field(
        default=None, description="Most recent pipeline for this MR"
    )


# === Merge Request Diff ===


class MergeRequestDiff(BaseModel):
    """A single file diff entry in a merge request."""

    old_path: str = Field(description="File path before the change")
    new_path: str = Field(description="File path after the change")
    diff: str = Field(description="Unified diff content")
    new_file: bool = Field(description="Whether this is a newly created file")
    renamed_file: bool = Field(description="Whether the file was renamed")
    deleted_file: bool = Field(description="Whether the file was deleted")


# === Merge Request Commit ===


class MergeRequestCommit(BaseModel):
    """A single commit in a merge request."""

    id: str = Field(description="Full commit SHA")
    short_id: str = Field(description="Short commit SHA")
    title: str = Field(description="Commit title (first line of message)")
    author_name: str = Field(description="Name of the commit author")
    authored_date: str = Field(description="Authoring timestamp (ISO 8601)")
    message: str = Field(description="Full commit message")


# === Paginated Output Models ===


class ListMergeRequestsOutput(PaginatedOutput):
    """Paginated list of merge request summaries."""

    items: list[MergeRequestSummary] = Field(description="List of merge request summaries")


class MergeRequestDiffsOutput(PaginatedOutput):
    """Paginated list of merge request diffs."""

    items: list[MergeRequestDiff] = Field(description="List of file diffs in the merge request")


class MergeRequestCommitsOutput(PaginatedOutput):
    """Paginated list of merge request commits."""

    items: list[MergeRequestCommit] = Field(description="List of commits in the merge request")
