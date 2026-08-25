"""Per-IP rate limiting for anonymous (unauthenticated) endpoints.

Phase 2's pre-signup hook is deliberately reachable with no auth gate at
all, per the plan ("No auth gate before API calls") -- which means it's
the one part of the API that's directly exposed to abuse (someone
scripting thousands of resume uploads to burn LLM spend). This is the
control for that, until Cloud Armor (or an equivalent edge WAF) is in
front of this in a real deployment.

Deliberately hand-rolled rather than a dependency like slowapi: this is a
small, single-process, in-memory sliding-window counter -- the same
"simple in-memory dict + lock" pattern api/main.py already uses for its
leads TTL cache and demo-build registry. It resets on process restart and
doesn't share state across multiple API instances -- both acceptable
gaps for a single-instance deployment; graduate to a shared store (Redis)
before running more than one API replica.
"""

import threading
import time
from collections import deque

from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding-window per-key rate limiter: at most `max_requests` calls
    per `window_seconds` for any single key (an IP address, in practice).
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record a hit for `key` and raise HTTPException(429) if it's
        over the limit. Call this once per incoming request, before doing
        any real work.
        """
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())

            # Drop hits outside the current window before counting/appending.
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()

            if len(hits) >= self.max_requests:
                retry_after = self.window_seconds - (now - hits[0])
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded: max {self.max_requests} requests "
                        f"per {int(self.window_seconds)}s. Try again in "
                        f"{max(1, int(retry_after))}s."
                    ),
                )

            hits.append(now)

    def reset(self) -> None:
        """Clear all tracked hits. Used by tests."""
        with self._lock:
            self._hits.clear()


def get_client_ip(request: Request) -> str:
    """Best-effort client IP extraction. Checks X-Forwarded-For first
    (set by a real load balancer/reverse proxy in front of the API in any
    deployed environment -- Cloud Run terminates TLS and forwards through
    one), falling back to the direct connection's address for local dev.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # X-Forwarded-For can be a comma-separated chain (client, proxy1,
        # proxy2, ...) -- the first entry is the original client.
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# Anonymous resume upload: the expensive step (one LLM call to parse).
# Capped tighter than the preview endpoint since it's the entry point an
# abuser would hit first/repeatedly.
resume_upload_limiter = RateLimiter(max_requests=10, window_seconds=3600)

# Anonymous tailored preview: also one LLM call, per job clicked -- same
# per-hour cap, tracked independently so exhausting one doesn't block the other.
preview_limiter = RateLimiter(max_requests=10, window_seconds=3600)
