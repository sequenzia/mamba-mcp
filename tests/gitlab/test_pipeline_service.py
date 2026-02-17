"""Tests for the PipelineService (services/pipeline_service.py).

Covers all 4 methods: list_pipelines, get_pipeline, get_pipeline_jobs,
get_job_log. Includes unit tests for correct endpoint calls, filter support,
job log truncation, error handling, and edge cases.
"""

import httpx
import pytest
import respx
from mamba_mcp_gitlab.config import Settings
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.services.base import GitLabAPIError
from mamba_mcp_gitlab.services.pipeline_service import DEFAULT_MAX_LOG_BYTES, PipelineService

GITLAB_URL = "https://gitlab.example.com"
BASE_API = f"{GITLAB_URL}/api/v4"


def _make_settings(
    url: str = GITLAB_URL,
    default_project_id: int | None = None,
) -> Settings:
    """Create a Settings instance for testing."""
    return Settings(
        gitlab={  # type: ignore[arg-type]
            "url": url,
            "token": "glpat-test-token",
            "default_project_id": default_project_id,
        },
        oauth={},  # type: ignore[arg-type]
        server={},  # type: ignore[arg-type]
        rate_limit={},  # type: ignore[arg-type]
    )


def _make_service(
    client: httpx.AsyncClient | None = None,
    url: str = GITLAB_URL,
    default_project_id: int | None = None,
) -> PipelineService:
    """Create a PipelineService instance for testing."""
    settings = _make_settings(url=url, default_project_id=default_project_id)
    http_client = client or httpx.AsyncClient()
    return PipelineService(http_client=http_client, settings=settings)


# === Sample data ===

PIPELINE_SUMMARY = {
    "id": 100,
    "iid": 1,
    "status": "success",
    "ref": "main",
    "sha": "abc123",
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


class TestListPipelines:
    """Tests for the list_pipelines method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that list_pipelines calls GET /projects/{id}/pipelines."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[PIPELINE_SUMMARY],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_pipelines(project_id=42)

        assert route.called
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == 100

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that list_pipelines returns pagination metadata."""
        respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[PIPELINE_SUMMARY],
            headers={"x-total": "50", "x-total-pages": "3"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_pipelines(project_id=42, page=2, per_page=20)

        assert result["page"] == 2
        assert result["per_page"] == 20
        assert result["total"] == 50
        assert result["total_pages"] == 3

    @respx.mock
    async def test_status_filter(self) -> None:
        """Test that list_pipelines passes status filter as query param."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[PIPELINE_SUMMARY],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_pipelines(project_id=42, status="running")

        request = route.calls[0].request
        assert b"status=running" in request.url.raw_path

    @respx.mock
    async def test_ref_filter(self) -> None:
        """Test that list_pipelines passes ref filter as query param."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[PIPELINE_SUMMARY],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_pipelines(project_id=42, ref="develop")

        request = route.calls[0].request
        assert b"ref=develop" in request.url.raw_path

    @respx.mock
    async def test_both_filters(self) -> None:
        """Test that list_pipelines passes both status and ref filters."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_pipelines(project_id=42, status="failed", ref="main")

        request = route.calls[0].request
        assert b"status=failed" in request.url.raw_path
        assert b"ref=main" in request.url.raw_path

    @respx.mock
    async def test_no_filters(self) -> None:
        """Test that list_pipelines omits status/ref when not provided."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_pipelines(project_id=42)

        request = route.calls[0].request
        raw_path = request.url.raw_path.decode()
        assert "status=" not in raw_path
        assert "ref=" not in raw_path

    @respx.mock
    async def test_empty_pipeline_list(self) -> None:
        """Test that list_pipelines returns empty items for projects with no pipelines."""
        respx.get(f"{BASE_API}/projects/42/pipelines").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.list_pipelines(project_id=42)

        assert result["items"] == []
        assert result["total"] == 0

    @respx.mock
    async def test_string_project_id(self) -> None:
        """Test that list_pipelines URL-encodes string project IDs."""
        route = respx.get(url__regex=r".*/projects/group%2Fproject/pipelines.*").respond(
            200,
            json=[],
            headers={"x-total": "0", "x-total-pages": "0"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            await service.list_pipelines(project_id="group/project")

        assert route.called


class TestGetPipeline:
    """Tests for the get_pipeline method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_pipeline calls GET /projects/{id}/pipelines/{pipeline_id}."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines/100").respond(
            200, json=PIPELINE_DETAIL
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_pipeline(project_id=42, pipeline_id=100)

        assert route.called
        assert result["id"] == 100
        assert result["status"] == "success"
        assert result["duration"] == 300

    @respx.mock
    async def test_returns_full_detail(self) -> None:
        """Test that get_pipeline returns all detail fields from the response."""
        respx.get(f"{BASE_API}/projects/42/pipelines/100").respond(200, json=PIPELINE_DETAIL)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_pipeline(project_id=42, pipeline_id=100)

        assert result["started_at"] == "2026-01-15T10:00:30Z"
        assert result["finished_at"] == "2026-01-15T10:05:00Z"
        assert result["coverage"] == 85.5
        assert result["user"]["username"] == "admin"

    @respx.mock
    async def test_pipeline_not_found_raises_pipeline_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with PIPELINE_NOT_FOUND error code."""
        respx.get(f"{BASE_API}/projects/42/pipelines/999").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_pipeline(project_id=42, pipeline_id=999)

        assert exc_info.value.error_code == ErrorCode.PIPELINE_NOT_FOUND
        assert exc_info.value.status_code == 404
        assert "999" in str(exc_info.value)

    @respx.mock
    async def test_non_404_error_propagated(self) -> None:
        """Test that non-404 errors are propagated with original error code."""
        respx.get(f"{BASE_API}/projects/42/pipelines/100").respond(
            403, json={"message": "Forbidden"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_pipeline(project_id=42, pipeline_id=100)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert exc_info.value.status_code == 403

    @respx.mock
    async def test_running_pipeline(self) -> None:
        """Test that a running pipeline returns current status with in-progress details."""
        running_pipeline = {
            **PIPELINE_SUMMARY,
            "status": "running",
            "duration": None,
            "started_at": "2026-01-15T10:00:30Z",
            "finished_at": None,
            "coverage": None,
            "user": {"id": 1, "username": "admin", "name": "Admin", "avatar_url": None},
        }
        respx.get(f"{BASE_API}/projects/42/pipelines/100").respond(200, json=running_pipeline)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_pipeline(project_id=42, pipeline_id=100)

        assert result["status"] == "running"
        assert result["finished_at"] is None
        assert result["duration"] is None


class TestGetPipelineJobs:
    """Tests for the get_pipeline_jobs method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_pipeline_jobs calls GET /projects/{id}/pipelines/{pipeline_id}/jobs."""
        route = respx.get(f"{BASE_API}/projects/42/pipelines/100/jobs").respond(
            200,
            json=[PIPELINE_JOB],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_pipeline_jobs(project_id=42, pipeline_id=100)

        assert route.called
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == 500

    @respx.mock
    async def test_returns_pagination_metadata(self) -> None:
        """Test that get_pipeline_jobs returns pagination metadata."""
        respx.get(f"{BASE_API}/projects/42/pipelines/100/jobs").respond(
            200,
            json=[PIPELINE_JOB],
            headers={"x-total": "10", "x-total-pages": "2"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_pipeline_jobs(
                project_id=42, pipeline_id=100, page=1, per_page=5
            )

        assert result["page"] == 1
        assert result["per_page"] == 5
        assert result["total"] == 10
        assert result["total_pages"] == 2

    @respx.mock
    async def test_pipeline_not_found_raises_pipeline_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with PIPELINE_NOT_FOUND error code."""
        respx.get(f"{BASE_API}/projects/42/pipelines/999/jobs").respond(
            404, json={"message": "404 Not Found"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_pipeline_jobs(project_id=42, pipeline_id=999)

        assert exc_info.value.error_code == ErrorCode.PIPELINE_NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_non_404_error_propagated(self) -> None:
        """Test that non-404 errors are propagated with original error code."""
        respx.get(f"{BASE_API}/projects/42/pipelines/100/jobs").respond(
            500, json={"error": "Internal Server Error"}
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_pipeline_jobs(project_id=42, pipeline_id=100)

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_running_pipeline_with_in_progress_jobs(self) -> None:
        """Test that a running pipeline returns in-progress job details."""
        running_job = {
            **PIPELINE_JOB,
            "status": "running",
            "duration": None,
        }
        respx.get(f"{BASE_API}/projects/42/pipelines/100/jobs").respond(
            200,
            json=[running_job],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_pipeline_jobs(project_id=42, pipeline_id=100)

        assert result["items"][0]["status"] == "running"
        assert result["items"][0]["duration"] is None


class TestGetJobLog:
    """Tests for the get_job_log method."""

    @respx.mock
    async def test_calls_correct_endpoint(self) -> None:
        """Test that get_job_log calls GET /projects/{id}/jobs/{job_id}/trace."""
        route = respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(
            200,
            text="Build output line 1\nBuild output line 2\n",
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500)

        assert route.called
        assert "Build output line 1" in result["content"]

    @respx.mock
    async def test_returns_plain_text_content(self) -> None:
        """Test that job log returns plain text content, not JSON."""
        log_text = "Step 1: Building...\nStep 2: Testing...\nStep 3: Done.\n"
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500)

        assert result["content"] == log_text
        assert result["truncated"] is False
        assert result["byte_count"] == len(log_text.encode("utf-8"))

    @respx.mock
    async def test_empty_job_log(self) -> None:
        """Test that an empty job log returns empty content."""
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text="")

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500)

        assert result["content"] == ""
        assert result["truncated"] is False
        assert result["byte_count"] == 0

    @respx.mock
    async def test_truncation_at_max_bytes(self) -> None:
        """Test that logs exceeding max_bytes are truncated."""
        # Create a log that is exactly 100 bytes
        log_text = "X" * 100
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500, max_bytes=50)

        assert result["truncated"] is True
        assert result["byte_count"] == 100
        # Content should start with the first 50 bytes
        assert result["content"].startswith("X" * 50)
        # Should include truncation notice
        assert "truncated" in result["content"].lower()
        assert "50" in result["content"]
        assert "100" in result["content"]

    @respx.mock
    async def test_truncation_at_exact_boundary(self) -> None:
        """Test truncation at exact byte boundary."""
        log_text = "A" * 10
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            # max_bytes equals byte count - should NOT truncate
            result = await service.get_job_log(project_id=42, job_id=500, max_bytes=10)

        assert result["truncated"] is False
        assert result["content"] == log_text
        assert result["byte_count"] == 10

    @respx.mock
    async def test_truncation_one_byte_over(self) -> None:
        """Test truncation when log is one byte over max_bytes."""
        log_text = "B" * 11
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500, max_bytes=10)

        assert result["truncated"] is True
        assert result["byte_count"] == 11
        assert result["content"].startswith("B" * 10)
        assert "truncated" in result["content"].lower()

    @respx.mock
    async def test_default_max_bytes(self) -> None:
        """Test that the default max_bytes is 100KB (102400)."""
        assert DEFAULT_MAX_LOG_BYTES == 102400

        # Create log under 100KB - should not truncate
        log_text = "x" * 100
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500)

        assert result["truncated"] is False

    @respx.mock
    async def test_very_large_log_truncated(self) -> None:
        """Test that a very large job log is truncated with notice."""
        # 200KB log
        log_text = "L" * 204800
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500)

        assert result["truncated"] is True
        assert result["byte_count"] == 204800
        # Should include the truncation notice
        assert "--- Log truncated" in result["content"]
        assert "102400" in result["content"]
        assert "204800" in result["content"]

    @respx.mock
    async def test_custom_max_bytes(self) -> None:
        """Test that max_bytes is configurable."""
        log_text = "C" * 500
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(200, text=log_text)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service.get_job_log(project_id=42, job_id=500, max_bytes=200)

        assert result["truncated"] is True
        assert result["byte_count"] == 500
        assert result["content"].startswith("C" * 200)
        assert "200" in result["content"]
        assert "500" in result["content"]

    @respx.mock
    async def test_job_not_found(self) -> None:
        """Test that 404 raises GitLabAPIError with NOT_FOUND error code."""
        respx.get(f"{BASE_API}/projects/42/jobs/999/trace").respond(404)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_job_log(project_id=42, job_id=999)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_connection_error(self) -> None:
        """Test that connection errors are mapped to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").mock(
            side_effect=httpx.ConnectError("refused")
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_job_log(project_id=42, job_id=500)

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_timeout_error(self) -> None:
        """Test that timeout errors are mapped to CONNECTION_ERROR."""
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_job_log(project_id=42, job_id=500)

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_server_error(self) -> None:
        """Test that 500 errors are mapped to API_ERROR."""
        respx.get(f"{BASE_API}/projects/42/jobs/500/trace").respond(500)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service.get_job_log(project_id=42, job_id=500)

        assert exc_info.value.error_code == ErrorCode.API_ERROR
        assert exc_info.value.status_code == 500


class TestGetTextMethod:
    """Tests for the _get_text internal method."""

    @respx.mock
    async def test_returns_text_content(self) -> None:
        """Test that _get_text returns the response as plain text."""
        respx.get(f"{BASE_API}/test/endpoint").respond(
            200,
            text="plain text response",
        )

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            result = await service._get_text("/test/endpoint")

        assert result == "plain text response"

    @respx.mock
    async def test_raises_on_404(self) -> None:
        """Test that _get_text raises GitLabAPIError on 404."""
        respx.get(f"{BASE_API}/test/endpoint").respond(404)

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get_text("/test/endpoint")

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_raises_on_connection_error(self) -> None:
        """Test that _get_text wraps connection errors."""
        respx.get(f"{BASE_API}/test/endpoint").mock(side_effect=httpx.ConnectError("refused"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get_text("/test/endpoint")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_raises_on_timeout(self) -> None:
        """Test that _get_text wraps timeout errors."""
        respx.get(f"{BASE_API}/test/endpoint").mock(side_effect=httpx.ReadTimeout("read timed out"))

        async with httpx.AsyncClient() as client:
            service = _make_service(client=client)
            with pytest.raises(GitLabAPIError) as exc_info:
                await service._get_text("/test/endpoint")

        assert exc_info.value.error_code == ErrorCode.CONNECTION_ERROR


class TestPipelineServiceInheritance:
    """Tests verifying PipelineService properly inherits from GitLabService."""

    def test_is_subclass_of_gitlab_service(self) -> None:
        """Test that PipelineService is a subclass of GitLabService."""
        from mamba_mcp_gitlab.services.base import GitLabService

        assert issubclass(PipelineService, GitLabService)

    def test_inherits_base_url(self) -> None:
        """Test that PipelineService inherits base_url from GitLabService."""
        service = _make_service()
        assert service.base_url == f"{GITLAB_URL}/api/v4"

    def test_inherits_build_project_url(self) -> None:
        """Test that PipelineService inherits _build_project_url."""
        service = _make_service()
        url = service._build_project_url(42, "pipelines")
        assert url == "/projects/42/pipelines"
