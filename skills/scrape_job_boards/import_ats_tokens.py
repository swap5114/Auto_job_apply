"""One-off importer: pulls real, verified company tokens into ats_tokens.json
from kalil0321/ats-scrapers (MIT licensed), an actively maintained open
dataset of companies using each ATS platform:
https://github.com/kalil0321/ats-scrapers/tree/main/ats-companies

Why this exists: a hand-picked seed list of ~20 companies is not a real
catalog for a job-search product -- it was a placeholder from Phase 1's
first pass, called out as inadequate, and replaced with this. This dataset
gives ~11,800 real, currently-live company tokens across the three
providers (spot-checked live against each API before adopting it).

Re-run this whenever you want to refresh the token list against upstream's
latest CSVs (they add new companies over time). This OVERWRITES
ats_tokens.json's greenhouse/lever/ashby arrays -- if you've hand-added
tokens not in upstream's CSVs, re-add them after re-running this, or add
them to upstream via a PR instead (see their CONTRIBUTING guidance).

Usage:
    python -m skills.scrape_job_boards.import_ats_tokens
"""

import csv
import io
import json
import os

import requests

RAW_BASE = "https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/ats-companies"
PROVIDERS = ["greenhouse", "lever", "ashby"]
TOKENS_PATH = os.path.join(os.path.dirname(__file__), "ats_tokens.json")

ATTRIBUTION = (
    "Seed list of ATS board tokens. Bulk-imported from kalil0321/ats-scrapers "
    "(MIT licensed, https://github.com/kalil0321/ats-scrapers/tree/main/ats-companies), "
    "an actively maintained open dataset of real, verified company tokens per ATS "
    "platform. Re-run skills/scrape_job_boards/import_ats_tokens.py to refresh."
)


def fetch_slugs(provider: str) -> list[str]:
    url = f"{RAW_BASE}/{provider}.csv"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    slugs = sorted({row["slug"] for row in reader if row.get("slug")})
    return slugs


def run() -> None:
    data = {"_comment": ATTRIBUTION}

    for provider in PROVIDERS:
        print(f"Fetching {provider} token list...")
        slugs = fetch_slugs(provider)
        data[provider] = slugs
        print(f"  {len(slugs)} tokens")

    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total = sum(len(data[p]) for p in PROVIDERS)
    print(f"\nWrote {total} total tokens to {TOKENS_PATH}")


if __name__ == "__main__":
    run()
