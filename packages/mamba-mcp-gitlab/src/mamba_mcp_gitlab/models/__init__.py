"""Pydantic models for MCP tool inputs and outputs."""

from mamba_mcp_gitlab.models.common import (
    Author,
    PaginatedOutput,
)
from mamba_mcp_gitlab.models.issues import (
    IssueComment,
    IssueCommentsOutput,
    IssueDetail,
    IssueSummary,
    ListIssuesOutput,
    Milestone,
)
from mamba_mcp_gitlab.models.merge_requests import (
    DiffRefs,
    ListMergeRequestsOutput,
    MergeRequestCommit,
    MergeRequestCommitsOutput,
    MergeRequestDetail,
    MergeRequestDiff,
    MergeRequestDiffsOutput,
    MergeRequestSummary,
    PipelineRef,
)
from mamba_mcp_gitlab.models.pipelines import (
    JobLogOutput,
    ListPipelinesOutput,
    PipelineDetail,
    PipelineJob,
    PipelineJobsOutput,
    PipelineSummary,
)
from mamba_mcp_gitlab.models.search import (
    SearchOutput,
    SearchResult,
)

__all__ = [
    # Common models
    "Author",
    "PaginatedOutput",
    # Merge request models
    "MergeRequestSummary",
    "MergeRequestDetail",
    "MergeRequestDiff",
    "MergeRequestCommit",
    "DiffRefs",
    "PipelineRef",
    "ListMergeRequestsOutput",
    "MergeRequestDiffsOutput",
    "MergeRequestCommitsOutput",
    # Issue models
    "IssueSummary",
    "IssueDetail",
    "IssueComment",
    "Milestone",
    "ListIssuesOutput",
    "IssueCommentsOutput",
    # Pipeline models
    "PipelineSummary",
    "PipelineDetail",
    "PipelineJob",
    "JobLogOutput",
    "ListPipelinesOutput",
    "PipelineJobsOutput",
    # Search models
    "SearchResult",
    "SearchOutput",
]
