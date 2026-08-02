import os
import sys
import requests
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.sheet_client import add_lead
from skills.relevance_filter import matches_criteria

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

SORSA_API_KEY = os.getenv("SORSA_API_KEY")
SORSA_URL = "https://api.sorsa.io/v3/search-tweets"

QUERIES = [
    '"hiring" ("fresher" OR "entry level" OR "junior") (developer OR engineer)',
    '"we\'re hiring" (backend OR frontend OR "full stack" OR MERN) remote',
    '"looking for" ("junior developer" OR "entry level engineer") India',
]


def search_tweets(query: str) -> list:
    headers = { 
        "ApiKey": SORSA_API_KEY,
        "Content-Type": "application/json",
    }
    body = {"query": query, "order": "latest"}

    response = requests.post(SORSA_URL, headers=headers, json=body, timeout=15)
    response.raise_for_status()
    return response.json().get("tweets", [])


def run():
    if not SORSA_API_KEY:
        print("SORSA_API_KEY not set in config/.env -- skipping scrape_x_leads.")
        return

    added = 0
    skipped = 0
    filtered_out = 0

    for query in QUERIES:
        try:
            tweets = search_tweets(query)
        except requests.exceptions.RequestException as e:
            print(f"Sorsa API call failed for query '{query}': {e}")
            continue

        for tweet in tweets:
            user = tweet.get("user", {})
            username = user.get("username", "")
            tweet_id = tweet.get("id", "")

            lead = {
                "source": "x",
                "company": "",
                "role": "",
                "jd_text": f"Bio: {user.get('description', '')}\n\nTweet: {tweet.get('full_text', '')}",
                "listing_url": f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else "",
                "posted_date": tweet.get("created_at", ""),
                "x_handle": username,
            }

            if not matches_criteria(lead):
                filtered_out += 1
                continue

            if add_lead(lead):
                added += 1
            else:
                skipped += 1

    print(f"\nSorsa (X leads): {added} added, {skipped} skipped (duplicates), {filtered_out} filtered out.")


if __name__ == "__main__":
    run()
