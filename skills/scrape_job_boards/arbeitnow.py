import os
import sys
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup  # type: ignore

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from storage.sheet_client import add_lead
from skills.relevance_filter import matches_criteria

URL = "https://www.arbeitnow.com/api/job-board-api"


def run():
    added = 0
    skipped = 0
    filtered_out = 0

    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()

        payload = response.json()
        jobs = payload.get("data", [])

        for job in jobs:
            raw_description = job.get("description", "")
            jd_text = BeautifulSoup(raw_description, "html.parser").get_text(separator=" ", strip=True)

            created_at = job.get("created_at")
            if created_at:
                posted_date = datetime.fromtimestamp(created_at, tz=timezone.utc).strftime("%Y-%m-%d")
            else:
                posted_date = ""

            lead = {
                "source": "arbeitnow",
                "company": job.get("company_name") or "",
                "role": job.get("title") or "",
                "jd_text": jd_text,
                "listing_url": job.get("url", ""),
                "posted_date": posted_date,
            }

            if not matches_criteria(lead):
                filtered_out += 1
                continue

            if add_lead(lead):
                added += 1
            else:
                skipped += 1

    except requests.exceptions.RequestException as e:
        print(f"API Call Failed: {e}")
        return

    print(f"\nArbeitnow: {added} added, {skipped} skipped (duplicates), {filtered_out} filtered out.")


if __name__ == "__main__":
    run()
