"""Ashby job board connector -- populates the shared catalog (companies/jobs).

Same role as greenhouse.py/lever.py: writes to the shared, non-tenant-scoped
companies/jobs catalog, not per-user leads. Ashby's public Job Postings API
needs no auth and returns every currently-listed job posting for a company
in one JSON response (no pagination -- this endpoint returns the full set
of published postings per the official docs).

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}
Docs: https://developers.ashbyhq.com/docs/public-job-posting-api

JOB_BOARD_NAME (called "token" here for consistency with the other two
connectors) is the final path segment of a company's hosted job board URL,
e.g. for jobs.ashbyhq.com/render the token is "render". Note this segment
is case-sensitive in Ashby's own examples (jobs.ashbyhq.com/Ashby uses
"Ashby", not "ashby") -- pass tokens exactly as they appear in the URL.

Usage:
    python -m skills.scrape_job_boards.ashby [token ...]

With no arguments, syncs every token listed in ats_tokens.json's
"ashby" list.
"""

import json
import os
import sys
from datetime import datetime

import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from db import repository as repo
from skills.scrape_job_boards.ats_common import prioritize_tokens, run_concurrent

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "ats_tokens.json")

# See greenhouse.py's DEFAULT_RUN_LIMIT comment -- same rationale applies here.
DEFAULT_RUN_LIMIT = 200


def _load_seed_tokens() -> list[str]:
    if not os.path.exists(TOKENS_PATH):
        return []
    with open(TOKENS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("ashby", [])


def _parse_published_at(value: str | None) -> datetime | None:
    """Ashby's publishedAt is ISO 8601 with milliseconds and a numeric UTC
    offset, e.g. '2021-04-30T16:21:55.393+00:00' -- fromisoformat handles
    this natively. Missing/malformed values never crash the sync."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fetch_jobs(token: str) -> tuple[list[dict] | None, str | None]:
    """Fetch every listed job posting for one company's Ashby board.

    Returns (jobs, error). jobs is None if the board doesn't exist (404,
    a dead/mistyped token) or the response wasn't valid JSON.
    """
    url = BASE_URL.format(token=token)
    try:
        response = requests.get(url, timeout=30)
    except requests.exceptions.RequestException as e:
        return None, f"request failed: {e}"

    if response.status_code == 404:
        return None, "job board not found (404) -- token likely stale, mistyped, or wrong case"
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


def sync_company(token: str) -> dict:
    """Sync one company's Ashby board into the shared catalog.

    Returns a summary dict: {token, status, added, skipped, error}.
    """
    jobs, error = fetch_jobs(token)

    if error is not None:
        status = "not_found" if "404" in error or "not found" in error else "error"
        print(f"  ⚠️  ashby:{token} -- {error}")
        return {"token": token, "status": status, "added": 0, "skipped": 0, "error": error}

    # isListed=False jobs are only reachable via direct link, not meant to
    # be surfaced in a general feed -- filter them out, same as Ashby's own
    # careers-page guidance for building a public job board.
    listed_jobs = [job for job in jobs if job.get("isListed", True)]

    if not listed_jobs:
        print(f"  ⏭️  ashby:{token} -- board exists but has 0 publicly listed jobs")

    # Ashby's posting-api response carries no company-name field -- the
    # token itself (titleized) is the only name signal available here.
    company_name = token.replace("-", " ").replace("_", " ").title()
    company = repo.get_or_create_company(
        name=company_name, ats_type="ashby", ats_token=token
    )

    added = 0
    skipped = 0

    for job in listed_jobs:
        external_id = job.get("id") or ""
        title = job.get("title") or ""
        if not external_id or not title:
            print(f"  ⚠️  ashby:{token} -- skipping malformed posting (missing id/title): {job}")
            skipped += 1
            continue

        result = repo.add_job(
            company["id"],
            source="ashby",
            external_id=external_id,
            title=title,
            location=job.get("location"),
            department=job.get("department") or job.get("team"),
            jd_text=job.get("descriptionPlain") or "",
            apply_url=job.get("jobUrl") or job.get("applyUrl"),
            posted_at=_parse_published_at(job.get("publishedAt")),
        )
        if result is not None:
            added += 1
        else:
            skipped += 1

    repo.mark_company_scraped(company["id"])

    print(f"  ✅ ashby:{token} ({company_name}) -- {added} new, {skipped} already known")
    return {"token": token, "status": "ok", "added": added, "skipped": skipped, "error": None}


def run(tokens: list[str] | None = None, limit: int | None = None, max_workers: int = 8) -> dict:
    """Sync Ashby tokens into the catalog. See greenhouse.run()'s
    docstring for the tokens/limit/max_workers contract -- identical here.
    """
    if tokens is None:
        seed_tokens = _load_seed_tokens()
        known = repo.get_companies_by_ats_type("ashby")
        effective_limit = DEFAULT_RUN_LIMIT if limit is None else limit
        tokens = prioritize_tokens(seed_tokens, known, effective_limit)

    print(f"\n{'=' * 60}")
    print("Ashby Catalog Sync")
    print(f"{'=' * 60}")
    print(f"Tokens to sync: {len(tokens)}")

    results = run_concurrent(tokens, sync_company, max_workers=max_workers)

    ok = sum(1 for r in results if r["status"] == "ok")
    not_found = sum(1 for r in results if r["status"] == "not_found")
    errored = sum(1 for r in results if r["status"] == "error")
    total_added = sum(r["added"] for r in results)

    print(f"\n{'=' * 60}")
    print(f"Ashby: {ok} boards synced, {not_found} not found, {errored} errored, "
          f"{total_added} new jobs added")
    print(f"{'=' * 60}\n")

    return {"provider": "ashby", "results": results, "total_added": total_added}


if __name__ == "__main__":
    cli_tokens = sys.argv[1:] or None
    run(cli_tokens)
