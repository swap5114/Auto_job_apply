import os
import sys
import requests
from bs4 import BeautifulSoup  # type: ignore

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from db import repository as repo
from db.current_user import get_current_user_id
from skills.relevance_filter import matches_criteria

URL = "https://jobicy.com/api/v2/remote-jobs"


def run(user_id: str | None = None):
    if user_id is None:
        user_id = get_current_user_id()
    added = 0
    skipped = 0
    filtered_out = 0

    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()

        payload = response.json()
        jobs = payload.get("jobs", [])

        for job in jobs:
            raw_description = job.get("jobDescription", "")
            jd_text = BeautifulSoup(raw_description, "html.parser").get_text(separator=" ", strip=True)

            lead = {
                "source": "jobicy",
                "company": job.get("companyName") or "",
                "role": job.get("jobTitle") or "",
                "jd_text": jd_text,
                "listing_url": job.get("url", ""),
                "posted_date": job.get("pubDate", ""),
            }

            if not matches_criteria(lead):
                filtered_out += 1
                continue

            if repo.try_add_lead(user_id, lead):
                added += 1
            else:
                skipped += 1

    except requests.exceptions.RequestException as e:
        print(f"API Call Failed: {e}")
        return

    print(f"\nJobicy: {added} added, {skipped} skipped (duplicates), {filtered_out} filtered out.")


if __name__ == "__main__":
    run()
