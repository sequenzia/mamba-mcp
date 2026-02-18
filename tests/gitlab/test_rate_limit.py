"""Tests for the sliding window rate limiter module.

Covers: disabled mode, operations within limit, operations exceeding limit,
retry_after accuracy, window rollover, burst handling, configurable window size,
thread safety, boundary conditions, base service integration, and performance.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx
from mamba_mcp_gitlab.errors import ErrorCode
from mamba_mcp_gitlab.rate_limit import RateLimiter, RateLimitError
from mamba_mcp_gitlab.services.base import GitLabAPIError, GitLabService

from tests.gitlab.conftest import make_settings


# ---------------------------------------------------------------------------
# Disabled mode (max_requests=0)
# ---------------------------------------------------------------------------
class TestRateLimiterDisabled:
    """Rate limiting is disabled when max_requests=0."""

    def test_disabled_when_max_requests_zero(self) -> None:
        """RateLimiter is disabled when max_requests=0."""
        limiter = RateLimiter(max_requests=0)
        assert limiter.enabled is False

    def test_max_requests_stored(self) -> None:
        """max_requests value is stored on the instance."""
        limiter = RateLimiter(max_requests=0)
        assert limiter.max_requests == 0

    async def test_acquire_succeeds_when_disabled(self) -> None:
        """acquire() does not raise even after many calls when disabled."""
        limiter = RateLimiter(max_requests=0)
        for _ in range(1000):
            await limiter.acquire()

    async def test_acquire_does_not_record_when_disabled(self) -> None:
        """acquire() does not record timestamps when disabled."""
        limiter = RateLimiter(max_requests=0)
        await limiter.acquire()
        assert limiter.current_count == 0

    def test_current_count_is_zero_when_disabled(self) -> None:
        """current_count returns 0 when disabled."""
        limiter = RateLimiter(max_requests=0)
        assert limiter.current_count == 0

    def test_remaining_is_none_when_disabled(self) -> None:
        """remaining returns None when disabled."""
        limiter = RateLimiter(max_requests=0)
        assert limiter.remaining is None


# ---------------------------------------------------------------------------
# Enabled mode -- basic operations within limit
# ---------------------------------------------------------------------------
class TestRateLimiterWithinLimit:
    """Operations within the configured limit proceed normally."""

    def test_enabled_when_positive(self) -> None:
        """RateLimiter is enabled when max_requests > 0."""
        limiter = RateLimiter(max_requests=10)
        assert limiter.enabled is True

    def test_max_requests_stored(self) -> None:
        """max_requests value is stored on the instance."""
        limiter = RateLimiter(max_requests=60)
        assert limiter.max_requests == 60

    async def test_single_operation_succeeds(self) -> None:
        """A single acquire succeeds without error."""
        limiter = RateLimiter(max_requests=10)
        await limiter.acquire()

    async def test_multiple_operations_within_limit(self) -> None:
        """Multiple acquires within the limit all succeed."""
        limiter = RateLimiter(max_requests=5)
        for _ in range(5):
            await limiter.acquire()
        assert limiter.current_count == 5

    async def test_current_count_increments(self) -> None:
        """current_count increments after each acquire."""
        limiter = RateLimiter(max_requests=10)
        assert limiter.current_count == 0
        await limiter.acquire()
        assert limiter.current_count == 1
        await limiter.acquire()
        assert limiter.current_count == 2

    async def test_remaining_decrements(self) -> None:
        """remaining decrements after each acquire."""
        limiter = RateLimiter(max_requests=5)
        assert limiter.remaining == 5
        await limiter.acquire()
        assert limiter.remaining == 4
        await limiter.acquire()
        assert limiter.remaining == 3


# ---------------------------------------------------------------------------
# Operations exceeding the limit
# ---------------------------------------------------------------------------
class TestRateLimiterExceedsLimit:
    """Operations exceeding the limit receive RATE_LIMITED errors."""

    async def test_exceeds_limit_raises_rate_limit_error(self) -> None:
        """Exceeding the limit raises RateLimitError."""
        limiter = RateLimiter(max_requests=3)
        for _ in range(3):
            await limiter.acquire()
        with pytest.raises(RateLimitError):
            await limiter.acquire()

    async def test_error_message_includes_limit(self) -> None:
        """Error message includes the configured request limit."""
        limiter = RateLimiter(max_requests=5)
        for _ in range(5):
            await limiter.acquire()
        with pytest.raises(RateLimitError, match="5 requests"):
            await limiter.acquire()

    async def test_error_message_includes_window(self) -> None:
        """Error message includes the window size."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            await limiter.acquire()
        with pytest.raises(RateLimitError, match="60s window"):
            await limiter.acquire()

    async def test_error_message_includes_retry_after(self) -> None:
        """Error message includes retry_after timing."""
        limiter = RateLimiter(max_requests=1)
        await limiter.acquire()
        with pytest.raises(RateLimitError, match=r"Try again in \d+\.\d+ seconds"):
            await limiter.acquire()

    async def test_error_carries_retry_after_attribute(self) -> None:
        """RateLimitError carries retry_after as a numeric attribute."""
        limiter = RateLimiter(max_requests=1, window_seconds=30)
        await limiter.acquire()
        with pytest.raises(RateLimitError) as exc_info:
            await limiter.acquire()
        assert exc_info.value.retry_after > 0
        assert exc_info.value.retry_after <= 30.0

    async def test_error_carries_max_requests_attribute(self) -> None:
        """RateLimitError carries the max_requests value."""
        limiter = RateLimiter(max_requests=5)
        for _ in range(5):
            await limiter.acquire()
        with pytest.raises(RateLimitError) as exc_info:
            await limiter.acquire()
        assert exc_info.value.max_requests == 5

    async def test_error_carries_window_seconds_attribute(self) -> None:
        """RateLimitError carries the window_seconds value."""
        limiter = RateLimiter(max_requests=1, window_seconds=120)
        await limiter.acquire()
        with pytest.raises(RateLimitError) as exc_info:
            await limiter.acquire()
        assert exc_info.value.window_seconds == 120.0

    async def test_remaining_is_zero_when_at_limit(self) -> None:
        """remaining returns 0 when at or over limit."""
        limiter = RateLimiter(max_requests=3)
        for _ in range(3):
            await limiter.acquire()
        assert limiter.remaining == 0


# ---------------------------------------------------------------------------
# retry_after accuracy
# ---------------------------------------------------------------------------
class TestRetryAfterAccuracy:
    """retry_after value reflects window expiry timing."""

    async def test_retry_after_based_on_oldest_timestamp(self) -> None:
        """retry_after is roughly the time until the oldest entry expires."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        t_before = time.monotonic()
        await limiter.acquire()
        await limiter.acquire()

        with pytest.raises(RateLimitError) as exc_info:
            await limiter.acquire()

        t_after = time.monotonic()
        elapsed = t_after - t_before
        expected_retry = 60.0 - elapsed
        assert exc_info.value.retry_after == pytest.approx(expected_retry, abs=1.0)

    async def test_retry_after_minimum_value(self) -> None:
        """retry_after is always at least 0.1 seconds."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        # Inject an old timestamp about to expire
        limiter._timestamps = [time.monotonic() - 60.0 + 0.01]
        with pytest.raises(RateLimitError) as exc_info:
            await limiter.acquire()
        assert exc_info.value.retry_after >= 0.1

    def test_compute_retry_after_empty_timestamps(self) -> None:
        """_compute_retry_after returns 0.1 when timestamps list is empty."""
        limiter = RateLimiter(max_requests=5)
        assert len(limiter._timestamps) == 0
        result = limiter._compute_retry_after(time.monotonic())
        assert result == 0.1


# ---------------------------------------------------------------------------
# Configurable window size
# ---------------------------------------------------------------------------
class TestConfigurableWindowSize:
    """Window size is configurable via constructor parameter."""

    def test_default_window_is_60_seconds(self) -> None:
        """Default window_seconds is 60.0."""
        limiter = RateLimiter(max_requests=10)
        assert limiter.window_seconds == 60.0

    def test_custom_window_size(self) -> None:
        """Custom window_seconds is stored correctly."""
        limiter = RateLimiter(max_requests=10, window_seconds=120)
        assert limiter.window_seconds == 120.0

    def test_window_size_converted_to_float(self) -> None:
        """Integer window_seconds is converted to float."""
        limiter = RateLimiter(max_requests=10, window_seconds=30)
        assert isinstance(limiter.window_seconds, float)
        assert limiter.window_seconds == 30.0

    async def test_short_window_expires_quickly(self) -> None:
        """Timestamps expire according to the configured window size."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.1)
        await limiter.acquire()
        await limiter.acquire()
        # Wait for the short window to expire
        import asyncio

        await asyncio.sleep(0.15)
        # Should be allowed again after window expires
        assert limiter.current_count == 0
        await limiter.acquire()

    async def test_custom_window_in_error_message(self) -> None:
        """Error message references the custom window size."""
        limiter = RateLimiter(max_requests=1, window_seconds=120)
        await limiter.acquire()
        with pytest.raises(RateLimitError, match="120s window"):
            await limiter.acquire()


# ---------------------------------------------------------------------------
# Exact limit boundary
# ---------------------------------------------------------------------------
class TestRateLimiterBoundary:
    """Exact limit boundary behavior."""

    async def test_nth_operation_at_limit_succeeds(self) -> None:
        """The Nth operation (where N = limit) succeeds."""
        limiter = RateLimiter(max_requests=5)
        for _ in range(4):
            await limiter.acquire()
        # 5th operation should succeed (at limit, not over)
        await limiter.acquire()
        assert limiter.current_count == 5

    async def test_n_plus_1_operation_fails(self) -> None:
        """The (N+1)th operation fails."""
        limiter = RateLimiter(max_requests=5)
        for _ in range(5):
            await limiter.acquire()
        with pytest.raises(RateLimitError):
            await limiter.acquire()

    async def test_limit_of_one(self) -> None:
        """With limit=1, first op succeeds, second fails."""
        limiter = RateLimiter(max_requests=1)
        await limiter.acquire()
        with pytest.raises(RateLimitError):
            await limiter.acquire()


# ---------------------------------------------------------------------------
# Window rollover
# ---------------------------------------------------------------------------
class TestRateLimiterWindowRollover:
    """Rate limit window rollover allows operations after timestamps expire."""

    async def test_old_timestamps_pruned(self) -> None:
        """Timestamps older than window_seconds are removed."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        old_time = time.monotonic() - 61.0
        limiter._timestamps = [old_time, old_time + 0.1]
        # Both should be pruned
        assert limiter.current_count == 0

    async def test_operations_allowed_after_window_expires(self) -> None:
        """After old entries fall out of window, new operations are allowed."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        expired = time.monotonic() - 61.0
        limiter._timestamps = [expired, expired + 0.1]
        await limiter.acquire()
        assert limiter.current_count == 1

    async def test_partial_window_expiry(self) -> None:
        """When some timestamps expire but others remain, count is correct."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        now = time.monotonic()
        limiter._timestamps = [
            now - 62.0,
            now - 61.0,
            now - 1.0,
        ]
        assert limiter.current_count == 1
        assert limiter.remaining == 2

    async def test_mixed_old_and_new_timestamps(self) -> None:
        """Mix of old and new timestamps: only new ones count."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        now = time.monotonic()
        limiter._timestamps = [
            now - 120.0,
            now - 90.0,
            now - 30.0,
            now - 10.0,
        ]
        assert limiter.current_count == 2
        assert limiter.remaining == 3

    async def test_immediately_after_window_expiration_allows_requests(self) -> None:
        """Rate limit immediately after window expiration allows new requests."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        # Inject a timestamp that just expired
        limiter._timestamps = [time.monotonic() - 60.1]
        # Should be pruned, allowing a new request
        await limiter.acquire()
        assert limiter.current_count == 1


# ---------------------------------------------------------------------------
# Burst of requests at window boundary
# ---------------------------------------------------------------------------
class TestRateLimiterBurst:
    """Burst of requests at window boundary."""

    async def test_burst_within_limit_succeeds(self) -> None:
        """Rapid burst within the limit all succeed."""
        limiter = RateLimiter(max_requests=10)
        for _ in range(10):
            await limiter.acquire()
        assert limiter.current_count == 10

    async def test_burst_exceeding_limit_fails_at_boundary(self) -> None:
        """Rapid burst exceeding the limit fails at exactly the right point."""
        limiter = RateLimiter(max_requests=5)
        succeeded = 0
        for _ in range(10):
            try:
                await limiter.acquire()
                succeeded += 1
            except RateLimitError:
                break
        assert succeeded == 5

    async def test_burst_at_window_boundary_with_expired(self) -> None:
        """Burst at window boundary with some expired timestamps."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        now = time.monotonic()
        # 2 expired + 1 recent = effectively only 1 in window
        limiter._timestamps = [now - 61.0, now - 61.0, now - 1.0]
        # Should allow 2 more requests (limit 3, 1 active)
        await limiter.acquire()
        await limiter.acquire()
        assert limiter.current_count == 3
        with pytest.raises(RateLimitError):
            await limiter.acquire()


# ---------------------------------------------------------------------------
# RateLimitError structure
# ---------------------------------------------------------------------------
class TestRateLimitErrorStructure:
    """RateLimitError carries structured error information."""

    def test_error_is_exception(self) -> None:
        """RateLimitError is a subclass of Exception."""
        err = RateLimitError(
            "test",
            retry_after=1.0,
            max_requests=10,
            window_seconds=60.0,
        )
        assert isinstance(err, Exception)

    def test_error_message_attribute(self) -> None:
        """RateLimitError stores the message."""
        err = RateLimitError(
            "limit exceeded",
            retry_after=5.0,
            max_requests=100,
            window_seconds=60.0,
        )
        assert err.message == "limit exceeded"

    def test_error_str_representation(self) -> None:
        """RateLimitError str() returns the message."""
        err = RateLimitError(
            "limit exceeded",
            retry_after=5.0,
            max_requests=100,
            window_seconds=60.0,
        )
        assert str(err) == "limit exceeded"

    def test_error_attributes(self) -> None:
        """RateLimitError carries retry_after, max_requests, window_seconds."""
        err = RateLimitError(
            "test",
            retry_after=2.5,
            max_requests=50,
            window_seconds=30.0,
        )
        assert err.retry_after == 2.5
        assert err.max_requests == 50
        assert err.window_seconds == 30.0


# ---------------------------------------------------------------------------
# Base service integration
# ---------------------------------------------------------------------------
class TestBaseServiceRateLimitIntegration:
    """Rate limiter integrates with GitLabService base class."""

    def test_service_accepts_rate_limiter(self) -> None:
        """GitLabService constructor accepts an optional rate_limiter."""
        settings = make_settings()
        limiter = RateLimiter(max_requests=10)
        client = httpx.AsyncClient()
        service = GitLabService(
            http_client=client,
            settings=settings,
            rate_limiter=limiter,
        )
        assert service.rate_limiter is limiter

    def test_service_defaults_to_no_rate_limiter(self) -> None:
        """GitLabService defaults to no rate limiter (None)."""
        settings = make_settings()
        client = httpx.AsyncClient()
        service = GitLabService(http_client=client, settings=settings)
        assert service.rate_limiter is None

    @respx.mock
    async def test_request_blocked_by_rate_limiter(self) -> None:
        """HTTP request is blocked when rate limit is exceeded."""
        settings = make_settings()
        limiter = RateLimiter(max_requests=1)
        client = httpx.AsyncClient(headers={"PRIVATE-TOKEN": "test"})
        service = GitLabService(
            http_client=client,
            settings=settings,
            rate_limiter=limiter,
        )

        # Mock the API endpoint
        respx.get("https://gitlab.example.com/api/v4/projects").respond(200, json=[])

        # First request succeeds
        await service._get("/projects")

        # Second request should be rate-limited
        with pytest.raises(GitLabAPIError) as exc_info:
            await service._get("/projects")
        assert exc_info.value.error_code == ErrorCode.RATE_LIMITED

    @respx.mock
    async def test_request_succeeds_without_rate_limiter(self) -> None:
        """HTTP request succeeds when no rate limiter is configured."""
        settings = make_settings()
        client = httpx.AsyncClient(headers={"PRIVATE-TOKEN": "test"})
        service = GitLabService(http_client=client, settings=settings)

        respx.get("https://gitlab.example.com/api/v4/projects").respond(200, json=[])

        # Should succeed without rate limiter
        result = await service._get("/projects")
        assert result == []

    @respx.mock
    async def test_rate_limit_error_has_correct_error_code(self) -> None:
        """GitLabAPIError from rate limit carries RATE_LIMITED error code."""
        settings = make_settings()
        limiter = RateLimiter(max_requests=2)
        client = httpx.AsyncClient(headers={"PRIVATE-TOKEN": "test"})
        service = GitLabService(
            http_client=client,
            settings=settings,
            rate_limiter=limiter,
        )

        url = "https://gitlab.example.com/api/v4/projects"
        respx.get(url).respond(200, json=[])
        respx.post(url).respond(200, json={})

        # Consume the limit
        await service._get("/projects")
        await service._post("/projects")

        # Third request should fail
        with pytest.raises(GitLabAPIError) as exc_info:
            await service._get("/projects")
        assert exc_info.value.error_code == ErrorCode.RATE_LIMITED
        assert "Rate limit exceeded" in str(exc_info.value)

    @respx.mock
    async def test_paginated_request_uses_rate_limiter(self) -> None:
        """_get_paginated also checks the rate limiter."""
        settings = make_settings()
        limiter = RateLimiter(max_requests=1)
        client = httpx.AsyncClient(headers={"PRIVATE-TOKEN": "test"})
        service = GitLabService(
            http_client=client,
            settings=settings,
            rate_limiter=limiter,
        )

        respx.get("https://gitlab.example.com/api/v4/projects").respond(
            200,
            json=[{"id": 1}],
            headers={"x-total": "1", "x-total-pages": "1"},
        )

        # First paginated request succeeds
        items, total, total_pages = await service._get_paginated("/projects")
        assert len(items) == 1

        # Second paginated request should be rate-limited
        with pytest.raises(GitLabAPIError) as exc_info:
            await service._get_paginated("/projects")
        assert exc_info.value.error_code == ErrorCode.RATE_LIMITED

    @respx.mock
    async def test_disabled_rate_limiter_allows_unlimited_requests(self) -> None:
        """Disabled rate limiter (max_requests=0) allows unlimited requests."""
        settings = make_settings()
        limiter = RateLimiter(max_requests=0)
        client = httpx.AsyncClient(headers={"PRIVATE-TOKEN": "test"})
        service = GitLabService(
            http_client=client,
            settings=settings,
            rate_limiter=limiter,
        )

        respx.get("https://gitlab.example.com/api/v4/projects").respond(200, json=[])

        # Many requests should all succeed
        for _ in range(50):
            await service._get("/projects")


# ---------------------------------------------------------------------------
# Server AppContext integration
# ---------------------------------------------------------------------------
class TestAppContextIntegration:
    """Rate limiter integrates with AppContext in server.py."""

    def test_app_context_rate_limiter_field(self) -> None:
        """AppContext has a rate_limiter field of type RateLimiter."""
        import dataclasses

        from mamba_mcp_gitlab.server import AppContext

        field_names = [f.name for f in dataclasses.fields(AppContext)]
        assert "rate_limiter" in field_names

    def test_app_context_accepts_rate_limiter(self) -> None:
        """AppContext can be constructed with a RateLimiter instance."""
        from mamba_mcp_gitlab.auth import AuthInfo
        from mamba_mcp_gitlab.server import AppContext

        limiter = RateLimiter(max_requests=100, window_seconds=60)
        ctx = AppContext(
            client=httpx.AsyncClient(),
            settings=make_settings(),
            rate_limiter=limiter,
            auth_info=AuthInfo(
                auth_type="pat",
                username="test",
                scopes=["api"],
                expires_at="2027-12-31",
            ),
        )
        assert isinstance(ctx.rate_limiter, RateLimiter)
        assert ctx.rate_limiter.max_requests == 100
        assert ctx.rate_limiter.enabled is True


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
class TestRateLimiterPerformance:
    """Rate limit check adds negligible overhead (<1ms per request)."""

    async def test_acquire_is_fast_when_disabled(self) -> None:
        """acquire() is fast when disabled."""
        limiter = RateLimiter(max_requests=0)
        start = time.monotonic()
        for _ in range(1000):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0

    async def test_acquire_is_fast_when_enabled(self) -> None:
        """acquire() with pruning is fast."""
        limiter = RateLimiter(max_requests=10000)
        for _ in range(100):
            await limiter.acquire()
        start = time.monotonic()
        for _ in range(1000):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0

    async def test_current_count_is_fast(self) -> None:
        """current_count property is fast even with many timestamps."""
        limiter = RateLimiter(max_requests=100000)
        for _ in range(1000):
            await limiter.acquire()
        start = time.monotonic()
        for _ in range(1000):
            _ = limiter.current_count
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
