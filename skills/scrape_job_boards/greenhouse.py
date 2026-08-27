"""Greenhouse job board connector -- populates the shared catalog (companies/jobs).

Unlike the other scrapers in this package (arbeitnow.py, jobicy.py, etc.),
this connector does NOT write per-user leads. It populates
db.models.Company/Job, the shared, non-tenant-scoped catalog every user's
matched-jobs feed is built from later. Greenhouse's public Job Board API
needs no auth and returns every published job for a company in one call
(no pagination) as plain JSON.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Docs: https://developers.greenhouse.io/job-board

token is the slug in a company's public careers URL, e.g. for
job-boards.greenhouse.io/stripe the token is "stripe".

Usage:
    python -m skills.scrape_job_boards.greenhouse [token ...]

With no arguments, syncs every token listed in ats_tokens.json's
"greenhouse" list.
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup  # type: ignore

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from db import repository as repo
from skills.scrape_job_boards.ats_common import prioritize_tokens, run_concurrent

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "ats_tokens.json")

# ats_tokens.json (imported from kalil0321/ats-scrapers, an open dataset --
# see import_ats_tokens.py) holds thousands of tokens. Syncing all of them
# unbounded on every run would take hours and risk provider rate limits,
# so a scheduled/default run caps itself and relies on prioritize_tokens()
# (never-synced first, then stalest) to make steady progress across the
# whole seed list over repeated runs. Pass tokens explicitly (e.g. via the
# CLI) to bypass this cap for a specific company.
DEFAULT_RUN_LIMIT = 200


def _load_seed_tokens() -> list[str]:
    if not os.path.exists(TOKENS_PATH):
        return []
    with open(TOKENS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("greenhouse", [])


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _parse_posted_at(value: str | None) -> datetime | None:
    """Greenhouse timestamps are ISO 8601 with a numeric UTC offset, e.g.
    '2026-08-24T13:52:04-04:00'. datetime.fromisoformat handles that
    natively in Python 3.11+; guard anyway since a malformed/missing
    timestamp should never crash the whole sync."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fetch_jobs(token: str) -> tuple[list[dict] | None, str | None]:
    """Fetch every published job for one company's Greenhouse board.

    Returns (jobs, error). jobs is None if the board doesn't exist (404,
    a dead/mistyped token) or the response wasn't valid JSON -- both are
    routine, expected outcomes for a seed list that will inevitably
    contain a stale token eventually, not something worth crashing the
    whole sync over.
    """
    url = BASE_URL.format(token=token)
    try:
        response = requests.get(url, params={"content": "true"}, timeout=30)
    except requests.exceptions.RequestException as e:
        return None, f"request failed: {e}"

    if response.status_code == 404:
        return None, "board not found (404) -- token likely stale or mistyped"
    if response.status_code != 200:
        return None, f"unexpected status {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return None, "response was not valid JSON"

    jobs = payload.get("jobs")
    if jobs is None:
        return None, "response JSON had no 'jobs' key"

    return jobs, None


def _department_name(job: dict) -> str | None:
    departments = job.get("departments") or []
    return departments[0].get("name") if departments else None


def _location_name(job: dict) -> str | None:
    location = job.get("location") or {}
    return location.get("name")


def sync_company(token: str) -> dict:
    """Sync one company's Greenhouse board into the shared catalog.

    Returns a summary dict: {token, status, added, skipped, error}.
    status is one of "ok", "not_found", "error".
    """
    jobs, error = fetch_jobs(token)

    if error is not None:
        status = "not_found" if "404" in error or "not found" in error else "error"
        print(f"  ⚠️  greenhouse:{token} -- {error}")
        return {"token": token, "status": status, "added": 0, "skipped": 0, "error": error}

    if not jobs:
        print(f"  ⏭️  greenhouse:{token} -- board exists but has 0 published jobs")

    # company_name is normally present on every job in a non-empty board,
    # but don't assume jobs[0] specifically has it -- a malformed first
    # entry (missing fields) shouldn't break company creation for an
    # otherwise-fine board. Scan for the first job that actually has a
    # name; fall back to a titleized token if none do (or the board is empty).
    company_name = next(
        (job.get("company_name") for job in jobs if job.get("company_name")),
        None,
    ) or token.replace("-", " ").title()
    company = repo.get_or_create_company(
        name=company_name, ats_type="greenhouse", ats_token=token
    )

    added = 0
    skipped = 0
    seen_external_ids = set()

    for job in jobs:
        external_id = str(job.get("id") or "")
        title = job.get("title") or ""
        if not external_id or not title:
            print(f"  ⚠️  greenhouse:{token} -- skipping malformed job entry (missing id/title): {job}")
            skipped += 1
            continue

        seen_external_ids.add(external_id)

        result = repo.add_job(
            company["id"],
            source="greenhouse",
            external_id=external_id,
            title=title,
            location=_location_name(job),
            department=_department_name(job),
            jd_text=_strip_html(job.get("content") or ""),
            apply_url=job.get("absolute_url"),
            posted_at=_parse_posted_at(job.get("first_published")),
        )
        if result is not None:
            added += 1
        else:
            skipped += 1  # already in the catalog from a previous sync

    # This response is the company's full current set of open postings --
    # anything previously catalogued for this company but absent here has
    # been filled or pulled. Only run this when the fetch actually
    # succeeded with a real (possibly empty) jobs list, never on a
    # malformed/missing entry -- a partial parse failure must never look
    # like "this company has zero open jobs now."
    closed = repo.close_unseen_jobs(company["id"], seen_external_ids)

    repo.mark_company_scraped(company["id"])

    print(
        f"  ✅ greenhouse:{token} ({company_name}) -- {added} new, {skipped} already known"
        + (f", {closed} closed" if closed else "")
    )
    return {"token": token, "status": "ok", "added": added, "skipped": skipped, "error": None}


def run(tokens: list[str] | None = None, limit: int | None = None, max_workers: int = 8) -> dict:
    """Sync Greenhouse tokens into the catalog.

    Each company is synced independently -- one bad/stale token never stops
    the rest of the batch, per the project's "log loudly, never silently
    skip" rule (a failure is printed and counted, never swallowed).

    Args:
        tokens: explicit tokens to sync. If None, uses every seed-listed
            token, prioritized (never-synced first, then stalest) and
            capped at `limit`.
        limit: max tokens to sync this run when tokens is None. Defaults
            to DEFAULT_RUN_LIMIT. Pass None explicitly (with tokens=None)
            for an uncapped run across the entire seed list -- expect
            this to take a while with thousands of tokens.
        max_workers: concurrent HTTP fetches (each still writes to
            Postgres via its own session -- see ats_common.run_concurrent).
    """
    if tokens is None:
        seed_tokens = _load_seed_tokens()
        known = repo.get_companies_by_ats_type("greenhouse")
        effective_limit = DEFAULT_RUN_LIMIT if limit is None else limit
        tokens = prioritize_tokens(seed_tokens, known, effective_limit)
    else:
        # Explicit tokens (e.g. from the CLI) always run in full, uncapped.
        pass

    print(f"\n{'=' * 60}")
    print("Greenhouse Catalog Sync")
    print(f"{'=' * 60}")
    print(f"Tokens to sync: {len(tokens)}")

    results = run_concurrent(tokens, sync_company, max_workers=max_workers)

    ok = sum(1 for r in results if r["status"] == "ok")
    not_found = sum(1 for r in results if r["status"] == "not_found")
    errored = sum(1 for r in results if r["status"] == "error")
    total_added = sum(r["added"] for r in results)

    print(f"\n{'=' * 60}")
    print(f"Greenhouse: {ok} boards synced, {not_found} not found, {errored} errored, "
          f"{total_added} new jobs added")
    print(f"{'=' * 60}\n")

    return {"provider": "greenhouse", "results": results, "total_added": total_added}


if __name__ == "__main__":
    cli_tokens = sys.argv[1:] or None
    run(cli_tokens)
