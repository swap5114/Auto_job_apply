"""Matches catalog jobs (db.repository.get_jobs -- the shared, no-LLM-cost
Greenhouse/Lever/Ashby/YC catalog from Phase 1) against inferred search
criteria (skills/infer_criteria.py's output), for the anonymous
pre-signup feed.

Deliberately NOT the same matching logic as skills/relevance_filter.py:
that module requires BOTH a role keyword AND a tech-stack keyword to
match (a strict AND, tuned for a long-running scrape pipeline that can
afford to be picky since it runs continuously). Inferred criteria from a
single resume can easily have an empty role_keywords list (e.g. a
new-grad resume with no prior job titles, or a projects-only resume) --
a strict AND would zero out the anonymous feed for exactly the visitors
this hook is meant to hook. Matching here is scored, not a hard filter:
a job needs at least one tech-stack OR role signal to appear at all, and
results are ranked by how many signals matched, most-relevant first.

No LLM call anywhere in this module -- pure Python + the jobs already in
Postgres from Phase 1's catalog sync. This is what lets the feed render
within the 30-second budget without waiting on anything beyond the one
resume-parse LLM call upstream.
"""

import re


def _contains_keyword(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, text) is not None


_SENIOR_EXCLUDE_SIGNALS = [
    "senior", "sr.", "lead", "principal", "staff", "manager", "director",
    "head of", "vp", "chief",
]


def _job_text(job: dict) -> str:
    return f"{job.get('title') or ''} {job.get('jd_text') or ''}".lower()


def score_job(job: dict, criteria: dict) -> int:
    """Number of matched signals (tech-stack keywords + role keywords)
    for one job against one criteria set. 0 means no match at all.
    """
    text = _job_text(job)

    tech_matches = sum(
        1 for kw in criteria.get("tech_stack", []) if _contains_keyword(text, kw)
    )
    role_matches = sum(
        1 for kw in criteria.get("roles", []) if _contains_keyword(text, kw)
    )

    return tech_matches + role_matches


def matched_signals(job: dict, criteria: dict) -> list[str]:
    """The actual tech-stack/role keywords (original casing, as given in
    criteria -- not lowercased) that matched for this one job. Mirrors
    score_job's exact matching logic (same _contains_keyword whole-word
    check) so a caller can show *why* a job matched -- e.g. a "Python,
    FastAPI" chip row on a matched-jobs card -- without the two functions
    ever silently drifting apart on what counts as a match.
    """
    text = _job_text(job)
    matches = [kw for kw in criteria.get("tech_stack", []) if _contains_keyword(text, kw)]
    matches += [kw for kw in criteria.get("roles", []) if _contains_keyword(text, kw)]
    return matches


def _is_seniority_mismatch(job: dict, criteria: dict) -> bool:
    """An entry_to_mid candidate's feed shouldn't be dominated by
    Staff/Principal/Director postings -- exclude them. A 'senior'-inferred
    candidate has no such exclusion (they may still be open to a title
    that doesn't say "senior" but is otherwise senior-level work)."""
    if criteria.get("seniority") != "entry_to_mid":
        return False

    title = (job.get("title") or "").lower()
    return any(_contains_keyword(title, signal) for signal in _SENIOR_EXCLUDE_SIGNALS)


def match_jobs(jobs: list[dict], criteria: dict, limit: int = 50) -> list[dict]:
    """Score and rank jobs against criteria, returning at most `limit`
    matches sorted by relevance (highest score first, ties broken by most
    recently posted).

    A job with score 0 (no tech or role signal matched at all) is
    excluded -- this is the only hard filter; everything else is ranking.
    """
    scored = []
    for job in jobs:
        if _is_seniority_mismatch(job, criteria):
            continue

        score = score_job(job, criteria)
        if score == 0:
            continue

        scored.append((score, job))

    def sort_key(item: tuple[int, dict]):
        score, job = item
        posted_at = job.get("posted_at")
        # None posted_at sorts last within a score tier -- a job with a
        # known posting date is preferred over one with unknown recency
        # when relevance is otherwise tied.
        return (-score, posted_at is None, -(posted_at.timestamp() if posted_at else 0))

    scored.sort(key=sort_key)
    return [job for _, job in scored[:limit]]
