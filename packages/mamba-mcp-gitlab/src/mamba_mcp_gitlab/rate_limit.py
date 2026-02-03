"""Sliding window rate limiter for GitLab API requests.

Implements a sliding window counter algorithm for client-side rate limiting
of GitLab API calls. Adapted from the mamba-mcp-fs RateLimiter pattern with
configurable window size and asyncio.Lock for thread safety.

When enabled, tracks request timestamps within a configurable time window.
Requests exceeding the configured limit receive a RATE_LIMITED error with
retry_after information.

Based on Spec Section 9.3.
"""

from __future__ import annotations

import asyncio
import time


class RateLimitError(Exception):
    """Raised when the rate limit is exceeded.

    Carries retry_after information so callers know how long to wait
    before the next request will be allowed.

    Attributes:
        retry_after: Seconds until the next request will be allowed.
        max_requests: The configured maximum requests per window.
        window_seconds: The configured window size in seconds.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float,
        max_requests: int,
        window_seconds: float,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.max_requests = max_requests
        self.window_seconds = window_seconds


class RateLimiter:
    """Sliding window rate limiter for GitLab API requests.

    Tracks request timestamps and enforces a requests-per-window limit.
    When the limit is exceeded, raises RateLimitError with retry_after
    information indicating how long to wait before the next allowed request.

    Thread-safe via asyncio.Lock for concurrent tool handler access.

    Args:
        max_requests: Maximum requests allowed per time window.
            0 disables rate limiting entirely.
        window_seconds: Time window size in seconds (default 60.0).
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = float(window_seconds)
        self.enabled = max_requests > 0
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        """Remove timestamps older than the sliding window.

        Args:
            now: Current time as returned by time.monotonic().
        """
        cutoff = now - self.window_seconds
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
            Seconds to wait before the next request will be allowed.
            Always returns at least 0.1 to avoid zero-second waits.
        """
        if not self._timestamps:
            return 0.1
        oldest = self._timestamps[0]
        retry_after = (oldest + self.window_seconds) - now
        return max(retry_after, 0.1)

    async def acquire(self) -> None:
        """Check rate limit and record a request timestamp.

        If rate limiting is disabled (max_requests=0), returns immediately.
        If the current request count within the sliding window is at or above
        the limit, raises RateLimitError with retry_after details.

        Otherwise, records the current timestamp in the sliding window.

        Raises:
            RateLimitError: When the rate limit is exceeded.
        """
        if not self.enabled:
            return

        async with self._lock:
            now = time.monotonic()
            self._prune(now)

            if len(self._timestamps) >= self.max_requests:
                retry_after = self._compute_retry_after(now)
                raise RateLimitError(
                    f"Rate limit exceeded: {self.max_requests} requests "
                    f"per {self.window_seconds:.0f}s window. "
                    f"Try again in {retry_after:.1f} seconds.",
                    retry_after=retry_after,
                    max_requests=self.max_requests,
                    window_seconds=self.window_seconds,
                )

            self._timestamps.append(now)

    @property
    def current_count(self) -> int:
        """Return the number of requests in the current window.

        Prunes expired timestamps before counting.
        """
        if not self.enabled:
            return 0

        now = time.monotonic()
        self._prune(now)
        return len(self._timestamps)

    @property
    def remaining(self) -> int | None:
        """Return the number of remaining requests allowed, or None if disabled."""
        if not self.enabled:
            return None

        return max(0, self.max_requests - self.current_count)
