"""Rate limiting for MyClaw.

Provides per-session and per-IP rate limiting with header support.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel


class RateLimitInfo(BaseModel):
    """Rate limit information for a client."""

    limit: int
    remaining: int
    reset: int


class SessionRateLimiter:
    """Per-session rate limiter with sliding window."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_session: int = 100,
        window_seconds: int = 60,
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_session = requests_per_session
        self.window_seconds = window_seconds

        self._ip_requests: dict[str, list[float]] = defaultdict(list)
        self._session_requests: dict[str, list[float]] = defaultdict(list)

    def _cleanup_old_requests(self, timestamps: list[float], now: float) -> list[float]:
        """Remove timestamps outside the window."""
        cutoff = now - self.window_seconds
        return [ts for ts in timestamps if ts > cutoff]

    def _check_rate_limit(
        self,
        timestamps: list[float],
        limit: int,
        now: float,
    ) -> tuple[bool, int]:
        """Check if request is within rate limit.

        Returns:
            Tuple of (is_allowed, remaining)
        """
        timestamps = self._cleanup_old_requests(timestamps, now)
        if len(timestamps) >= limit:
            return False, 0
        return True, limit - len(timestamps) - 1

    def check_ip(self, ip: str) -> tuple[bool, RateLimitInfo]:
        """Check rate limit for an IP address."""
        now = time.time()
        timestamps = self._ip_requests[ip]
        timestamps = self._cleanup_old_requests(timestamps, now)

        allowed, remaining = self._check_rate_limit(timestamps, self.requests_per_minute, now)

        if allowed:
            timestamps.append(now)
            self._ip_requests[ip] = timestamps

        reset_time = int(now + self.window_seconds)
        return allowed, RateLimitInfo(
            limit=self.requests_per_minute,
            remaining=max(0, remaining),
            reset=reset_time,
        )

    def check_session(self, session_id: str) -> tuple[bool, RateLimitInfo]:
        """Check rate limit for a session."""
        now = time.time()
        timestamps = self._session_requests[session_id]
        timestamps = self._cleanup_old_requests(timestamps, now)

        allowed, remaining = self._check_rate_limit(timestamps, self.requests_per_session, now)

        if allowed:
            timestamps.append(now)
            self._session_requests[session_id] = timestamps

        reset_time = int(now + self.window_seconds)
        return allowed, RateLimitInfo(
            limit=self.requests_per_session,
            remaining=max(0, remaining),
            reset=reset_time,
        )

    def get_rate_limit_headers(
        self, ip_info: RateLimitInfo, session_info: Optional[RateLimitInfo] = None
    ) -> dict[str, str]:
        """Get rate limit headers for response."""
        headers = {
            "X-RateLimit-Limit": str(ip_info.limit),
            "X-RateLimit-Remaining": str(ip_info.remaining),
            "X-RateLimit-Reset": str(ip_info.reset),
        }

        if session_info:
            headers["X-RateLimit-Session-Limit"] = str(session_info.limit)
            headers["X-RateLimit-Session-Remaining"] = str(session_info.remaining)
            headers["X-RateLimit-Session-Reset"] = str(session_info.reset)

        return headers

    def reset_session(self, session_id: str) -> None:
        """Reset rate limit for a session."""
        if session_id in self._session_requests:
            del self._session_requests[session_id]

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        now = time.time()
        active_ips = sum(
            1 for ts in self._ip_requests.values() if self._cleanup_old_requests(ts.copy(), now)
        )
        active_sessions = sum(
            1
            for ts in self._session_requests.values()
            if self._cleanup_old_requests(ts.copy(), now)
        )
        return {
            "active_ips": active_ips,
            "active_sessions": active_sessions,
            "requests_per_minute": self.requests_per_minute,
            "requests_per_session": self.requests_per_session,
        }


_rate_limiter: Optional[SessionRateLimiter] = None


def get_rate_limiter(
    requests_per_minute: int = 60,
    requests_per_session: int = 100,
    window_seconds: int = 60,
) -> SessionRateLimiter:
    """Get or create the rate limiter."""
    global _rate_limiter

    if _rate_limiter is None:
        _rate_limiter = SessionRateLimiter(
            requests_per_minute=requests_per_minute,
            requests_per_session=requests_per_session,
            window_seconds=window_seconds,
        )

    return _rate_limiter
