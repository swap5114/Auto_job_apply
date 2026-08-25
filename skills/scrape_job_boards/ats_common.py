"""Shared helpers for the ATS catalog connectors (greenhouse.py, lever.py,
ashby.py). With thousands of seed tokens per provider (see
ats_tokens.json / import_ats_tokens.py), syncing them one at a time,
unprioritized, on every run is impractical: it would take hours per
provider and always hit the same alphabetically-first companies before
ever reaching the rest of the list.

This module solves both problems:
  - prioritize_tokens(): never-synced tokens first, then stalest-synced,
    so a capped run makes steady progress across the whole seed list
    over repeated scheduled runs instead of stalling at the front.
  - run_concurrent(): bounded-concurrency HTTP fetch + sequential DB
    write, so a provider with 6,000 tokens finishes in minutes instead
    of hours without overwhelming either the ATS's API or the local
    Postgres connection pool.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed


def prioritize_tokens(seed_tokens: list[str], known_companies: list[dict], limit: int | None) -> list[str]:
    """Order seed_tokens so a capped run covers the whole seed list over
    repeated calls, then truncate to `limit` (None = no cap).

    known_companies is the catalog's current rows for this ATS provider
    (from db.repository.get_companies_by_ats_type) -- used to look up
    each token's last_scraped_at by matching on ats_token.
    """
    last_scraped_by_token = {
        c["ats_token"]: c["last_scraped_at"]
        for c in known_companies
        if c.get("ats_token")
    }

    def sort_key(token: str):
        last_scraped = last_scraped_by_token.get(token)
        # Never-synced tokens (no row yet, or a row with last_scraped_at
        # still None) sort first via the False < True on has_been_scraped.
        # Among synced tokens, the least-recently-scraped sorts first.
        has_been_scraped = last_scraped is not None
        return (has_been_scraped, last_scraped)

    ordered = sorted(seed_tokens, key=sort_key)
    return ordered[:limit] if limit is not None else ordered


def run_concurrent(tokens: list[str], sync_one, max_workers: int = 8) -> list[dict]:
    """Fetch+sync each token with bounded thread concurrency.

    sync_one(token) -> dict is the per-provider sync_company function.
    Each call does its own HTTP fetch AND its own DB write (via
    db.repository, which opens its own session per call) -- SQLAlchemy
    sessions aren't shared across threads here, each sync_one call gets
    its own via db.session.get_session()'s context manager, so this is
    safe under concurrent execution.

    Returns results in the same order as `tokens`, regardless of
    completion order, so callers' per-token bookkeeping stays predictable.
    """
    results: list[dict | None] = [None] * len(tokens)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(sync_one, token): i for i, token in enumerate(tokens)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                # sync_one implementations already catch their own
                # request/parsing errors and return a status="error"
                # dict -- reaching here means something unexpected (e.g.
                # a DB error) escaped that handling. Report it loudly
                # rather than letting one token's crash kill the whole
                # concurrent batch silently.
                token = tokens[index]
                print(f"  ❌ {token} -- unexpected error escaped sync_one: {e}")
                results[index] = {
                    "token": token, "status": "error", "added": 0,
                    "skipped": 0, "error": f"unexpected: {e}",
                }

    return results  # type: ignore[return-value]
