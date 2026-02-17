"""Tests for rate limiting module (RateLimiter sliding window algorithm).

Covers: disabled mode, operations within limit, operations exceeding limit,
retry_after accuracy, window rollover, burst handling, boundary conditions,
and integration with AppContext.
"""

from __future__ import annotations

import time

import pytest
from mamba_mcp_fs.errors import ErrorCode, RateLimitedError
from mamba_mcp_fs.rate_limit import WINDOW_SIZE, RateLimiter


# ---------------------------------------------------------------------------
# Disabled mode (ops_per_minute=0)
# ---------------------------------------------------------------------------
class TestRateLimiterDisabled:
    """Rate limiting is disabled when ops_per_minute=0."""

    def test_disabled_by_default(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        assert limiter.enabled is False

    def test_disabled_ops_per_minute_zero(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        assert limiter.ops_per_minute == 0

    @pytest.mark.asyncio
    async def test_check_succeeds_when_disabled(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        # Should not raise even after many checks
        for _ in range(1000):
            await limiter.check()

    @pytest.mark.asyncio
    async def test_acquire_is_noop_when_disabled(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        await limiter.acquire()
        assert limiter.current_count == 0

    def test_current_count_is_zero_when_disabled(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        assert limiter.current_count == 0

    def test_remaining_is_none_when_disabled(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        assert limiter.remaining is None


# ---------------------------------------------------------------------------
# Enabled mode -- basic operations within limit
# ---------------------------------------------------------------------------
class TestRateLimiterWithinLimit:
    """Operations within the configured limit proceed normally."""

    def test_enabled_when_positive(self) -> None:
        limiter = RateLimiter(ops_per_minute=10)
        assert limiter.enabled is True

    def test_ops_per_minute_stored(self) -> None:
        limiter = RateLimiter(ops_per_minute=60)
        assert limiter.ops_per_minute == 60

    @pytest.mark.asyncio
    async def test_single_operation_succeeds(self) -> None:
        limiter = RateLimiter(ops_per_minute=10)
        await limiter.check()
        await limiter.acquire()

    @pytest.mark.asyncio
    async def test_multiple_operations_within_limit(self) -> None:
        limiter = RateLimiter(ops_per_minute=5)
        for _ in range(5):
            await limiter.check()
            await limiter.acquire()
        # All 5 should have succeeded
        assert limiter.current_count == 5

    @pytest.mark.asyncio
    async def test_current_count_increments(self) -> None:
        limiter = RateLimiter(ops_per_minute=10)
        assert limiter.current_count == 0
        await limiter.acquire()
        assert limiter.current_count == 1
        await limiter.acquire()
        assert limiter.current_count == 2

    @pytest.mark.asyncio
    async def test_remaining_decrements(self) -> None:
        limiter = RateLimiter(ops_per_minute=5)
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

    @pytest.mark.asyncio
    async def test_exceeds_limit_raises_error(self) -> None:
        limiter = RateLimiter(ops_per_minute=3)
        for _ in range(3):
            await limiter.check()
            await limiter.acquire()
        with pytest.raises(RateLimitedError):
            await limiter.check()

    @pytest.mark.asyncio
    async def test_error_is_fs_error_subclass(self) -> None:
        limiter = RateLimiter(ops_per_minute=1)
        await limiter.check()
        await limiter.acquire()
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check()
        assert exc_info.value.code == ErrorCode.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_error_message_includes_limit(self) -> None:
        limiter = RateLimiter(ops_per_minute=5)
        for _ in range(5):
            await limiter.acquire()
        with pytest.raises(RateLimitedError, match="5 operations per minute"):
            await limiter.check()

    @pytest.mark.asyncio
    async def test_error_message_includes_retry_after(self) -> None:
        limiter = RateLimiter(ops_per_minute=1)
        await limiter.acquire()
        with pytest.raises(RateLimitedError, match=r"Try again in \d+\.\d+ seconds"):
            await limiter.check()

    @pytest.mark.asyncio
    async def test_remaining_is_zero_when_at_limit(self) -> None:
        limiter = RateLimiter(ops_per_minute=3)
        for _ in range(3):
            await limiter.acquire()
        assert limiter.remaining == 0


# ---------------------------------------------------------------------------
# retry_after accuracy
# ---------------------------------------------------------------------------
class TestRetryAfterAccuracy:
    """retry_after value is accurate and reflects window expiry timing."""

    @pytest.mark.asyncio
    async def test_retry_after_based_on_oldest_timestamp(self) -> None:
        """retry_after should be roughly the time until the oldest entry expires."""
        limiter = RateLimiter(ops_per_minute=2)

        # Record the time before first acquire
        t_before = time.monotonic()
        await limiter.acquire()
        await limiter.acquire()

        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check()

        # Parse retry_after from the error message
        msg = exc_info.value.message
        retry_str = msg.split("Try again in ")[1].split(" seconds")[0]
        retry_after = float(retry_str)

        # Should be close to WINDOW_SIZE (60s) since we just acquired
        t_after = time.monotonic()
        elapsed = t_after - t_before
        expected_retry = WINDOW_SIZE - elapsed
        assert retry_after == pytest.approx(expected_retry, abs=1.0)

    @pytest.mark.asyncio
    async def test_retry_after_minimum_value(self) -> None:
        """retry_after should never be less than 0.1 seconds."""
        limiter = RateLimiter(ops_per_minute=1)
        # Manually inject an old timestamp that's about to expire
        limiter._timestamps = [time.monotonic() - WINDOW_SIZE + 0.01]
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check()
        msg = exc_info.value.message
        retry_str = msg.split("Try again in ")[1].split(" seconds")[0]
        retry_after = float(retry_str)
        assert retry_after >= 0.1

    def test_compute_retry_after_empty_timestamps_returns_minimum(self) -> None:
        """_compute_retry_after returns 0.1 when timestamps list is empty."""
        limiter = RateLimiter(ops_per_minute=5)
        # Ensure timestamps list is empty
        assert len(limiter._timestamps) == 0
        result = limiter._compute_retry_after(time.monotonic())
        assert result == 0.1


# ---------------------------------------------------------------------------
# Exact limit boundary
# ---------------------------------------------------------------------------
class TestRateLimiterBoundary:
    """Exact limit boundary behavior -- Nth operation at limit."""

    @pytest.mark.asyncio
    async def test_nth_operation_at_limit_succeeds(self) -> None:
        """The Nth operation (where N = limit) should succeed."""
        limiter = RateLimiter(ops_per_minute=5)
        for _ in range(4):
            await limiter.check()
            await limiter.acquire()
        # 5th operation should still succeed (at limit, not over)
        await limiter.check()
        await limiter.acquire()
        assert limiter.current_count == 5

    @pytest.mark.asyncio
    async def test_n_plus_1_operation_fails(self) -> None:
        """The (N+1)th operation (one over limit) should fail."""
        limiter = RateLimiter(ops_per_minute=5)
        for _ in range(5):
            await limiter.check()
            await limiter.acquire()
        with pytest.raises(RateLimitedError):
            await limiter.check()

    @pytest.mark.asyncio
    async def test_limit_of_one(self) -> None:
        """With limit=1, first op succeeds, second fails."""
        limiter = RateLimiter(ops_per_minute=1)
        await limiter.check()
        await limiter.acquire()
        with pytest.raises(RateLimitedError):
            await limiter.check()


# ---------------------------------------------------------------------------
# Window rollover
# ---------------------------------------------------------------------------
class TestRateLimiterWindowRollover:
    """Rate limit window rollover allows operations after timestamps expire."""

    @pytest.mark.asyncio
    async def test_old_timestamps_pruned(self) -> None:
        """Timestamps older than WINDOW_SIZE are removed."""
        limiter = RateLimiter(ops_per_minute=2)
        # Inject timestamps that are already expired
        old_time = time.monotonic() - WINDOW_SIZE - 1.0
        limiter._timestamps = [old_time, old_time + 0.1]
        # Both should be pruned, so check should succeed
        await limiter.check()
        assert limiter.current_count == 0

    @pytest.mark.asyncio
    async def test_operations_allowed_after_window_expires(self) -> None:
        """After old entries fall out of window, new operations are allowed."""
        limiter = RateLimiter(ops_per_minute=2)
        # Inject expired timestamps to simulate window rollover
        expired = time.monotonic() - WINDOW_SIZE - 1.0
        limiter._timestamps = [expired, expired + 0.1]
        # Should be allowed again
        await limiter.check()
        await limiter.acquire()
        assert limiter.current_count == 1

    @pytest.mark.asyncio
    async def test_partial_window_expiry(self) -> None:
        """When some timestamps expire but others remain, count is correct."""
        limiter = RateLimiter(ops_per_minute=3)
        now = time.monotonic()
        # Two expired, one fresh
        limiter._timestamps = [
            now - WINDOW_SIZE - 2.0,
            now - WINDOW_SIZE - 1.0,
            now - 1.0,
        ]
        # Only 1 fresh timestamp remains
        assert limiter.current_count == 1
        assert limiter.remaining == 2

    @pytest.mark.asyncio
    async def test_mixed_old_and_new_timestamps(self) -> None:
        """Mix of old and new timestamps: only new ones count."""
        limiter = RateLimiter(ops_per_minute=5)
        now = time.monotonic()
        limiter._timestamps = [
            now - 120.0,  # old (2 min ago)
            now - 90.0,  # old (1.5 min ago)
            now - 30.0,  # fresh (30s ago)
            now - 10.0,  # fresh (10s ago)
        ]
        assert limiter.current_count == 2
        assert limiter.remaining == 3


# ---------------------------------------------------------------------------
# Burst of operations
# ---------------------------------------------------------------------------
class TestRateLimiterBurst:
    """Burst of operations -- rapid-fire requests."""

    @pytest.mark.asyncio
    async def test_burst_within_limit_succeeds(self) -> None:
        """Rapid burst of operations within the limit all succeed."""
        limiter = RateLimiter(ops_per_minute=10)
        for _ in range(10):
            await limiter.check()
            await limiter.acquire()
        # All should succeed within the same moment
        assert limiter.current_count == 10

    @pytest.mark.asyncio
    async def test_burst_exceeding_limit_fails_at_boundary(self) -> None:
        """Rapid burst exceeding the limit fails at exactly the right point."""
        limiter = RateLimiter(ops_per_minute=5)
        succeeded = 0
        for _ in range(10):
            try:
                await limiter.check()
                await limiter.acquire()
                succeeded += 1
            except RateLimitedError:
                break
        assert succeeded == 5


# ---------------------------------------------------------------------------
# Error response details
# ---------------------------------------------------------------------------
class TestRateLimitedErrorDetails:
    """RATE_LIMITED error includes helpful information."""

    @pytest.mark.asyncio
    async def test_error_has_rate_limited_code(self) -> None:
        limiter = RateLimiter(ops_per_minute=1)
        await limiter.acquire()
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check()
        assert exc_info.value.code == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_error_message_is_informative(self) -> None:
        limiter = RateLimiter(ops_per_minute=10)
        for _ in range(10):
            await limiter.acquire()
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check()
        msg = exc_info.value.message
        assert "Rate limit exceeded" in msg
        assert "10 operations per minute" in msg
        assert "Try again in" in msg

    @pytest.mark.asyncio
    async def test_error_inherits_from_fs_error(self) -> None:
        """RateLimitedError is catchable as FSError."""
        from mamba_mcp_fs.errors import FSError

        limiter = RateLimiter(ops_per_minute=1)
        await limiter.acquire()
        with pytest.raises(FSError):
            await limiter.check()


# ---------------------------------------------------------------------------
# Performance -- negligible overhead
# ---------------------------------------------------------------------------
class TestRateLimiterPerformance:
    """Rate limit check adds negligible overhead (<1ms)."""

    @pytest.mark.asyncio
    async def test_check_is_fast_when_disabled(self) -> None:
        limiter = RateLimiter(ops_per_minute=0)
        start = time.monotonic()
        for _ in range(1000):
            await limiter.check()
        elapsed = time.monotonic() - start
        # 1000 checks should be well under 1 second
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_check_is_fast_when_enabled(self) -> None:
        limiter = RateLimiter(ops_per_minute=10000)
        # Fill up some timestamps
        for _ in range(100):
            await limiter.acquire()
        start = time.monotonic()
        for _ in range(1000):
            await limiter.check()
        elapsed = time.monotonic() - start
        # 1000 checks should be well under 1 second
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_acquire_is_fast(self) -> None:
        limiter = RateLimiter(ops_per_minute=100000)
        start = time.monotonic()
        for _ in range(1000):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0


# ---------------------------------------------------------------------------
# Integration: RateLimiter with AppContext
# ---------------------------------------------------------------------------
class TestRateLimiterAppContext:
    """Rate limiter integrates with AppContext and server setup."""

    def test_rate_limiter_in_app_context(self) -> None:
        """AppContext has a rate_limiter field."""
        import dataclasses

        from mamba_mcp_fs.server import AppContext

        field_names = [f.name for f in dataclasses.fields(AppContext)]
        assert "rate_limiter" in field_names

    def test_rate_limiter_created_from_config(self) -> None:
        """RateLimiter can be created from ServerSettings rate_limit value."""
        from mamba_mcp_fs.config import ServerSettings

        settings = ServerSettings()
        limiter = RateLimiter(ops_per_minute=settings.rate_limit)
        assert limiter.enabled is False  # default rate_limit=0

    def test_rate_limiter_enabled_from_config(self) -> None:
        """RateLimiter is enabled when rate_limit > 0."""
        limiter = RateLimiter(ops_per_minute=100)
        assert limiter.enabled is True
        assert limiter.ops_per_minute == 100


# ---------------------------------------------------------------------------
# Integration: Multiple tool calls across rate limiter
# ---------------------------------------------------------------------------
class TestRateLimiterMultipleTools:
    """Rate limiting applies across all tool calls per-server instance."""

    @pytest.mark.asyncio
    async def test_shared_rate_limiter_across_operations(self) -> None:
        """A single rate limiter tracks operations from different tools."""
        limiter = RateLimiter(ops_per_minute=3)

        # Simulate 3 different tool calls
        await limiter.check()
        await limiter.acquire()

        await limiter.check()
        await limiter.acquire()

        await limiter.check()
        await limiter.acquire()

        # 4th call from any tool should fail
        with pytest.raises(RateLimitedError):
            await limiter.check()

    @pytest.mark.asyncio
    async def test_check_without_acquire_does_not_count(self) -> None:
        """check() alone does not consume capacity -- only acquire() does."""
        limiter = RateLimiter(ops_per_minute=2)
        # Just checking should not consume
        await limiter.check()
        await limiter.check()
        await limiter.check()
        assert limiter.current_count == 0

        # Now actually acquire
        await limiter.acquire()
        await limiter.acquire()
        # 3rd check should fail because acquire was called twice
        with pytest.raises(RateLimitedError):
            await limiter.check()


# ---------------------------------------------------------------------------
# Edge: window_size constant
# ---------------------------------------------------------------------------
class TestWindowSizeConstant:
    """The WINDOW_SIZE constant is set correctly."""

    def test_window_size_is_60_seconds(self) -> None:
        assert WINDOW_SIZE == 60.0

    def test_window_size_is_float(self) -> None:
        assert isinstance(WINDOW_SIZE, float)
