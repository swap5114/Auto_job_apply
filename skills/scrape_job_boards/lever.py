"""Lever job board connector -- populates the shared catalog (companies/jobs).

Same role as greenhouse.py: writes to the shared, non-tenant-scoped
companies/jobs catalog, not per-user leads. Lever's public Postings API
needs no auth and returns every published posting for a company in one
JSON array (no pagination for a single request, though very large boards
can be paged with skip/limit -- not needed for the catalog sizes here).

Endpoint: https://api.lever.co/v0/postings/{token}?mode=json
Docs: https://github.com/lever/postings-api

token is the site name in a company's hosted job site URL, e.g. for
jobs.lever.co/spotify the token is "spotify". Note that a company with NO
open postings returns 200 with an empty JSON array `[]`, not a 404 -- only
a genuinely unknown/mistyped token 404s.

Usage:
    python -m skills.scrape_job_boards.lever [token ...]

With no arguments, syncs every token listed in ats_tokens.json's "lever" list.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from db import repository as repo
from skills.scrape_job_boards.ats_common import prioritize_tokens, run_concurrent

BASE_URL = "https://api.lever.co/v0/postings/{token}"
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "ats_tokens.json")

# See greenhouse.py's DEFAULT_RUN_LIMIT comment -- same rationale applies here.
DEFAULT_RUN_LIMIT = 200


def _load_seed_tokens() -> list[str]:
    if not os.path.exists(TOKENS_PATH):
        return []
    with open(TOKENS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lever", [])


def _parse_created_at(value) -> datetime | None:
    """Lever's createdAt is a Unix epoch in MILLISECONDS (e.g. 1553186035299),
    not seconds -- dividing by 1000 is required or every date lands in
    the far future. Missing/malformed values never crash the sync."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_jobs(token: str) -> tuple[list[dict] | None, str | None]:
    """Fetch every published posting for one company's Lever site.

    Returns (jobs, error). jobs is None only on a genuine fetch/parse
    failure -- an empty, valid `[]` response (a real board with zero open
    postings right now) returns ([], None), not an error.
    """
    url = BASE_URL.format(token=token)
    try:
        response = requests.get(url, params={"mode": "json"}, timeout=30)
    except requests.exceptions.RequestException as e:
        return None, f"request failed: {e}"

    if response.status_code == 404:
        return None, "site not found (404) -- token likely stale or mistyped"
    if response.status_code != 200:
        return None, f"unexpected status {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return None, "response was not valid JSON"

    if not isinstance(payload, list):
        return None, "response JSON was not a list of postings"

    return payload, None


def _department(job: dict) -> str | None:
    categories = job.get("categories") or {}
    return categories.get("department") or categories.get("team")


def _location(job: dict) -> str | None:
    categories = job.get("categories") or {}
    return categories.get("location")


def sync_company(token: str) -> dict:
    """Sync one company's Lever board into the shared catalog.

    Returns a summary dict: {token, status, added, skipped, error}.
    """
    jobs, error = fetch_jobs(token)

    if error is not None:
        status = "not_found" if "404" in error or "not found" in error else "error"
        print(f"  ⚠️  lever:{token} -- {error}")
        return {"token": token, "status": status, "added": 0, "skipped": 0, "error": error}

    if not jobs:
        print(f"  ⏭️  lever:{token} -- site exists but has 0 open postings")

    # Lever's postings carry no company-name field -- the token itself
    # (titleized) is the only name signal available from this API.
    company_name = token.replace("-", " ").title()
    company = repo.get_or_create_company(
        name=company_name, ats_type="lever", ats_token=token
    )

    added = 0
    skipped = 0
    seen_external_ids = set()

    for job in jobs:
        external_id = job.get("id") or ""
        title = job.get("text") or ""
        if not external_id or not title:
            print(f"  ⚠️  lever:{token} -- skipping malformed posting (missing id/text): {job}")
            skipped += 1
            continue

        seen_external_ids.add(external_id)

        result = repo.add_job(
            company["id"],
            source="lever",
            external_id=external_id,
            title=title,
            location=_location(job),
            department=_department(job),
            jd_text=job.get("descriptionPlain") or job.get("description") or "",
            apply_url=job.get("hostedUrl") or job.get("applyUrl"),
            posted_at=_parse_created_at(job.get("createdAt")),
        )
        if result is not None:
            added += 1
        else:
            skipped += 1

    # See greenhouse.py's sync_company for why this runs even when jobs is
    # an empty list (a real "0 open postings right now" response) but
    # never on a fetch/parse failure.
    closed = repo.close_unseen_jobs(company["id"], seen_external_ids)

    repo.mark_company_scraped(company["id"])

    print(
        f"  ✅ lever:{token} ({company_name}) -- {added} new, {skipped} already known"
        + (f", {closed} closed" if closed else "")
    )
    return {"token": token, "status": "ok", "added": added, "skipped": skipped, "error": None}


def run(tokens: list[str] | None = None, limit: int | None = None, max_workers: int = 8) -> dict:
    """Sync Lever tokens into the catalog. See greenhouse.run()'s
    docstring for the tokens/limit/max_workers contract -- identical here.
    """
    if tokens is None:
        seed_tokens = _load_seed_tokens()
        known = repo.get_companies_by_ats_type("lever")
        effective_limit = DEFAULT_RUN_LIMIT if limit is None else limit
        tokens = prioritize_tokens(seed_tokens, known, effective_limit)

    print(f"\n{'=' * 60}")
    print("Lever Catalog Sync")
    print(f"{'=' * 60}")
    print(f"Tokens to sync: {len(tokens)}")

    results = run_concurrent(tokens, sync_company, max_workers=max_workers)

    ok = sum(1 for r in results if r["status"] == "ok")
    not_found = sum(1 for r in results if r["status"] == "not_found")
    errored = sum(1 for r in results if r["status"] == "error")
    total_added = sum(r["added"] for r in results)

    print(f"\n{'=' * 60}")
    print(f"Lever: {ok} boards synced, {not_found} not found, {errored} errored, "
          f"{total_added} new jobs added")
    print(f"{'=' * 60}\n")

    return {"provider": "lever", "results": results, "total_added": total_added}


if __name__ == "__main__":
    cli_tokens = sys.argv[1:] or None
    run(cli_tokens)
