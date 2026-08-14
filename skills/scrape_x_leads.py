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

GETX_API_KEY = os.getenv("GETX_API_KEY")
GETX_URL = "https://api.getxapi.com/twitter/tweet/advanced_search"

QUERIES = [
    '"hiring" ("fresher" OR "entry level" OR "junior") (developer OR engineer)',
    '"we\'re hiring" (backend OR frontend OR "full stack" OR MERN) remote',
    '"looking for" ("junior developer" OR "entry level engineer") India',
]


def search_tweets_sorsa(query: str) -> list:
    """Search tweets using Sorsa API."""
    headers = { 
        "ApiKey": SORSA_API_KEY,
        "Content-Type": "application/json",
    }
    body = {"query": query, "order": "latest"}

    response = requests.post(SORSA_URL, headers=headers, json=body, timeout=15)
    response.raise_for_status()
    return response.json().get("tweets", [])


def search_tweets_getx(query: str, count: int = 20) -> list:
    """Search tweets using GetX API (fallback)."""
    headers = {"Authorization": f"Bearer {GETX_API_KEY}"}
    params = {"q": query, "count": count}  # GetX uses 'q' not 'query'
    
    response = requests.get(GETX_URL, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    # GetX API response format: {query, tweet_count, tweets: [...]}
    return data.get("tweets", [])


def search_tweets(query: str) -> tuple[list, str]:
    """Search tweets, trying Sorsa first, then GetX API as fallback.
    
    Returns:
        (tweets, source) where source is "sorsa" or "getx"
    """
    # Try Sorsa first
    if SORSA_API_KEY:
        try:
            tweets = search_tweets_sorsa(query)
            return (tweets, "sorsa")
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  Sorsa failed: {e}")
    
    # Fallback to GetX
    if GETX_API_KEY:
        try:
            tweets = search_tweets_getx(query)
            return (tweets, "getx")
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  GetX failed: {e}")
            return ([], "none")
    
    return ([], "none")


def run(max_leads: int = None):
    """Run X lead scraper.
    
    Args:
        max_leads: Maximum number of leads to add (default: unlimited)
    """
    if not SORSA_API_KEY and not GETX_API_KEY:
        print("Neither SORSA_API_KEY nor GETX_API_KEY set in config/.env -- skipping scrape_x_leads.")
        return

    added = 0
    skipped = 0
    filtered_out = 0
    source_used = None

    for query in QUERIES:
        if max_leads and added >= max_leads:
            print(f"Reached limit of {max_leads} leads, stopping.")
            break
            
        tweets, source = search_tweets(query)
        
        if not tweets:
            print(f"No tweets found for query '{query}'")
            continue
        
        if not source_used:
            source_used = source
            print(f"Using {source.upper()} API for X leads")

        for tweet in tweets:
            if max_leads and added >= max_leads:
                break
                
            # Handle both Sorsa and GetX formats
            user = tweet.get("user", {})
            
            # GetX format: no user object, extract username from URL
            if not user and tweet.get("url"):
                # URL format: https://x.com/USERNAME/status/ID
                url_parts = tweet.get("url", "").split("/")
                username = url_parts[3] if len(url_parts) > 3 else ""
                user_bio = ""  # GetX doesn't include user bio in tweet response
            elif user:
                # Sorsa format: user object with details
                username = user.get("username", "") or user.get("screen_name", "")
                user_bio = user.get("description", "") or user.get("bio", "")
            else:
                username = ""
                user_bio = ""
            
            tweet_id = tweet.get("id", "") or tweet.get("id_str", "")
            tweet_text = tweet.get("full_text", "") or tweet.get("text", "")
            tweet_url = tweet.get("url", "") or f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else ""

            lead = {
                "source": "x",
                "company": "",
                "role": "",
                "jd_text": f"Bio: {user_bio}\n\nTweet: {tweet_text}",
                "listing_url": tweet_url,
                "posted_date": tweet.get("created_at", "") or tweet.get("createdAt", ""),
                "x_handle": username,
            }

            if not matches_criteria(lead):
                filtered_out += 1
                continue

            if add_lead(lead):
                added += 1
            else:
                skipped += 1

    api_name = source_used.upper() if source_used else "No API"
    print(f"\n{api_name} (X leads): {added} added, {skipped} skipped (duplicates), {filtered_out} filtered out.")


if __name__ == "__main__":
    import sys
    max_leads = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(max_leads)
