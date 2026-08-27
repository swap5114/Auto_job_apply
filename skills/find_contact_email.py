import os
import sys
import re
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import repository as repo
from db.current_user import get_current_user_id

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
HUNTER_URL = "https://api.hunter.io/v2/domain-search"

# Apollo.io is used as a fallback when Hunter has no coverage (common for
# small/early-stage YC startups). The People Search endpoint typically isn't in
# an API key's scope (returns 403 API_INACCESSIBLE), so we deliberately avoid
# it and instead use two endpoints that standard keys can reach:
#   - Organization Enrichment (by domain) -> gives org_chart_root_people_ids,
#     i.e. the founder/CEO, which is exactly who to cold-email at a YC startup.
#   - People Match/Enrichment -> unlocks a real, verified email for a person
#     identified by id (from the org chart) or by name + domain.
# Apollo is the primary provider (a named founder/CEO is best for personalized
# cold outreach); Hunter is the fallback for generic role inboxes when Apollo
# has no coverage. Org enrichment and the email unlock each consume an Apollo
# credit, so every domain lookup now spends Apollo credits before falling back.
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_ORG_ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"
APOLLO_MATCH_URL = "https://api.apollo.io/api/v1/people/match"

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


# ---------------------------------------------------------------------------
# Apollo.io fallback
# ---------------------------------------------------------------------------

def _clean_domain(domain: str) -> str:
    """Normalises a domain for Apollo/Hunter: strips scheme, path, www., @."""
    if not domain:
        return ""
    domain = domain.strip().lstrip("@")
    if "://" in domain:
        domain = urlparse(domain).netloc or domain
    domain = domain.split("/")[0]
    return domain.replace("www.", "").strip().lower()


def _is_real_email(email: str) -> bool:
    """Apollo returns the placeholder `email_not_unlocked@domain.com` for
    contacts whose address hasn't been revealed -- treat that as no email."""
    if not email or "@" not in email:
        return False
    return "email_not_unlocked" not in email.lower()


def _apollo_headers() -> dict:
    # Apollo requires the key in the X-Api-Key header (passing it in the body
    # returns INVALID_API_KEY_LOCATION).
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "accept": "application/json",
        "x-api-key": APOLLO_API_KEY,
    }


def _apollo_person_name(person: dict) -> str:
    """Builds a greeting-friendly name from an Apollo person record. Apollo
    often truncates the last name to a single initial for un-saved contacts, so
    fall back to the first name alone rather than surfacing 'Patrick C'."""
    first = (person.get("first_name") or "").strip()
    last = (person.get("last_name") or "").strip()
    if first and len(last) > 1:
        return f"{first} {last}"
    if first:
        return first
    return (person.get("name") or "").strip() or None


def apollo_org_enrich(domain: str) -> dict:
    """Enriches a company by domain. Returns the organization dict (which
    includes org_chart_root_people_ids -- the founder/CEO) or {}."""
    if not APOLLO_API_KEY or not domain:
        return {}

    try:
        resp = requests.post(
            APOLLO_ORG_ENRICH_URL, json={"domain": domain},
            headers=_apollo_headers(), timeout=20,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Apollo org-enrich failed for {domain}: {e}")
        return {}

    return resp.json().get("organization") or {}


def apollo_match(payload: dict):
    """Calls the People Match/enrichment endpoint to unlock a verified email.
    Consumes an Apollo credit on success. Returns (email, name)."""
    if not APOLLO_API_KEY:
        return None, None

    body = {**payload, "reveal_personal_emails": False, "reveal_phone_number": False}

    try:
        resp = requests.post(
            APOLLO_MATCH_URL, json=body, headers=_apollo_headers(), timeout=20,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Apollo match failed ({payload}): {e}")
        return None, None

    person = resp.json().get("person") or {}
    email = person.get("email")
    if _is_real_email(email):
        return email, _apollo_person_name(person)
    return None, None


def apollo_lookup(domain: str, company: str = None, contact_name: str = None):
    """Fallback contact discovery via Apollo. Returns (email, name).

    Scoped to endpoints a standard Apollo key can reach (People Search is
    usually 403 API_INACCESSIBLE, so it's avoided):
      1. If a contact name is already known, unlock that person by name+domain.
      2. Otherwise enrich the org by domain and unlock the org-chart root
         (typically the founder/CEO -- ideal for YC-stage cold outreach).
    """
    if not APOLLO_API_KEY:
        return None, None

    domain = _clean_domain(domain)
    if not domain:
        return None, None

    # 1) Targeted unlock when we already have a name (e.g. YC/company_list founder).
    if contact_name:
        parts = contact_name.split()
        if len(parts) >= 2:
            email, name = apollo_match({"first_name": parts[0], "last_name": parts[-1], "domain": domain})
        else:
            email, name = apollo_match({"name": contact_name, "domain": domain})
        if email:
            return email, name or contact_name

    # 2) Org-chart root (founder/CEO) via organization enrichment.
    org = apollo_org_enrich(domain)
    for pid in (org.get("org_chart_root_people_ids") or [])[:2]:
        email, name = apollo_match({"id": pid})
        if email:
            return email, name

    return None, None


# ---------------------------------------------------------------------------
# Source-aware dispatcher
# ---------------------------------------------------------------------------

def _lookup_by_domain(domain: str, company: str = None, contact_name: str = None):
    """Resolve a contact for a known domain. Apollo first (named founder/CEO,
    best for personalized cold outreach), then Hunter (generic role inboxes
    like careers@/hr@) as a fallback when Apollo has no coverage. Returns
    (email, name)."""
    domain = _clean_domain(domain)
    if not domain:
        return None, None

    email, name = apollo_lookup(domain, company=company, contact_name=contact_name)
    if email:
        return email, name

    return hunter_lookup(domain), None


def _lookup_by_guessed_domains(company: str, contact_name: str = None):
    """For sources with no domain (arbeitnow/jobicy): guess candidate domains,
    try Apollo on the most likely guess first, then fall back to Hunter across
    all guesses. Returns (email, name)."""
    candidates = guess_domains_from_company(company)
    if not candidates:
        return None, None

    apollo_email, apollo_name = apollo_lookup(candidates[0], company=company, contact_name=contact_name)
    if apollo_email:
        return apollo_email, apollo_name

    for guess in candidates:
        email = hunter_lookup(guess)
        if email:
            return email, None

    print(f"No email found for {company} -- tried domains: {', '.join(candidates)}")
    return None, None


def find_contact_email_for_lead(lead: dict) -> dict:
    """Finds the best contact email (and name, when known) for a lead.

    Returns {"contact_email": str|None, "contact_name": str|None}. This is the
    primary entry point used by the pipeline graph; find_email_for_lead is a
    thin string-returning wrapper kept for existing callers.
    """
    source = lead.get("source")
    jd_text = lead.get("jd_text", "") or ""
    listing_url = lead.get("listing_url", "") or ""
    company = lead.get("company", "") or ""
    domain = _clean_domain(lead.get("domain") or "")
    contact_name = (lead.get("contact_name") or "").strip() or None

    email, name = None, None

    if domain:
        # A verified domain (YC website, company_list CSV, careers page) beats
        # any guessing below -- use it directly regardless of source.
        email, name = _lookup_by_domain(domain, company, contact_name)

    elif source == "x":
        # Bio/tweet text is already stored in jd_text -- scan it before
        # spending any API call.
        email_match = EMAIL_PATTERN.search(jd_text)
        if email_match:
            email = email_match.group(0)
        else:
            url_match = URL_PATTERN.search(jd_text)
            if url_match:
                d = urlparse(url_match.group(0)).netloc
                email, name = _lookup_by_domain(d, company, contact_name)

    elif source == "careers_page" and listing_url:
        # listing_url is the company's own site here -- real domain.
        email, name = _lookup_by_domain(urlparse(listing_url).netloc, company, contact_name)

    elif source in ("arbeitnow", "jobicy") and company:
        # listing_url points at the aggregator, not the employer -- guess.
        email, name = _lookup_by_guessed_domains(company, contact_name)

    elif company:
        # Last resort for any other source that at least has a company name.
        email, name = _lookup_by_guessed_domains(company, contact_name)

    return {"contact_email": email, "contact_name": name}


def find_email_for_lead(lead: dict) -> str:
    """Backward-compatible wrapper: returns just the email string (or None)."""
    return find_contact_email_for_lead(lead).get("contact_email")


def run():
    if not HUNTER_API_KEY and not APOLLO_API_KEY:
        print("Neither HUNTER_API_KEY nor APOLLO_API_KEY set in config/.env -- skipping find_contact_email.")
        return
    if not HUNTER_API_KEY:
        print("HUNTER_API_KEY not set -- running with Apollo only.")
    if not APOLLO_API_KEY:
        print("APOLLO_API_KEY not set -- running with Hunter only (no fallback).")

    user_id = get_current_user_id()
    leads = repo.get_leads(user_id)
    targets = [lead for lead in leads if not (lead.get("contact_email") or "").strip()]

    found = 0
    not_found = 0

    for lead in targets:
        result = find_contact_email_for_lead(lead)
        email = result.get("contact_email")
        name = result.get("contact_name")

        if email:
            fields = {"contact_email": email}
            # Only fill contact_name if Apollo gave us one and the lead doesn't
            # already have a (e.g. scraper-provided) name.
            if name and not (lead.get("contact_name") or "").strip():
                fields["contact_name"] = name
            repo.update_lead(user_id, lead["id"], fields)
            found += 1
            label = lead.get("company") or lead.get("x_handle") or lead["id"]
            who = f" ({name})" if name else ""
            print(f"Found email for {label}: {email}{who}")
        else:
            not_found += 1

    print(f"\nfind_contact_email: {found} found, {not_found} not found (left null).")


if __name__ == "__main__":
    run()
