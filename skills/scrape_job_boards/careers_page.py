import os
import sys
import re
import json
import requests
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from storage.sheet_client import add_lead

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "config", ".env"))

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"

# Known job postings to scrape. There's no auto-discovery of listing pages
# yet -- add (url, company) pairs here as you find them.
TARGET_JOBS = [
    ("https://migma.ai/careers/backend-product-engineer", "Migma AI"),
]


def fetch_markdown(url: str) -> str:
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps({"url": url, "formats": ["markdown"]})

    response = requests.post(FIRECRAWL_URL, headers=headers, data=data, timeout=30)
    response.raise_for_status()

    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"Firecrawl did not succeed for {url}: {payload}")

    markdown = payload.get("data", {}).get("markdown", "")
    if not markdown:
        raise RuntimeError(f"No content returned for {url}")

    return markdown


def extract_role(markdown: str) -> str:
    match = re.search(r"^# (.+)$", markdown, re.MULTILINE)
    return match.group(1) if match else "Unknown Role"


def run():
    if not FIRECRAWL_API_KEY:
        print("FIRECRAWL_API_KEY not set in config/.env -- skipping careers_page scrape.")
        return

    added = 0
    skipped = 0

    for url, company in TARGET_JOBS:
        try:
            markdown = fetch_markdown(url)
        except (requests.exceptions.RequestException, RuntimeError) as e:
            print(f"Failed to scrape {url}: {e}")
            continue

        lead = {
            "source": "careers_page",
            "company": company,
            "role": extract_role(markdown),
            "jd_text": markdown,
            "listing_url": url,
            "posted_date": "",
        }

        if add_lead(lead):
            added += 1
        else:
            skipped += 1

    print(f"\nCareers page: {added} added, {skipped} skipped (duplicates).")


if __name__ == "__main__":
    run()
