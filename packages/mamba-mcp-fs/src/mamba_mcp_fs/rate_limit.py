"""Rate limiting for MCP server operations.

Implements a sliding window counter algorithm for per-server-instance
rate limiting. Based on spec Section 6.2 (REQ-SEC-006).

When enabled, tracks operation timestamps within a 60-second window.
Operations exceeding the configured limit receive a RATE_LIMITED error
with retry_after information.
"""

from __future__ import annotations

import time

from mamba_mcp_fs.errors import RateLimitedError

# Window size in seconds for the sliding window counter
WINDOW_SIZE = 60.0


class RateLimiter:
    """Sliding window rate limiter for MCP tool operations.

    Tracks operation timestamps and enforces an operations-per-minute limit.
    When the limit is exceeded, raises RateLimitedError with retry_after
    information indicating how long to wait before the next allowed operation.

    Args:
        ops_per_minute: Maximum operations allowed per 60-second window.
            0 disables rate limiting entirely.
    """

    def __init__(self, ops_per_minute: int) -> None:
        self.ops_per_minute = ops_per_minute
        self.enabled = ops_per_minute > 0
        self._timestamps: list[float] = []

    def _prune(self, now: float) -> None:
        """Remove timestamps older than the sliding window.

        Args:
            now: Current time as returned by time.monotonic().
        """
        cutoff = now - WINDOW_SIZE
        # Find the first index that is within the window
        idx = 0
        for idx, ts in enumerate(self._timestamps):
            if ts > cutoff:
                break
        else:
            # All entries are expired (or list is empty)
            if self._timestamps and self._timestamps[-1] <= cutoff:
                idx = len(self._timestamps)
        if idx > 0:
            self._timestamps = self._timestamps[idx:]

    def _compute_retry_after(self, now: float) -> float:
        """Calculate seconds until the oldest entry falls out of the window.

        Args:
            now: Current time as returned by time.monotonic().

        Returns:
            Seconds to wait before the next operation will be allowed.
            Always returns at least 0.1 to avoid zero-second waits.
        """
        if not self._timestamps:
            return 0.1
        oldest = self._timestamps[0]
        retry_after = (oldest + WINDOW_SIZE) - now
        return max(retry_after, 0.1)

    async def check(self) -> None:
        """Check if the rate limit has been exceeded.

        If rate limiting is disabled (ops_per_minute=0), returns immediately.
        If the current operation count within the sliding window is at or above
        the limit, raises RateLimitedError with retry_after details.

        Raises:
            RateLimitedError: When the rate limit is exceeded.
        """
        if not self.enabled:
            return

        now = time.monotonic()
        self._prune(now)

        if len(self._timestamps) >= self.ops_per_minute:
            retry_after = self._compute_retry_after(now)
            raise RateLimitedError(
                f"Rate limit exceeded: {self.ops_per_minute} operations per minute. "
                f"Try again in {retry_after:.1f} seconds."
            )

    async def acquire(self) -> None:
        """Record an operation timestamp after a successful check.

        Call this after check() succeeds to register the operation
        in the sliding window. If rate limiting is disabled, this
        is a no-op.
        """
        if not self.enabled:
            return

        now = time.monotonic()
        self._timestamps.append(now)

    @property
    def current_count(self) -> int:
        """Return the number of operations in the current window.

        Prunes expired timestamps before counting.
        """
        if not self.enabled:
            return 0

        now = time.monotonic()
        self._prune(now)
        return len(self._timestamps)

    @property
    def remaining(self) -> int | None:
        """Return the number of remaining operations allowed, or None if disabled."""
        if not self.enabled:
            return None

        return max(0, self.ops_per_minute - self.current_count)
