"""Tests for skills/scrape_job_boards/ats_common.py -- token prioritization
(never-synced first, then stalest) and bounded-concurrency batch execution.
These are what make syncing thousands of seed tokens (see
import_ats_tokens.py) practical instead of a multi-hour sequential run
that always favors the same alphabetically-first companies.
"""

from datetime import datetime, timedelta, timezone

from skills.scrape_job_boards.ats_common import prioritize_tokens, run_concurrent


def _company(token: str, last_scraped_at=None) -> dict:
    return {"ats_token": token, "last_scraped_at": last_scraped_at}


def test_prioritize_never_synced_before_synced():
    seed = ["a", "b", "c"]
    known = [_company("b", last_scraped_at=datetime.now(timezone.utc))]

    ordered = prioritize_tokens(seed, known, limit=None)

    # a and c have never been synced (no matching row) -- both must sort
    # before b, which has a real last_scraped_at.
    assert ordered.index("b") == 2
    assert set(ordered[:2]) == {"a", "c"}


def test_prioritize_synced_tokens_stalest_first():
    now = datetime.now(timezone.utc)
    seed = ["fresh", "stale", "stalest"]
    known = [
        _company("fresh", last_scraped_at=now),
        _company("stale", last_scraped_at=now - timedelta(days=1)),
        _company("stalest", last_scraped_at=now - timedelta(days=7)),
    ]

    ordered = prioritize_tokens(seed, known, limit=None)

    assert ordered == ["stalest", "stale", "fresh"]


def test_prioritize_respects_limit():
    seed = [f"token-{i}" for i in range(10)]
    ordered = prioritize_tokens(seed, known_companies=[], limit=3)
    assert len(ordered) == 3


def test_prioritize_no_limit_returns_everything():
    seed = [f"token-{i}" for i in range(10)]
    ordered = prioritize_tokens(seed, known_companies=[], limit=None)
    assert len(ordered) == 10
    assert set(ordered) == set(seed)


def test_run_concurrent_preserves_input_order_regardless_of_completion_order():
    import time

    def sync_one(token: str) -> dict:
        # Deliberately vary "work" duration so completion order differs
        # from input order -- results must still come back input-ordered.
        delay = {"slow": 0.05, "fast": 0.0, "medium": 0.02}.get(token, 0.0)
        time.sleep(delay)
        return {"token": token, "status": "ok", "added": 1, "skipped": 0, "error": None}

    tokens = ["slow", "fast", "medium"]
    results = run_concurrent(tokens, sync_one, max_workers=3)

    assert [r["token"] for r in results] == tokens


def test_run_concurrent_isolates_one_tokens_unexpected_exception():
    """A sync_one call that raises (rather than returning a status="error"
    dict, which is the documented contract) must not crash the whole
    batch or corrupt other tokens' results -- it's caught and reported."""
    def sync_one(token: str) -> dict:
        if token == "boom":
            raise RuntimeError("unexpected DB failure")
        return {"token": token, "status": "ok", "added": 1, "skipped": 0, "error": None}

    tokens = ["fine-1", "boom", "fine-2"]
    results = run_concurrent(tokens, sync_one, max_workers=3)

    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert "unexpected" in results[1]["error"]
    assert results[2]["status"] == "ok"
