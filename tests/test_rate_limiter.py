"""Tests for Rate Limiter."""

import time
from unittest.mock import patch

import pytest

from rate_limiter import (
    RateLimitInfo,
    SessionRateLimiter,
    get_rate_limiter,
)


class TestRateLimitInfo:
    """Tests for RateLimitInfo model."""

    def test_creation(self):
        """Test creating RateLimitInfo."""
        info = RateLimitInfo(limit=60, remaining=30, reset=1000)
        assert info.limit == 60
        assert info.remaining == 30
        assert info.reset == 1000


class TestSessionRateLimiterInit:
    """Tests for SessionRateLimiter initialization."""

    def test_default_values(self):
        """Test default initialization values."""
        limiter = SessionRateLimiter()
        assert limiter.requests_per_minute == 60
        assert limiter.requests_per_session == 100
        assert limiter.window_seconds == 60

    def test_custom_values(self):
        """Test initialization with custom values."""
        limiter = SessionRateLimiter(
            requests_per_minute=30,
            requests_per_session=50,
            window_seconds=120,
        )
        assert limiter.requests_per_minute == 30
        assert limiter.requests_per_session == 50
        assert limiter.window_seconds == 120


class TestCleanupOldRequests:
    """Tests for _cleanup_old_requests method."""

    def test_cleanup_removes_old_timestamps(self):
        """Test that old timestamps are removed."""
        limiter = SessionRateLimiter(window_seconds=60)
        now = time.time()
        timestamps = [now - 100, now - 70, now - 10, now]
        cleaned = limiter._cleanup_old_requests(timestamps, now)
        assert len(cleaned) == 2
        assert now in cleaned
        assert now - 10 in cleaned
        assert now - 70 not in cleaned
        assert now - 100 not in cleaned

    def test_cleanup_keeps_all_when_all_fresh(self):
        """Test that all timestamps are kept when all are fresh."""
        limiter = SessionRateLimiter(window_seconds=60)
        now = time.time()
        timestamps = [now - 10, now - 5, now]
        cleaned = limiter._cleanup_old_requests(timestamps, now)
        assert len(cleaned) == 3


class TestCheckRateLimit:
    """Tests for _check_rate_limit method."""

    def test_under_limit(self):
        """Test request under limit is allowed."""
        limiter = SessionRateLimiter(requests_per_minute=10)
        allowed, remaining = limiter._check_rate_limit([], 10, time.time())
        assert allowed is True
        assert remaining == 9

    def test_at_limit(self):
        """Test request at limit is denied."""
        limiter = SessionRateLimiter(requests_per_minute=2)
        timestamps = [time.time() - 1, time.time() - 0.5]
        allowed, remaining = limiter._check_rate_limit(timestamps, 2, time.time())
        assert allowed is False
        assert remaining == 0

    def test_over_limit(self):
        """Test request over limit is denied."""
        limiter = SessionRateLimiter(requests_per_minute=2)
        timestamps = [time.time(), time.time()]
        allowed, remaining = limiter._check_rate_limit(timestamps, 2, time.time())
        assert allowed is False


class TestCheckIP:
    """Tests for check_ip method."""

    def test_first_request_allowed(self):
        """Test first request from IP is allowed."""
        limiter = SessionRateLimiter(requests_per_minute=60)
        allowed, info = limiter.check_ip("192.168.1.1")
        assert allowed is True
        assert info.limit == 60
        assert info.remaining >= 0

    def test_subsequent_requests_allowed(self):
        """Test subsequent requests are allowed under limit."""
        limiter = SessionRateLimiter(requests_per_minute=5)
        for _ in range(4):
            allowed, _ = limiter.check_ip("192.168.1.1")
            assert allowed is True

    def test_request_at_limit(self):
        """Test request at IP limit is denied."""
        limiter = SessionRateLimiter(requests_per_minute=2)
        limiter.check_ip("192.168.1.1")
        limiter.check_ip("192.168.1.1")
        allowed, info = limiter.check_ip("192.168.1.1")
        assert allowed is False
        assert info.remaining == 0

    def test_different_ips_independent(self):
        """Test different IPs have independent limits."""
        limiter = SessionRateLimiter(requests_per_minute=2)
        limiter.check_ip("192.168.1.1")
        limiter.check_ip("192.168.1.1")
        allowed, _ = limiter.check_ip("192.168.1.2")
        assert allowed is True


class TestCheckSession:
    """Tests for check_session method."""

    def test_first_session_request_allowed(self):
        """Test first request for session is allowed."""
        limiter = SessionRateLimiter(requests_per_session=100)
        allowed, info = limiter.check_session("session123")
        assert allowed is True
        assert info.limit == 100

    def test_session_at_limit(self):
        """Test session at limit is denied."""
        limiter = SessionRateLimiter(requests_per_session=2)
        limiter.check_session("session123")
        limiter.check_session("session123")
        allowed, info = limiter.check_session("session123")
        assert allowed is False

    def test_different_sessions_independent(self):
        """Test different sessions have independent limits."""
        limiter = SessionRateLimiter(requests_per_session=2)
        limiter.check_session("session1")
        limiter.check_session("session1")
        allowed, _ = limiter.check_session("session2")
        assert allowed is True


class TestGetRateLimitHeaders:
    """Tests for get_rate_limit_headers method."""

    def test_ip_only_headers(self):
        """Test headers with only IP info."""
        limiter = SessionRateLimiter()
        ip_info = RateLimitInfo(limit=60, remaining=30, reset=1000)
        headers = limiter.get_rate_limit_headers(ip_info)
        assert "X-RateLimit-Limit" in headers
        assert headers["X-RateLimit-Limit"] == "60"
        assert headers["X-RateLimit-Remaining"] == "30"
        assert headers["X-RateLimit-Reset"] == "1000"

    def test_session_headers_included(self):
        """Test headers include session info when provided."""
        limiter = SessionRateLimiter()
        ip_info = RateLimitInfo(limit=60, remaining=30, reset=1000)
        session_info = RateLimitInfo(limit=100, remaining=80, reset=1000)
        headers = limiter.get_rate_limit_headers(ip_info, session_info)
        assert "X-RateLimit-Session-Limit" in headers
        assert headers["X-RateLimit-Session-Limit"] == "100"
        assert headers["X-RateLimit-Session-Remaining"] == "80"


class TestResetSession:
    """Tests for reset_session method."""

    def test_reset_clears_session(self):
        """Test that reset clears session requests."""
        limiter = SessionRateLimiter(requests_per_session=2)
        limiter.check_session("session123")
        limiter.check_session("session123")
        limiter.reset_session("session123")
        allowed, _ = limiter.check_session("session123")
        assert allowed is True

    def test_reset_nonexistent_session(self):
        """Test resetting nonexistent session doesn't error."""
        limiter = SessionRateLimiter()
        limiter.reset_session("nonexistent")
        allowed, _ = limiter.check_session("nonexistent")
        assert allowed is True


class TestGetStats:
    """Tests for get_stats method."""

    def test_initial_stats(self):
        """Test stats when no requests made."""
        limiter = SessionRateLimiter(requests_per_minute=30, requests_per_session=50)
        stats = limiter.get_stats()
        assert stats["active_ips"] == 0
        assert stats["active_sessions"] == 0
        assert stats["requests_per_minute"] == 30
        assert stats["requests_per_session"] == 50

    def test_stats_with_active_requests(self):
        """Test stats with active requests."""
        limiter = SessionRateLimiter()
        limiter.check_ip("192.168.1.1")
        limiter.check_ip("192.168.1.2")
        limiter.check_session("session1")
        stats = limiter.get_stats()
        assert stats["active_ips"] == 2
        assert stats["active_sessions"] == 1


class TestGetRateLimiter:
    """Tests for get_rate_limiter factory."""

    def test_creates_instance(self):
        """Test that factory creates instance."""
        from rate_limiter import _rate_limiter

        original = _rate_limiter
        import rate_limiter

        rate_limiter._rate_limiter = None
        try:
            limiter = get_rate_limiter(requests_per_minute=30)
            assert isinstance(limiter, SessionRateLimiter)
            assert limiter.requests_per_minute == 30
        finally:
            rate_limiter._rate_limiter = original

    def test_reuses_instance(self):
        """Test that factory reuses existing instance."""
        import rate_limiter
        from rate_limiter import _rate_limiter

        original = _rate_limiter
        rate_limiter._rate_limiter = None
        try:
            limiter1 = get_rate_limiter()
            limiter2 = get_rate_limiter()
            assert limiter1 is limiter2
        finally:
            rate_limiter._rate_limiter = original


class TestIntegration:
    """Integration tests for rate limiter."""

    def test_ip_and_session_limits_independent(self):
        """Test IP and session limits work independently."""
        limiter = SessionRateLimiter(requests_per_minute=2, requests_per_session=2)

        limiter.check_ip("192.168.1.1")
        limiter.check_ip("192.168.1.1")

        ip_allowed, _ = limiter.check_ip("192.168.1.1")
        assert ip_allowed is False

        session_allowed, _ = limiter.check_session("session1")
        assert session_allowed is True

    def test_rate_limit_window_expires(self):
        """Test that rate limit window expires."""
        limiter = SessionRateLimiter(requests_per_minute=2, window_seconds=1)

        limiter.check_ip("192.168.1.1")
        limiter.check_ip("192.168.1.1")

        allowed, _ = limiter.check_ip("192.168.1.1")
        assert allowed is False

        time.sleep(1.1)

        allowed, _ = limiter.check_ip("192.168.1.1")
        assert allowed is True

    def test_full_workflow(self):
        """Test complete rate limiting workflow."""
        limiter = SessionRateLimiter(requests_per_minute=5, requests_per_session=10)

        ip_allowed, ip_info = limiter.check_ip("10.0.0.1")
        assert ip_allowed is True

        session_allowed, session_info = limiter.check_session("user-session")
        assert session_allowed is True

        headers = limiter.get_rate_limit_headers(ip_info, session_info)
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Session-Limit" in headers

        stats = limiter.get_stats()
        assert stats["active_ips"] == 1
        assert stats["active_sessions"] == 1
