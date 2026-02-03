"""Pydantic models for pipeline tools.

Based on spec Section 5.3.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mamba_mcp_gitlab.models.common import Author, PaginatedOutput

# === Pipeline Summary (list responses) ===


class PipelineSummary(BaseModel):
    """Summary of a pipeline, used in list responses."""

    id: int = Field(description="Pipeline ID")
    iid: int = Field(description="Project-level pipeline IID")
    status: str = Field(
        description="Pipeline status: created, waiting_for_resource, preparing, pending, "
        "running, success, failed, canceled, skipped, manual, scheduled"
    )
    ref: str = Field(description="Git ref (branch or tag) for the pipeline")
    sha: str = Field(description="Commit SHA that triggered the pipeline")
    created_at: str = Field(description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(description="Last update timestamp (ISO 8601)")
    web_url: str = Field(description="URL to the pipeline in GitLab UI")


# === Pipeline Detail (single pipeline response) ===


class PipelineDetail(PipelineSummary):
    """Full pipeline details, extends PipelineSummary."""

    duration: int | None = Field(default=None, description="Pipeline duration in seconds")
    started_at: str | None = Field(default=None, description="Pipeline start timestamp (ISO 8601)")
    finished_at: str | None = Field(
        default=None, description="Pipeline finish timestamp (ISO 8601)"
    )
    coverage: float | None = Field(default=None, description="Code coverage percentage")
    user: Author | None = Field(default=None, description="User who triggered the pipeline")


# === Pipeline Job ===


class PipelineJob(BaseModel):
    """A single job within a pipeline."""

    id: int = Field(description="Job ID")
    name: str = Field(description="Job name")
    stage: str = Field(description="Pipeline stage this job belongs to")
    status: str = Field(
        description="Job status: created, pending, running, failed, success, "
        "canceled, skipped, manual"
    )
    duration: float | None = Field(default=None, description="Job duration in seconds")
    runner: str | None = Field(
        default=None, description="Runner name or description that executed the job"
    )
    web_url: str = Field(description="URL to the job in GitLab UI")


# === Job Log Output ===


class JobLogOutput(BaseModel):
    """Log output from a pipeline job."""

    content: str = Field(description="Job log text content")
    truncated: bool = Field(description="Whether the log was truncated due to size limits")
    byte_count: int = Field(description="Total log size in bytes before truncation")


# === Paginated Output Models ===


class ListPipelinesOutput(PaginatedOutput):
    """Paginated list of pipeline summaries."""

    items: list[PipelineSummary] = Field(description="List of pipeline summaries")


class PipelineJobsOutput(PaginatedOutput):
    """Paginated list of pipeline jobs."""

    items: list[PipelineJob] = Field(description="List of jobs in the pipeline")
