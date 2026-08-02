import csv
import os
import sys
import re
import json
import requests
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from storage.sheet_client import add_lead
from skills.relevance_filter import matches_criteria
from skills.find_contact_email import guess_domain_from_company

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "config", ".env"))

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
FIRECRAWL_MAP_URL = "https://api.firecrawl.dev/v1/map"

# Hard cap so one company with a huge careers page (500+ roles) can't blow
# through Firecrawl/Hunter/Claude API budgets in a single run.
MAX_ROLES_PER_COMPANY = 20

CAREER_PATH_KEYWORDS = [
    "career", "careers", "jobs", "job", "join-us", "join",
    "positions", "openings", "work-with-us", "hiring",
]

# Sites hosted on a third-party ATS are a strong signal a link is a real
# job posting, not a nav link -- helps the heuristic below stay precise.
KNOWN_ATS_DOMAINS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "breezy.hr", "smartrecruiters.com", "myworkdayjobs.com",
    "bamboohr.com", "recruitee.com", "jobvite.com",
]

NAV_LINK_DENYLIST = {
    "home", "about", "about us", "contact", "contact us", "privacy",
    "privacy policy", "terms", "terms of service", "blog", "linkedin",
    "twitter", "x", "facebook", "instagram", "login", "sign in",
    "sign up", "cookie policy", "faq", "press", "media", "careers",
    "jobs", "our team", "team",
}

LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")

# Different CSVs (Tracxn/Crunchbase-style exports, manual lists, etc.) use
# different column names for the same thing -- match by normalized alias
# instead of hardcoding one exact header string per field. Aliases are
# checked as whole-phrase matches (not bare substrings) so e.g. "name"
# alone isn't used for "company" -- it would wrongly also match a
# "Founder Name" or "Contact Name" column.
HEADER_ALIASES = {
    "company": ["company name", "company", "organization", "startup"],
    "domain": ["company domain", "domain", "website"],
    "founder": ["founder name", "founder", "founders", "ceo"],
    "hq": ["headquarters", "hq location", "hq", "location"],
    "funding": [
        "total funding raised", "money raised", "total funding",
        "funding amount", "amount raised", "funding",
    ],
}


def _normalize_header(name: str) -> str:
    # Punctuation (apostrophes, etc.) collapses to a space, e.g.
    # "Founder's Name" -> "founder s name" -- aliases are matched as
    # whole phrases below so this still lines up with the "founder" alias.
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _map_headers(fieldnames: list) -> dict:
    """Matches whatever headers a given CSV has against known aliases, so the
    skill works against a differently-formatted CSV each time instead of
    one hardcoded column layout."""
    mapped = {}
    for original in fieldnames or []:
        normalized = _normalize_header(original)
        for field, aliases in HEADER_ALIASES.items():
            if field in mapped:
                continue
            if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in aliases):
                mapped[field] = original
                break
    return mapped


def read_companies(csv_path: str) -> list:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header_map = _map_headers(reader.fieldnames)

        if "company" not in header_map:
            raise ValueError(
                f"Could not find a company-name column in {csv_path}. "
                f"Columns found: {reader.fieldnames}"
            )

        companies = []
        for row in reader:
            company = (row.get(header_map["company"]) or "").strip()
            if not company:
                continue

            companies.append({
                "company": company,
                "domain": (row.get(header_map.get("domain", "")) or "").strip(),
                "founder": (row.get(header_map.get("founder", "")) or "").strip(),
                "hq": (row.get(header_map.get("hq", "")) or "").strip(),
                "funding": (row.get(header_map.get("funding", "")) or "").strip(),
            })

        return companies


def fetch_markdown(url: str) -> str:
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps({"url": url, "formats": ["markdown"]})

    response = requests.post(FIRECRAWL_SCRAPE_URL, headers=headers, data=data, timeout=30)
    response.raise_for_status()

    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"Firecrawl scrape did not succeed for {url}: {payload}")

    markdown = payload.get("data", {}).get("markdown", "")
    if not markdown:
        raise RuntimeError(f"No content returned for {url}")

    return markdown


def find_career_pages(domain: str) -> list:
    """Maps a company's site (cheap link-discovery, no full page scrape)
    and returns URLs that look like careers/jobs pages."""
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    url = domain if domain.startswith("http") else f"https://{domain}"
    data = json.dumps({"url": url, "search": "careers jobs"})

    response = requests.post(FIRECRAWL_MAP_URL, headers=headers, data=data, timeout=30)
    response.raise_for_status()

    payload = response.json()
    if not payload.get("success"):
        return []

    # NOTE: verify this key against a real Firecrawl /v1/map response the
    # first time this runs -- hedging on "links" vs "data" since it wasn't
    # confirmed live.
    links = payload.get("links") or payload.get("data") or []

    return [link for link in links if any(kw in link.lower() for kw in CAREER_PATH_KEYWORDS)]


def extract_role_links(markdown: str) -> list:
    """Pulls candidate individual-job-posting links out of a careers page's
    markdown. Heuristic, not a real parser -- ATS-hosted job boards
    (Greenhouse, Lever, etc.) vary too much in structure for anything more
    precise without per-site rules. Expect to miss some roles and
    occasionally pick up a stray nav link."""
    candidates = []
    seen_urls = set()

    for text, url in LINK_PATTERN.findall(markdown):
        title = text.strip()
        normalized_title = title.lower()

        if not title or normalized_title in NAV_LINK_DENYLIST:
            continue
        if url in seen_urls:
            continue
        if len(title.split()) > 10:
            continue  # reads like a sentence, not a job title

        is_known_ats = any(ats in url for ats in KNOWN_ATS_DOMAINS)
        looks_like_role_path = re.search(r"(job|role|position|req|opening)", url.lower()) is not None

        if is_known_ats or looks_like_role_path or len(title.split()) <= 8:
            candidates.append((title, url))
            seen_urls.add(url)

        if len(candidates) >= MAX_ROLES_PER_COMPANY:
            break

    return candidates


def run(csv_path: str):
    if not FIRECRAWL_API_KEY:
        print("FIRECRAWL_API_KEY not set in config/.env -- skipping company_list scrape.")
        return

    companies = read_companies(csv_path)

    added = 0
    skipped = 0
    filtered_out = 0
    issues = 0

    for entry in companies:
        company = entry["company"]
        domain = entry["domain"] or guess_domain_from_company(company)

        if not domain:
            print(f"Skipping {company}: no domain available or guessable.")
            issues += 1
            continue

        try:
            career_pages = find_career_pages(domain)
        except requests.exceptions.RequestException as e:
            print(f"Failed to map {domain}: {e}")
            issues += 1
            continue

        if not career_pages:
            print(f"No careers page found for {company} ({domain}).")
            issues += 1
            continue

        context_parts = []
        if entry["hq"]:
            context_parts.append(f"HQ: {entry['hq']}")
        if entry["funding"]:
            context_parts.append(f"Funding raised: {entry['funding']}")
        context_note = " | ".join(context_parts)

        company_added = 0

        for page_url in career_pages:
            try:
                listing_markdown = fetch_markdown(page_url)
            except (requests.exceptions.RequestException, RuntimeError) as e:
                print(f"Failed to scrape {page_url}: {e}")
                continue

            for title, role_url in extract_role_links(listing_markdown):
                try:
                    jd_markdown = fetch_markdown(role_url)
                except (requests.exceptions.RequestException, RuntimeError) as e:
                    print(f"Failed to scrape role page {role_url}: {e}")
                    continue

                jd_text = f"{context_note}\n\n---\n\n{jd_markdown}" if context_note else jd_markdown

                lead = {
                    "source": "company_list",
                    "company": company,
                    "role": title,
                    "jd_text": jd_text,
                    "contact_name": entry["founder"],
                    "domain": domain,
                    "listing_url": role_url,
                    "posted_date": "",
                }

                if not matches_criteria(lead):
                    filtered_out += 1
                    continue

                if add_lead(lead):
                    added += 1
                    company_added += 1
                else:
                    skipped += 1

        if company_added == 0:
            issues += 1

    print(f"\ncompany_list: {added} added, {skipped} skipped (duplicates), "
          f"{filtered_out} filtered out, {issues} companies with issues.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python skills/scrape_job_boards/company_list.py <path-to-csv>")
        sys.exit(1)
    run(sys.argv[1])
