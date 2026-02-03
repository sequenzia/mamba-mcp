"""Tests for Pydantic I/O models across all resource categories."""

import pytest
from mamba_mcp_gitlab.models import (
    Author,
    DiffRefs,
    IssueComment,
    IssueCommentsOutput,
    IssueDetail,
    IssueSummary,
    JobLogOutput,
    ListIssuesOutput,
    ListMergeRequestsOutput,
    ListPipelinesOutput,
    MergeRequestCommit,
    MergeRequestCommitsOutput,
    MergeRequestDetail,
    MergeRequestDiff,
    MergeRequestDiffsOutput,
    MergeRequestSummary,
    Milestone,
    PaginatedOutput,
    PipelineDetail,
    PipelineJob,
    PipelineJobsOutput,
    PipelineRef,
    PipelineSummary,
    SearchOutput,
    SearchResult,
)
from pydantic import ValidationError

# === Test Data Factories ===


def make_author(**overrides: object) -> dict:
    """Create a valid Author data dict."""
    data = {
        "id": 1,
        "username": "jdoe",
        "name": "Jane Doe",
        "avatar_url": "https://gitlab.example.com/uploads/-/system/user/avatar/1/avatar.png",
    }
    data.update(overrides)
    return data


def make_mr_summary(**overrides: object) -> dict:
    """Create a valid MergeRequestSummary data dict."""
    data = {
        "id": 100,
        "iid": 1,
        "title": "Add feature X",
        "state": "opened",
        "author": make_author(),
        "source_branch": "feature-x",
        "target_branch": "main",
        "created_at": "2026-01-15T10:30:00Z",
        "updated_at": "2026-01-16T14:00:00Z",
        "web_url": "https://gitlab.example.com/project/-/merge_requests/1",
    }
    data.update(overrides)
    return data


def make_issue_summary(**overrides: object) -> dict:
    """Create a valid IssueSummary data dict."""
    data = {
        "id": 200,
        "iid": 10,
        "title": "Fix login bug",
        "state": "opened",
        "author": make_author(),
        "assignees": [],
        "labels": ["bug"],
        "created_at": "2026-01-10T08:00:00Z",
        "updated_at": "2026-01-12T16:00:00Z",
        "web_url": "https://gitlab.example.com/project/-/issues/10",
    }
    data.update(overrides)
    return data


def make_pipeline_summary(**overrides: object) -> dict:
    """Create a valid PipelineSummary data dict."""
    data = {
        "id": 300,
        "iid": 5,
        "status": "success",
        "ref": "main",
        "sha": "abc123def456",
        "created_at": "2026-01-20T12:00:00Z",
        "updated_at": "2026-01-20T12:10:00Z",
        "web_url": "https://gitlab.example.com/project/-/pipelines/300",
    }
    data.update(overrides)
    return data


def make_pagination(**overrides: object) -> dict:
    """Create valid pagination fields."""
    data = {
        "page": 1,
        "per_page": 20,
        "total": 50,
        "total_pages": 3,
    }
    data.update(overrides)
    return data


# === Common Models ===


class TestAuthor:
    """Tests for the Author model."""

    def test_valid_author(self) -> None:
        """Test Author instantiation with all fields."""
        author = Author(**make_author())
        assert author.id == 1
        assert author.username == "jdoe"
        assert author.name == "Jane Doe"
        assert author.avatar_url is not None

    def test_author_optional_avatar(self) -> None:
        """Test Author with None avatar_url."""
        author = Author(**make_author(avatar_url=None))
        assert author.avatar_url is None

    def test_author_rejects_invalid_id(self) -> None:
        """Test Author validation rejects non-integer ID."""
        with pytest.raises(ValidationError):
            Author(**make_author(id="not_an_int"))

    def test_author_rejects_missing_username(self) -> None:
        """Test Author validation rejects missing required field."""
        data = make_author()
        del data["username"]
        with pytest.raises(ValidationError):
            Author(**data)


class TestPaginatedOutput:
    """Tests for the PaginatedOutput base model."""

    def test_valid_pagination(self) -> None:
        """Test PaginatedOutput with valid data."""
        page = PaginatedOutput(**make_pagination())
        assert page.page == 1
        assert page.per_page == 20
        assert page.total == 50
        assert page.total_pages == 3

    def test_rejects_missing_page(self) -> None:
        """Test PaginatedOutput rejects missing page field."""
        data = make_pagination()
        del data["page"]
        with pytest.raises(ValidationError):
            PaginatedOutput(**data)

    def test_rejects_invalid_type(self) -> None:
        """Test PaginatedOutput rejects non-integer total."""
        with pytest.raises(ValidationError):
            PaginatedOutput(**make_pagination(total="many"))


# === Merge Request Models ===


class TestMergeRequestSummary:
    """Tests for the MergeRequestSummary model."""

    def test_valid_summary(self) -> None:
        """Test MergeRequestSummary instantiation with all fields."""
        mr = MergeRequestSummary(**make_mr_summary())
        assert mr.id == 100
        assert mr.iid == 1
        assert mr.title == "Add feature X"
        assert mr.state == "opened"
        assert mr.source_branch == "feature-x"
        assert mr.target_branch == "main"
        assert mr.created_at == "2026-01-15T10:30:00Z"
        assert mr.web_url.startswith("https://")

    def test_author_is_optional(self) -> None:
        """Test MergeRequestSummary with None author."""
        mr = MergeRequestSummary(**make_mr_summary(author=None))
        assert mr.author is None

    def test_date_accepts_iso8601(self) -> None:
        """Test date fields accept ISO 8601 format strings."""
        mr = MergeRequestSummary(
            **make_mr_summary(
                created_at="2026-01-15T10:30:00.000+02:00",
                updated_at="2026-01-16T14:00:00Z",
            )
        )
        assert mr.created_at == "2026-01-15T10:30:00.000+02:00"

    def test_rejects_missing_title(self) -> None:
        """Test MergeRequestSummary rejects missing required field."""
        data = make_mr_summary()
        del data["title"]
        with pytest.raises(ValidationError):
            MergeRequestSummary(**data)


class TestMergeRequestDetail:
    """Tests for the MergeRequestDetail model."""

    def test_valid_detail(self) -> None:
        """Test MergeRequestDetail with all fields."""
        detail = MergeRequestDetail(
            **make_mr_summary(),
            description="## Changes\n- Added feature X",
            assignees=[make_author()],
            reviewers=[make_author(id=2, username="reviewer")],
            labels=["feature", "reviewed"],
            merge_status="can_be_merged",
            diff_refs={
                "base_sha": "aaa111",
                "head_sha": "bbb222",
                "start_sha": "ccc333",
            },
            pipeline={
                "id": 50,
                "status": "success",
                "ref": "feature-x",
                "sha": "bbb222",
                "web_url": "https://gitlab.example.com/project/-/pipelines/50",
            },
        )
        assert detail.description is not None
        assert len(detail.assignees) == 1
        assert len(detail.reviewers) == 1
        assert detail.labels == ["feature", "reviewed"]
        assert detail.merge_status == "can_be_merged"
        assert detail.diff_refs is not None
        assert detail.diff_refs.head_sha == "bbb222"
        assert detail.pipeline is not None
        assert detail.pipeline.status == "success"

    def test_optional_fields_default_none(self) -> None:
        """Test MergeRequestDetail optional fields default to None or empty."""
        detail = MergeRequestDetail(**make_mr_summary())
        assert detail.description is None
        assert detail.assignees == []
        assert detail.reviewers == []
        assert detail.labels == []
        assert detail.merge_status is None
        assert detail.diff_refs is None
        assert detail.pipeline is None

    def test_inherits_summary_fields(self) -> None:
        """Test MergeRequestDetail inherits from MergeRequestSummary."""
        detail = MergeRequestDetail(**make_mr_summary())
        assert detail.source_branch == "feature-x"
        assert detail.target_branch == "main"


class TestDiffRefs:
    """Tests for the DiffRefs model."""

    def test_valid_diff_refs(self) -> None:
        """Test DiffRefs with all fields."""
        refs = DiffRefs(base_sha="aaa", head_sha="bbb", start_sha="ccc")
        assert refs.base_sha == "aaa"

    def test_all_optional(self) -> None:
        """Test DiffRefs with all None values."""
        refs = DiffRefs()
        assert refs.base_sha is None
        assert refs.head_sha is None
        assert refs.start_sha is None


class TestPipelineRef:
    """Tests for the PipelineRef model."""

    def test_valid_pipeline_ref(self) -> None:
        """Test PipelineRef instantiation."""
        ref = PipelineRef(
            id=50,
            status="success",
            ref="main",
            sha="abc123",
            web_url="https://gitlab.example.com/project/-/pipelines/50",
        )
        assert ref.id == 50
        assert ref.status == "success"


class TestMergeRequestDiff:
    """Tests for the MergeRequestDiff model."""

    def test_valid_diff(self) -> None:
        """Test MergeRequestDiff with valid data."""
        diff = MergeRequestDiff(
            old_path="src/old.py",
            new_path="src/new.py",
            diff="@@ -1,3 +1,4 @@\n+added line",
            new_file=False,
            renamed_file=True,
            deleted_file=False,
        )
        assert diff.old_path == "src/old.py"
        assert diff.renamed_file is True

    def test_new_file_diff(self) -> None:
        """Test MergeRequestDiff for a newly created file."""
        diff = MergeRequestDiff(
            old_path="/dev/null",
            new_path="src/feature.py",
            diff="@@ -0,0 +1,10 @@\n+new content",
            new_file=True,
            renamed_file=False,
            deleted_file=False,
        )
        assert diff.new_file is True

    def test_rejects_missing_diff(self) -> None:
        """Test MergeRequestDiff rejects missing diff field."""
        with pytest.raises(ValidationError):
            MergeRequestDiff(
                old_path="a.py",
                new_path="a.py",
                new_file=False,
                renamed_file=False,
                deleted_file=False,
                # missing 'diff' field
            )


class TestMergeRequestCommit:
    """Tests for the MergeRequestCommit model."""

    def test_valid_commit(self) -> None:
        """Test MergeRequestCommit instantiation."""
        commit = MergeRequestCommit(
            id="abc123def456789",
            short_id="abc123d",
            title="Add feature X",
            author_name="Jane Doe",
            authored_date="2026-01-15T10:30:00Z",
            message="Add feature X\n\nDetailed description here.",
        )
        assert commit.id == "abc123def456789"
        assert commit.short_id == "abc123d"
        assert commit.title == "Add feature X"
        assert commit.authored_date == "2026-01-15T10:30:00Z"


class TestListMergeRequestsOutput:
    """Tests for the ListMergeRequestsOutput model."""

    def test_valid_paginated_list(self) -> None:
        """Test ListMergeRequestsOutput with items and pagination."""
        output = ListMergeRequestsOutput(
            items=[make_mr_summary()],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.page == 1
        assert output.total == 1

    def test_empty_list(self) -> None:
        """Test ListMergeRequestsOutput with no items."""
        output = ListMergeRequestsOutput(
            items=[],
            **make_pagination(total=0, total_pages=0),
        )
        assert output.items == []
        assert output.total == 0


class TestMergeRequestDiffsOutput:
    """Tests for the MergeRequestDiffsOutput model."""

    def test_valid_diffs_output(self) -> None:
        """Test MergeRequestDiffsOutput with a diff item."""
        output = MergeRequestDiffsOutput(
            items=[
                {
                    "old_path": "a.py",
                    "new_path": "a.py",
                    "diff": "@@ -1 +1 @@\n-old\n+new",
                    "new_file": False,
                    "renamed_file": False,
                    "deleted_file": False,
                }
            ],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.items[0].old_path == "a.py"


class TestMergeRequestCommitsOutput:
    """Tests for the MergeRequestCommitsOutput model."""

    def test_valid_commits_output(self) -> None:
        """Test MergeRequestCommitsOutput with a commit item."""
        output = MergeRequestCommitsOutput(
            items=[
                {
                    "id": "abc123",
                    "short_id": "abc",
                    "title": "Fix bug",
                    "author_name": "Dev",
                    "authored_date": "2026-01-15T10:00:00Z",
                    "message": "Fix bug",
                }
            ],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.items[0].title == "Fix bug"


# === Issue Models ===


class TestMilestone:
    """Tests for the Milestone model."""

    def test_valid_milestone(self) -> None:
        """Test Milestone instantiation with all fields."""
        ms = Milestone(
            id=1,
            iid=1,
            title="v1.0",
            state="active",
            due_date="2026-03-01",
            web_url="https://gitlab.example.com/project/-/milestones/1",
        )
        assert ms.title == "v1.0"
        assert ms.state == "active"

    def test_optional_fields(self) -> None:
        """Test Milestone with optional fields as None."""
        ms = Milestone(id=1, iid=1, title="v2.0", state="closed")
        assert ms.due_date is None
        assert ms.web_url is None


class TestIssueSummary:
    """Tests for the IssueSummary model."""

    def test_valid_summary(self) -> None:
        """Test IssueSummary instantiation with all fields."""
        issue = IssueSummary(**make_issue_summary())
        assert issue.id == 200
        assert issue.iid == 10
        assert issue.title == "Fix login bug"
        assert issue.labels == ["bug"]

    def test_author_optional(self) -> None:
        """Test IssueSummary with None author."""
        issue = IssueSummary(**make_issue_summary(author=None))
        assert issue.author is None

    def test_empty_assignees_and_labels(self) -> None:
        """Test IssueSummary defaults to empty lists."""
        data = make_issue_summary()
        del data["assignees"]
        del data["labels"]
        issue = IssueSummary(**data)
        assert issue.assignees == []
        assert issue.labels == []


class TestIssueDetail:
    """Tests for the IssueDetail model."""

    def test_valid_detail(self) -> None:
        """Test IssueDetail with all fields."""
        detail = IssueDetail(
            **make_issue_summary(),
            description="Login fails when password contains special chars.",
            milestone={"id": 1, "iid": 1, "title": "v1.0", "state": "active"},
            user_notes_count=5,
            upvotes=3,
            downvotes=1,
        )
        assert detail.description is not None
        assert detail.milestone is not None
        assert detail.milestone.title == "v1.0"
        assert detail.user_notes_count == 5
        assert detail.upvotes == 3
        assert detail.downvotes == 1

    def test_optional_fields_default(self) -> None:
        """Test IssueDetail optional fields default to None/0."""
        detail = IssueDetail(**make_issue_summary())
        assert detail.description is None
        assert detail.milestone is None
        assert detail.user_notes_count == 0
        assert detail.upvotes == 0
        assert detail.downvotes == 0

    def test_inherits_summary_fields(self) -> None:
        """Test IssueDetail inherits from IssueSummary."""
        detail = IssueDetail(**make_issue_summary())
        assert detail.title == "Fix login bug"
        assert detail.state == "opened"


class TestIssueComment:
    """Tests for the IssueComment model."""

    def test_valid_comment(self) -> None:
        """Test IssueComment instantiation."""
        comment = IssueComment(
            id=500,
            body="This looks like a regression from v0.9.",
            author=make_author(),
            created_at="2026-01-11T09:00:00Z",
            updated_at="2026-01-11T09:00:00Z",
            system=False,
        )
        assert comment.id == 500
        assert comment.body.startswith("This looks")
        assert comment.system is False

    def test_system_note(self) -> None:
        """Test IssueComment for a system-generated note."""
        comment = IssueComment(
            id=501,
            body="assigned to @jdoe",
            created_at="2026-01-11T09:01:00Z",
            updated_at="2026-01-11T09:01:00Z",
            system=True,
        )
        assert comment.system is True
        assert comment.author is None

    def test_optional_author(self) -> None:
        """Test IssueComment with None author."""
        comment = IssueComment(
            id=502,
            body="Comment text",
            created_at="2026-01-11T10:00:00Z",
            updated_at="2026-01-11T10:00:00Z",
        )
        assert comment.author is None
        assert comment.system is False


class TestListIssuesOutput:
    """Tests for the ListIssuesOutput model."""

    def test_valid_paginated_list(self) -> None:
        """Test ListIssuesOutput with items and pagination."""
        output = ListIssuesOutput(
            items=[make_issue_summary()],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.page == 1


class TestIssueCommentsOutput:
    """Tests for the IssueCommentsOutput model."""

    def test_valid_comments_output(self) -> None:
        """Test IssueCommentsOutput with a comment item."""
        output = IssueCommentsOutput(
            items=[
                {
                    "id": 500,
                    "body": "Comment",
                    "created_at": "2026-01-11T09:00:00Z",
                    "updated_at": "2026-01-11T09:00:00Z",
                }
            ],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.items[0].body == "Comment"


# === Pipeline Models ===


class TestPipelineSummary:
    """Tests for the PipelineSummary model."""

    def test_valid_summary(self) -> None:
        """Test PipelineSummary instantiation."""
        pipeline = PipelineSummary(**make_pipeline_summary())
        assert pipeline.id == 300
        assert pipeline.status == "success"
        assert pipeline.ref == "main"
        assert pipeline.sha == "abc123def456"

    def test_date_accepts_iso8601(self) -> None:
        """Test pipeline date fields accept ISO 8601 strings."""
        pipeline = PipelineSummary(
            **make_pipeline_summary(created_at="2026-01-20T12:00:00.000+00:00")
        )
        assert pipeline.created_at == "2026-01-20T12:00:00.000+00:00"


class TestPipelineDetail:
    """Tests for the PipelineDetail model."""

    def test_valid_detail(self) -> None:
        """Test PipelineDetail with all fields."""
        detail = PipelineDetail(
            **make_pipeline_summary(),
            duration=120,
            started_at="2026-01-20T12:00:00Z",
            finished_at="2026-01-20T12:02:00Z",
            coverage=87.5,
            user=make_author(),
        )
        assert detail.duration == 120
        assert detail.started_at is not None
        assert detail.finished_at is not None
        assert detail.coverage == 87.5
        assert detail.user is not None

    def test_optional_fields_default_none(self) -> None:
        """Test PipelineDetail optional fields default to None."""
        detail = PipelineDetail(**make_pipeline_summary())
        assert detail.duration is None
        assert detail.started_at is None
        assert detail.finished_at is None
        assert detail.coverage is None
        assert detail.user is None

    def test_inherits_summary_fields(self) -> None:
        """Test PipelineDetail inherits from PipelineSummary."""
        detail = PipelineDetail(**make_pipeline_summary())
        assert detail.status == "success"
        assert detail.ref == "main"


class TestPipelineJob:
    """Tests for the PipelineJob model."""

    def test_valid_job(self) -> None:
        """Test PipelineJob instantiation."""
        job = PipelineJob(
            id=400,
            name="test",
            stage="test",
            status="success",
            duration=45.2,
            runner="shared-runner-01",
            web_url="https://gitlab.example.com/project/-/jobs/400",
        )
        assert job.id == 400
        assert job.name == "test"
        assert job.stage == "test"
        assert job.duration == 45.2
        assert job.runner == "shared-runner-01"

    def test_optional_fields(self) -> None:
        """Test PipelineJob with optional fields as None."""
        job = PipelineJob(
            id=401,
            name="build",
            stage="build",
            status="pending",
            web_url="https://gitlab.example.com/project/-/jobs/401",
        )
        assert job.duration is None
        assert job.runner is None


class TestJobLogOutput:
    """Tests for the JobLogOutput model."""

    def test_valid_log(self) -> None:
        """Test JobLogOutput instantiation."""
        log = JobLogOutput(
            content="Running tests...\nAll tests passed.",
            truncated=False,
            byte_count=42,
        )
        assert "tests passed" in log.content
        assert log.truncated is False
        assert log.byte_count == 42

    def test_truncated_log(self) -> None:
        """Test JobLogOutput with truncation."""
        log = JobLogOutput(
            content="Partial log output...",
            truncated=True,
            byte_count=102400,
        )
        assert log.truncated is True
        assert log.byte_count == 102400

    def test_rejects_missing_content(self) -> None:
        """Test JobLogOutput rejects missing content field."""
        with pytest.raises(ValidationError):
            JobLogOutput(truncated=False, byte_count=0)


class TestListPipelinesOutput:
    """Tests for the ListPipelinesOutput model."""

    def test_valid_paginated_list(self) -> None:
        """Test ListPipelinesOutput with items and pagination."""
        output = ListPipelinesOutput(
            items=[make_pipeline_summary()],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.items[0].status == "success"


class TestPipelineJobsOutput:
    """Tests for the PipelineJobsOutput model."""

    def test_valid_jobs_output(self) -> None:
        """Test PipelineJobsOutput with a job item."""
        output = PipelineJobsOutput(
            items=[
                {
                    "id": 400,
                    "name": "lint",
                    "stage": "test",
                    "status": "success",
                    "web_url": "https://gitlab.example.com/project/-/jobs/400",
                }
            ],
            **make_pagination(total=1, total_pages=1),
        )
        assert len(output.items) == 1
        assert output.items[0].name == "lint"


# === Search Models ===


class TestSearchResult:
    """Tests for the SearchResult model."""

    def test_valid_issue_result(self) -> None:
        """Test SearchResult with an issue type."""
        result = SearchResult(
            type="issues",
            data={"id": 200, "iid": 10, "title": "Bug report"},
        )
        assert result.type == "issues"
        assert result.data["title"] == "Bug report"

    def test_valid_mr_result(self) -> None:
        """Test SearchResult with a merge_requests type."""
        result = SearchResult(
            type="merge_requests",
            data={"id": 100, "iid": 1, "title": "Feature MR"},
        )
        assert result.type == "merge_requests"

    def test_valid_project_result(self) -> None:
        """Test SearchResult with a projects type."""
        result = SearchResult(
            type="projects",
            data={"id": 50, "name": "my-project"},
        )
        assert result.type == "projects"

    def test_rejects_missing_type(self) -> None:
        """Test SearchResult rejects missing type."""
        with pytest.raises(ValidationError):
            SearchResult(data={"id": 1})

    def test_rejects_missing_data(self) -> None:
        """Test SearchResult rejects missing data."""
        with pytest.raises(ValidationError):
            SearchResult(type="issues")


class TestSearchOutput:
    """Tests for the SearchOutput model."""

    def test_valid_search_output(self) -> None:
        """Test SearchOutput with results and pagination."""
        output = SearchOutput(
            items=[{"type": "issues", "data": {"id": 1, "title": "Test"}}],
            query="login bug",
            scope="issues",
            **make_pagination(total=1, total_pages=1),
        )
        assert output.query == "login bug"
        assert output.scope == "issues"
        assert len(output.items) == 1

    def test_empty_search_results(self) -> None:
        """Test SearchOutput with no results."""
        output = SearchOutput(
            items=[],
            query="nonexistent",
            scope="projects",
            **make_pagination(total=0, total_pages=0),
        )
        assert output.items == []
        assert output.total == 0


# === Cross-Cutting Concerns ===


class TestPaginationConsistency:
    """Tests verifying pagination fields are consistent across all list outputs."""

    @pytest.mark.parametrize(
        "model_cls,items_data",
        [
            (ListMergeRequestsOutput, [make_mr_summary()]),
            (ListIssuesOutput, [make_issue_summary()]),
            (ListPipelinesOutput, [make_pipeline_summary()]),
            (
                MergeRequestDiffsOutput,
                [
                    {
                        "old_path": "a.py",
                        "new_path": "a.py",
                        "diff": "diff",
                        "new_file": False,
                        "renamed_file": False,
                        "deleted_file": False,
                    }
                ],
            ),
            (
                MergeRequestCommitsOutput,
                [
                    {
                        "id": "abc",
                        "short_id": "ab",
                        "title": "t",
                        "author_name": "a",
                        "authored_date": "2026-01-01T00:00:00Z",
                        "message": "m",
                    }
                ],
            ),
            (
                IssueCommentsOutput,
                [
                    {
                        "id": 1,
                        "body": "b",
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ],
            ),
            (
                PipelineJobsOutput,
                [
                    {
                        "id": 1,
                        "name": "j",
                        "stage": "s",
                        "status": "success",
                        "web_url": "https://example.com/job/1",
                    }
                ],
            ),
            (
                SearchOutput,
                {
                    "items": [{"type": "issues", "data": {"id": 1}}],
                    "query": "test",
                    "scope": "issues",
                },
            ),
        ],
        ids=[
            "ListMergeRequestsOutput",
            "ListIssuesOutput",
            "ListPipelinesOutput",
            "MergeRequestDiffsOutput",
            "MergeRequestCommitsOutput",
            "IssueCommentsOutput",
            "PipelineJobsOutput",
            "SearchOutput",
        ],
    )
    def test_pagination_fields_present(self, model_cls: type, items_data: list | dict) -> None:
        """Test that all paginated outputs have consistent pagination fields."""
        pagination = make_pagination()
        if isinstance(items_data, dict):
            # SearchOutput needs extra fields
            data = {**items_data, **pagination}
        else:
            data = {"items": items_data, **pagination}
        output = model_cls(**data)
        assert hasattr(output, "page")
        assert hasattr(output, "per_page")
        assert hasattr(output, "total")
        assert hasattr(output, "total_pages")
        assert output.page == 1
        assert output.per_page == 20


class TestAuthorReuse:
    """Tests verifying the Author model is shared across resource categories."""

    def test_author_in_mr(self) -> None:
        """Test Author is used in MergeRequestSummary."""
        mr = MergeRequestSummary(**make_mr_summary())
        assert isinstance(mr.author, Author)

    def test_author_in_issue(self) -> None:
        """Test Author is used in IssueSummary."""
        issue = IssueSummary(**make_issue_summary())
        assert isinstance(issue.author, Author)

    def test_author_in_pipeline(self) -> None:
        """Test Author is used in PipelineDetail."""
        detail = PipelineDetail(**make_pipeline_summary(), user=make_author())
        assert isinstance(detail.user, Author)

    def test_author_in_issue_comment(self) -> None:
        """Test Author is used in IssueComment."""
        comment = IssueComment(
            id=1,
            body="text",
            author=make_author(),
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert isinstance(comment.author, Author)


class TestModelImports:
    """Tests verifying all models are importable from the models package."""

    def test_all_models_importable(self) -> None:
        """Test that all models listed in __all__ are importable."""
        from mamba_mcp_gitlab import models

        expected = [
            "Author",
            "PaginatedOutput",
            "MergeRequestSummary",
            "MergeRequestDetail",
            "MergeRequestDiff",
            "MergeRequestCommit",
            "DiffRefs",
            "PipelineRef",
            "ListMergeRequestsOutput",
            "MergeRequestDiffsOutput",
            "MergeRequestCommitsOutput",
            "IssueSummary",
            "IssueDetail",
            "IssueComment",
            "Milestone",
            "ListIssuesOutput",
            "IssueCommentsOutput",
            "PipelineSummary",
            "PipelineDetail",
            "PipelineJob",
            "JobLogOutput",
            "ListPipelinesOutput",
            "PipelineJobsOutput",
            "SearchResult",
            "SearchOutput",
        ]
        for name in expected:
            assert hasattr(models, name), f"{name} not importable from models"

    def test_all_exports_defined(self) -> None:
        """Test that __all__ is defined and matches expected models."""
        from mamba_mcp_gitlab.models import __all__

        assert len(__all__) >= 25
        assert "Author" in __all__
        assert "PaginatedOutput" in __all__
        assert "SearchOutput" in __all__
