"""Tests for api/rate_limit.py -- the per-IP sliding-window limiter
protecting the anonymous (no-auth) endpoints."""

import time

import pytest
from fastapi import HTTPException

from api.rate_limit import RateLimiter


def test_allows_requests_under_the_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.check("1.2.3.4")  # must not raise


def test_blocks_the_request_over_the_limit():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")
    assert exc_info.value.status_code == 429


def test_different_keys_tracked_independently():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("1.1.1.1")  # uses up 1.1.1.1's quota
    limiter.check("2.2.2.2")  # a different IP must not be affected


def test_window_expiry_allows_new_requests():
    limiter = RateLimiter(max_requests=1, window_seconds=0.05)
    limiter.check("1.2.3.4")
    with pytest.raises(HTTPException):
        limiter.check("1.2.3.4")

    time.sleep(0.1)  # let the window pass
    limiter.check("1.2.3.4")  # must not raise now


def test_reset_clears_all_tracked_hits():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.reset()
    limiter.check("1.2.3.4")  # must not raise -- reset cleared it
