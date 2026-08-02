import os
import sys
import re
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.sheet_client import get_leads, update_lead

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
HUNTER_URL = "https://api.hunter.io/v2/domain-search"

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
URL_PATTERN = re.compile(r"https?://[^\s)]+")


LEGAL_SUFFIXES = {
    "bv", "nv", "inc", "llc", "ltd", "gmbh", "corp", "co",
    "plc", "sa", "ag", "srl", "pty", "limited", "incorporated",
}


def _company_words(company: str) -> list:
    """Splits a company name into words and drops a trailing legal-entity
    suffix (B.V., Inc, GmbH, ...) -- those are almost never part of the real
    domain, e.g. 'Strix Group B.V.' should guess 'strixgroup.com' /
    'strix-group.com', not 'strixgroupbv.com'."""
    # Strip periods before splitting, so an abbreviation like "B.V." stays
    # one token ("bv") instead of being cut into "b" and "v" at each dot.
    cleaned = company.lower().replace(".", "")
    words = re.findall(r"[a-z0-9]+", cleaned)
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return words


def guess_domain_from_company(company: str) -> str:
    """Single best-effort guess: words smashed together, no separator.
    Kept as one guess (not a list) since callers like company_list.py feed
    this straight into a paid Firecrawl call -- not something to retry."""
    words = _company_words(company)
    return f"{''.join(words)}.com" if words else None


def guess_domains_from_company(company: str) -> list:
    """Multiple candidate domains -- smashed-together and hyphenated -- since
    we can't know which form a company actually registered. Cheap to try
    both against Hunter's domain search, which costs nothing on a miss."""
    words = _company_words(company)
    if not words:
        return []
    candidates = [f"{''.join(words)}.com"]
    if len(words) > 1:
        candidates.append(f"{'-'.join(words)}.com")
    return candidates


def hunter_lookup(domain: str) -> str:
    """Looks up a work email for a company domain via Hunter's Domain Search.
    Returns the best match (prefers a generic/role address like hr@ or
    careers@ over a random personal one, since we have no named contact)."""
    if not domain:
        return None

    params = {
        "domain": domain,
        "api_key": HUNTER_API_KEY,
        "limit": 5,
    }

    try:
        response = requests.get(HUNTER_URL, params=params, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Hunter lookup failed for domain {domain}: {e}")
        return None

    emails = response.json().get("data", {}).get("emails", [])
    if not emails:
        return None

    generic = next((e for e in emails if e.get("type") == "generic"), None)
    chosen = generic or emails[0]
    return chosen.get("value")


def find_email_for_lead(lead: dict) -> str:
    source = lead.get("source")
    jd_text = lead.get("jd_text", "") or ""
    listing_url = lead.get("listing_url", "") or ""
    company = lead.get("company", "") or ""
    domain = (lead.get("domain") or "").strip()

    if domain:
        # A verified domain (e.g. from a company_list CSV) beats any
        # guessing/URL-parsing below -- use it directly regardless of source.
        return hunter_lookup(domain)

    if source == "x":
        # Bio/tweet text is already stored in jd_text -- check it before
        # ever calling Hunter, per the plan's "don't waste API calls" rule.
        email_match = EMAIL_PATTERN.search(jd_text)
        if email_match:
            return email_match.group(0)

        url_match = URL_PATTERN.search(jd_text)
        if url_match:
            domain = urlparse(url_match.group(0)).netloc
            return hunter_lookup(domain)

        return None

    if source == "careers_page" and listing_url:
        # listing_url is the company's own site here -- real domain.
        domain = urlparse(listing_url).netloc
        return hunter_lookup(domain)

    if source in ("arbeitnow", "jobicy") and company:
        # listing_url points at the aggregator, not the employer -- guess instead.
        candidates = guess_domains_from_company(company)
        for guess in candidates:
            email = hunter_lookup(guess)
            if email:
                return email
        if candidates:
            print(f"No email found for {company} -- tried guessed domains: {', '.join(candidates)}")
        return None

    return None


def run():
    if not HUNTER_API_KEY:
        print("HUNTER_API_KEY not set in config/.env -- skipping find_contact_email.")
        return

    leads = get_leads()
    targets = [lead for lead in leads if not (lead.get("contact_email") or "").strip()]

    found = 0
    not_found = 0

    for lead in targets:
        email = find_email_for_lead(lead)

        if email:
            update_lead(lead["id"], {"contact_email": email})
            found += 1
            label = lead.get("company") or lead.get("x_handle") or lead["id"]
            print(f"Found email for {label}: {email}")
        else:
            not_found += 1

    print(f"\nfind_contact_email: {found} found, {not_found} not found (left null).")


if __name__ == "__main__":
    run()
