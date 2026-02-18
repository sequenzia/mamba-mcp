"""Tests for pipeline tool handlers (tools/pipeline_tools.py).

Covers all 4 pipeline tools: list_pipelines, get_pipeline, get_pipeline_jobs,
get_job_log. Tests the 7-step handler skeleton including context null-check,
service delegation, model conversion, and error handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.models.pipelines import (
    JobLogOutput,
    ListPipelinesOutput,
    PipelineDetail,
    PipelineJobsOutput,
)
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.tools.pipeline_tools import (
    _DEFAULT_MAX_BYTES,
    _MAX_MAX_BYTES,
    _MIN_MAX_BYTES,
    VALID_PIPELINE_STATUSES,
    get_job_log,
    get_pipeline,
    get_pipeline_jobs,
    list_pipelines,
)

# === Sample data ===

PIPELINE_SUMMARY = {
    "id": 100,
    "iid": 1,
    "status": "success",
    "ref": "main",
    "sha": "abc123def456",
    "created_at": "2026-01-15T10:00:00Z",
    "updated_at": "2026-01-15T10:05:00Z",
    "web_url": "https://gitlab.example.com/project/-/pipelines/100",
}

PIPELINE_DETAIL = {
    **PIPELINE_SUMMARY,
    "duration": 300,
    "started_at": "2026-01-15T10:00:30Z",
    "finished_at": "2026-01-15T10:05:00Z",
    "coverage": 85.5,
    "user": {
        "id": 1,
        "username": "admin",
        "name": "Admin",
        "avatar_url": None,
    },
}

PIPELINE_JOB = {
    "id": 500,
    "name": "test",
    "stage": "test",
    "status": "success",
    "duration": 45.2,
    "runner": "shared-runner-01",
    "web_url": "https://gitlab.example.com/project/-/jobs/500",
}


def _make_mock_ctx() -> MagicMock:
    """Create a mock MCP Context with AppContext containing client and settings."""
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context.client = MagicMock()
    mock_ctx.request_context.lifespan_context.settings = MagicMock()
    return mock_ctx


# === Tests for list_pipelines ===


class TestListPipelines:
    """Tests for the list_pipelines tool handler."""

    async def test_returns_paginated_output(self) -> None:
        """Test that list_pipelines returns a ListPipelinesOutput model."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [PIPELINE_SUMMARY],
            "page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(return_value=service_result)
            result = await list_pipelines(project_id=42, ctx=mock_ctx)

        assert isinstance(result, ListPipelinesOutput)
        assert len(result.items) == 1
        assert result.items[0].id == 100
        assert result.items[0].status == "success"
        assert result.page == 1
        assert result.per_page == 20
        assert result.total == 1

    async def test_passes_status_filter(self) -> None:
        """Test that status filter is forwarded to service."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.list_pipelines = mock_method
            await list_pipelines(project_id=42, status="failed", ctx=mock_ctx)

        mock_method.assert_called_once_with(
            project_id=42,
            status="failed",
            ref=None,
            page=1,
            per_page=20,
        )

    async def test_passes_ref_filter(self) -> None:
        """Test that ref filter is forwarded to service."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.list_pipelines = mock_method
            await list_pipelines(project_id=42, ref="feature-branch", ctx=mock_ctx)

        mock_method.assert_called_once_with(
            project_id=42,
            status=None,
            ref="feature-branch",
            page=1,
            per_page=20,
        )

    async def test_clamps_pagination(self) -> None:
        """Test that pagination parameters are clamped to valid range."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 100,
            "total": 0,
            "total_pages": 0,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.list_pipelines = mock_method
            await list_pipelines(project_id=42, page=-1, per_page=999, ctx=mock_ctx)

        # page=-1 should clamp to 1, per_page=999 should clamp to 100
        mock_method.assert_called_once_with(
            project_id=42,
            status=None,
            ref=None,
            page=1,
            per_page=100,
        )

    async def test_ctx_none_returns_connection_error(self) -> None:
        """Test that None context returns CONNECTION_ERROR."""
        result = await list_pipelines(project_id=42, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert result["tool_name"] == "list_pipelines"

    async def test_service_error_returns_structured_error(self) -> None:
        """Test that GitLabAPIError is converted to structured error response."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Project not found",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await list_pipelines(project_id=42, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PROJECT_NOT_FOUND
        assert result["tool_name"] == "list_pipelines"

    async def test_generic_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions return CONNECTION_ERROR."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(
                side_effect=RuntimeError("Unexpected error")
            )
            result = await list_pipelines(project_id=42, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_multiple_items(self) -> None:
        """Test list with multiple pipeline items."""
        mock_ctx = _make_mock_ctx()
        second_pipeline = {**PIPELINE_SUMMARY, "id": 101, "status": "failed"}
        service_result = {
            "items": [PIPELINE_SUMMARY, second_pipeline],
            "page": 1,
            "per_page": 20,
            "total": 2,
            "total_pages": 1,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(return_value=service_result)
            result = await list_pipelines(project_id=42, ctx=mock_ctx)

        assert isinstance(result, ListPipelinesOutput)
        assert len(result.items) == 2
        assert result.items[0].id == 100
        assert result.items[1].id == 101


# === Tests for get_pipeline ===


class TestGetPipeline:
    """Tests for the get_pipeline tool handler."""

    async def test_returns_pipeline_detail(self) -> None:
        """Test that get_pipeline returns a PipelineDetail model."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline = AsyncMock(return_value=PIPELINE_DETAIL)
            result = await get_pipeline(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, PipelineDetail)
        assert result.id == 100
        assert result.status == "success"
        assert result.duration == 300
        assert result.coverage == 85.5
        assert result.user is not None
        assert result.user.username == "admin"

    async def test_calls_service_with_correct_args(self) -> None:
        """Test that service method is called with correct arguments."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=PIPELINE_DETAIL)
            mock_svc.return_value.get_pipeline = mock_method
            await get_pipeline(project_id=42, pipeline_id=100, ctx=mock_ctx)

        mock_method.assert_called_once_with(project_id=42, pipeline_id=100)

    async def test_ctx_none_returns_connection_error(self) -> None:
        """Test that None context returns CONNECTION_ERROR."""
        result = await get_pipeline(project_id=42, pipeline_id=100, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert result["tool_name"] == "get_pipeline"

    async def test_not_found_returns_pipeline_not_found(self) -> None:
        """Test that 404 from service returns PIPELINE_NOT_FOUND error."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Pipeline 999 not found",
                    error_code=ErrorCode.PIPELINE_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_pipeline(project_id=42, pipeline_id=999, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PIPELINE_NOT_FOUND
        assert result["tool_name"] == "get_pipeline"

    async def test_generic_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions return CONNECTION_ERROR."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline = AsyncMock(
                side_effect=RuntimeError("Unexpected error")
            )
            result = await get_pipeline(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_pipeline_without_optional_fields(self) -> None:
        """Test pipeline detail with None optional fields."""
        mock_ctx = _make_mock_ctx()
        minimal_detail = {
            **PIPELINE_SUMMARY,
            "duration": None,
            "started_at": None,
            "finished_at": None,
            "coverage": None,
            "user": None,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline = AsyncMock(return_value=minimal_detail)
            result = await get_pipeline(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, PipelineDetail)
        assert result.duration is None
        assert result.coverage is None
        assert result.user is None


# === Tests for get_pipeline_jobs ===


class TestGetPipelineJobs:
    """Tests for the get_pipeline_jobs tool handler."""

    async def test_returns_paginated_jobs(self) -> None:
        """Test that get_pipeline_jobs returns PipelineJobsOutput model."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [PIPELINE_JOB],
            "page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline_jobs = AsyncMock(return_value=service_result)
            result = await get_pipeline_jobs(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, PipelineJobsOutput)
        assert len(result.items) == 1
        assert result.items[0].id == 500
        assert result.items[0].name == "test"
        assert result.items[0].stage == "test"
        assert result.items[0].status == "success"

    async def test_calls_service_with_correct_args(self) -> None:
        """Test that service method is called with correct arguments."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [],
            "page": 2,
            "per_page": 10,
            "total": 0,
            "total_pages": 0,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_pipeline_jobs = mock_method
            await get_pipeline_jobs(
                project_id=42, pipeline_id=100, page=2, per_page=10, ctx=mock_ctx
            )

        mock_method.assert_called_once_with(project_id=42, pipeline_id=100, page=2, per_page=10)

    async def test_clamps_pagination(self) -> None:
        """Test that pagination parameters are clamped to valid range."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "items": [],
            "page": 1,
            "per_page": 100,
            "total": 0,
            "total_pages": 0,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_pipeline_jobs = mock_method
            await get_pipeline_jobs(
                project_id=42, pipeline_id=100, page=0, per_page=200, ctx=mock_ctx
            )

        mock_method.assert_called_once_with(project_id=42, pipeline_id=100, page=1, per_page=100)

    async def test_ctx_none_returns_connection_error(self) -> None:
        """Test that None context returns CONNECTION_ERROR."""
        result = await get_pipeline_jobs(project_id=42, pipeline_id=100, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert result["tool_name"] == "get_pipeline_jobs"

    async def test_pipeline_not_found(self) -> None:
        """Test that 404 error returns PIPELINE_NOT_FOUND."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline_jobs = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Pipeline 999 not found",
                    error_code=ErrorCode.PIPELINE_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_pipeline_jobs(project_id=42, pipeline_id=999, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.PIPELINE_NOT_FOUND

    async def test_generic_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions return CONNECTION_ERROR."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline_jobs = AsyncMock(
                side_effect=RuntimeError("Unexpected error")
            )
            result = await get_pipeline_jobs(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR

    async def test_multiple_jobs_in_different_stages(self) -> None:
        """Test multiple jobs across different pipeline stages."""
        mock_ctx = _make_mock_ctx()
        build_job = {
            **PIPELINE_JOB,
            "id": 501,
            "name": "build",
            "stage": "build",
        }
        deploy_job = {
            **PIPELINE_JOB,
            "id": 502,
            "name": "deploy",
            "stage": "deploy",
            "status": "pending",
        }
        service_result = {
            "items": [PIPELINE_JOB, build_job, deploy_job],
            "page": 1,
            "per_page": 20,
            "total": 3,
            "total_pages": 1,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline_jobs = AsyncMock(return_value=service_result)
            result = await get_pipeline_jobs(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, PipelineJobsOutput)
        assert len(result.items) == 3
        assert result.items[0].stage == "test"
        assert result.items[1].stage == "build"
        assert result.items[2].stage == "deploy"


# === Tests for get_job_log ===


class TestGetJobLog:
    """Tests for the get_job_log tool handler."""

    async def test_returns_job_log_output(self) -> None:
        """Test that get_job_log returns a JobLogOutput model."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "content": "Running tests...\nAll 42 tests passed",
            "truncated": False,
            "byte_count": 40,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(return_value=service_result)
            result = await get_job_log(project_id=42, job_id=500, ctx=mock_ctx)

        assert isinstance(result, JobLogOutput)
        assert result.content == "Running tests...\nAll 42 tests passed"
        assert result.truncated is False
        assert result.byte_count == 40

    async def test_default_max_bytes(self) -> None:
        """Test that default max_bytes is 102400 (100KB)."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "content": "log content",
            "truncated": False,
            "byte_count": 11,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_job_log = mock_method
            await get_job_log(project_id=42, job_id=500, ctx=mock_ctx)

        mock_method.assert_called_once_with(
            project_id=42,
            job_id=500,
            max_bytes=_DEFAULT_MAX_BYTES,
        )

    async def test_custom_max_bytes(self) -> None:
        """Test that custom max_bytes is forwarded to service."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "content": "log",
            "truncated": False,
            "byte_count": 3,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_job_log = mock_method
            await get_job_log(project_id=42, job_id=500, max_bytes=50000, ctx=mock_ctx)

        mock_method.assert_called_once_with(
            project_id=42,
            job_id=500,
            max_bytes=50000,
        )

    async def test_max_bytes_clamped_to_minimum(self) -> None:
        """Test that max_bytes below minimum is clamped to 1024."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "content": "log",
            "truncated": False,
            "byte_count": 3,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_job_log = mock_method
            await get_job_log(project_id=42, job_id=500, max_bytes=100, ctx=mock_ctx)

        mock_method.assert_called_once_with(
            project_id=42,
            job_id=500,
            max_bytes=_MIN_MAX_BYTES,
        )

    async def test_max_bytes_clamped_to_maximum(self) -> None:
        """Test that max_bytes above maximum is clamped to 1MB."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "content": "log",
            "truncated": False,
            "byte_count": 3,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_method = AsyncMock(return_value=service_result)
            mock_svc.return_value.get_job_log = mock_method
            await get_job_log(project_id=42, job_id=500, max_bytes=10_000_000, ctx=mock_ctx)

        mock_method.assert_called_once_with(
            project_id=42,
            job_id=500,
            max_bytes=_MAX_MAX_BYTES,
        )

    async def test_truncated_log(self) -> None:
        """Test handling of truncated log output."""
        mock_ctx = _make_mock_ctx()
        service_result = {
            "content": "truncated content...\n--- Log truncated ---",
            "truncated": True,
            "byte_count": 200000,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(return_value=service_result)
            result = await get_job_log(project_id=42, job_id=500, ctx=mock_ctx)

        assert isinstance(result, JobLogOutput)
        assert result.truncated is True
        assert result.byte_count == 200000

    async def test_ctx_none_returns_connection_error(self) -> None:
        """Test that None context returns CONNECTION_ERROR."""
        result = await get_job_log(project_id=42, job_id=500, ctx=None)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR
        assert result["tool_name"] == "get_job_log"

    async def test_not_found_returns_error(self) -> None:
        """Test that 404 from service returns structured error."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Job 999 not found",
                    error_code=ErrorCode.NOT_FOUND,
                    status_code=404,
                )
            )
            result = await get_job_log(project_id=42, job_id=999, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.NOT_FOUND
        assert result["tool_name"] == "get_job_log"

    async def test_generic_exception_returns_connection_error(self) -> None:
        """Test that unexpected exceptions return CONNECTION_ERROR."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(
                side_effect=RuntimeError("Unexpected error")
            )
            result = await get_job_log(project_id=42, job_id=500, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.CONNECTION_ERROR


# === Tests for error context ===


class TestErrorContext:
    """Tests for error context in structured error responses."""

    async def test_service_error_includes_status_code_context(self) -> None:
        """Test that service errors include status_code in context."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_pipeline = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Forbidden",
                    error_code=ErrorCode.FORBIDDEN,
                    status_code=403,
                )
            )
            result = await get_pipeline(project_id=42, pipeline_id=100, ctx=mock_ctx)

        assert isinstance(result, dict)
        assert result["code"] == ErrorCode.FORBIDDEN
        context = result.get("context", {})
        assert context.get("status_code") == 403

    async def test_service_error_includes_input_received(self) -> None:
        """Test that errors include input_received field."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.list_pipelines = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Not found",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
                    status_code=404,
                )
            )
            result = await list_pipelines(project_id=42, status="running", ref="main", ctx=mock_ctx)

        assert isinstance(result, dict)
        input_received = result.get("input_received", {})
        assert input_received.get("project_id") == 42
        assert input_received.get("status") == "running"
        assert input_received.get("ref") == "main"

    async def test_error_includes_elapsed_ms(self) -> None:
        """Test that errors include elapsed_ms in context."""
        mock_ctx = _make_mock_ctx()
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(
                side_effect=GitLabAPIError(
                    message="Server error",
                    error_code=ErrorCode.API_ERROR,
                    status_code=500,
                )
            )
            result = await get_job_log(project_id=42, job_id=500, ctx=mock_ctx)

        assert isinstance(result, dict)
        context = result.get("context", {})
        assert "elapsed_ms" in context
        assert isinstance(context["elapsed_ms"], float)


# === Tests for module-level constants ===


class TestModuleConstants:
    """Tests for exported constants and configuration values."""

    def test_valid_pipeline_statuses(self) -> None:
        """Test that all expected pipeline statuses are defined."""
        expected = {"running", "pending", "success", "failed", "canceled", "skipped"}
        assert VALID_PIPELINE_STATUSES == expected

    def test_default_max_bytes_is_100kb(self) -> None:
        """Test that default max_bytes is 102400 (100KB)."""
        assert _DEFAULT_MAX_BYTES == 102400

    def test_min_max_bytes_is_1kb(self) -> None:
        """Test that minimum max_bytes is 1024 (1KB)."""
        assert _MIN_MAX_BYTES == 1024

    def test_max_max_bytes_is_1mb(self) -> None:
        """Test that maximum max_bytes is 1048576 (1MB)."""
        assert _MAX_MAX_BYTES == 1_048_576


# === Tests for service construction ===


class TestServiceConstruction:
    """Tests verifying PipelineService is constructed correctly."""

    async def test_service_receives_client_and_settings(self) -> None:
        """Test that PipelineService is instantiated with app_ctx client and settings."""
        mock_ctx = _make_mock_ctx()
        app_ctx = mock_ctx.request_context.lifespan_context
        service_result = {
            "content": "log",
            "truncated": False,
            "byte_count": 3,
        }
        with patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService") as mock_svc:
            mock_svc.return_value.get_job_log = AsyncMock(return_value=service_result)
            await get_job_log(project_id=42, job_id=500, ctx=mock_ctx)

        mock_svc.assert_called_once_with(
            http_client=app_ctx.client,
            settings=app_ctx.settings,
        )
