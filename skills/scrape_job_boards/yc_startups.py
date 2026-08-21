"""Y Combinator startups scraper — finds recently funded startups that are hiring.

Uses the unofficial YC API (yc-oss.github.io/api) which mirrors the Algolia index
that powers ycombinator.com/companies. No API key required.

Filters:
1. Companies marked as hiring (isHiring=true)
2. Recent batches (last 4-6 months: Winter 2026, Spring 2026, Summer 2026)
3. Applies relevance_filter for role/tech stack matching

Usage:
    python -m skills.scrape_job_boards.yc_startups [max_leads]
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from storage.sheet_client import add_lead

# YC OSS API endpoints (no auth required, updated daily)
YC_API_BASE = "https://yc-oss.github.io/api"
YC_HIRING_URL = f"{YC_API_BASE}/companies/hiring.json"

# Recent batches to filter for (4-6 months window)
# Adjust these based on current date - these are batches from ~Feb 2026 to Aug 2026
RECENT_BATCHES = [
    "Winter 2026",
    "Spring 2026", 
    "Summer 2026",
    "Fall 2025",  # Include slightly older for broader pool
    "Winter 2025",
]

# Tech-focused industries to prioritize
TECH_INDUSTRIES = [
    "B2B",
    "Engineering, Product and Design",
    "Infrastructure",
    "Fintech",
    "Developer Tools",
    "AI",
    "Healthcare IT",
    "Security",
]


def fetch_hiring_companies() -> list[dict]:
    """Fetch all YC companies currently hiring."""
    try:
        response = requests.get(YC_HIRING_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  ❌ Failed to fetch YC hiring data: {e}")
        return []


def fetch_batch_companies(batch_slug: str) -> list[dict]:
    """Fetch companies from a specific batch."""
    # Convert "Winter 2026" -> "winter-2026"
    slug = batch_slug.lower().replace(" ", "-")
    url = f"{YC_API_BASE}/batches/{slug}.json"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  ⚠️  Failed to fetch batch {batch_slug}: {e}")
        return []


def is_recent_batch(batch: str) -> bool:
    """Check if company is from a recent batch (last 4-6 months)."""
    return batch in RECENT_BATCHES


def is_tech_company(company: dict) -> bool:
    """Check if company is in a tech-focused industry."""
    industries = company.get("industries", [])
    tags = company.get("tags", [])
    
    # Check industries
    for industry in industries:
        if industry in TECH_INDUSTRIES:
            return True
    
    # Check tags for tech signals
    tech_tags = ["Developer Tools", "API", "SaaS", "Infrastructure", "AI", 
                 "Machine Learning", "DevOps", "Open Source", "Data Engineering"]
    for tag in tags:
        if tag in tech_tags:
            return True
    
    return False


def yc_matches_criteria(lead: dict, company: dict) -> bool:
    """Light filter for YC companies - they're already tech startups.
    
    Only excludes:
    - Non-tech industries (healthcare services, food & beverage, etc.)
    - Companies with exclude keywords in description
    """
    industries = company.get("industries", [])
    tags = company.get("tags", [])
    description = (company.get("long_description") or "").lower()
    one_liner = (company.get("one_liner") or "").lower()
    combined = f"{description} {one_liner}"
    
    # Exclude certain industries that are clearly non-engineering focused
    non_engineering_industries = [
        "Food and Beverage",
        "Healthcare Services", 
        "Travel, Leisure and Tourism",
        "Apparel and Cosmetics",
        "Transportation Services",
    ]
    for industry in industries:
        if industry in non_engineering_industries:
            return False
    
    # Exclude non-tech keywords
    non_tech_keywords = [
        "mechanical", "civil", "electrical", "chemical", "maintenance",
        "manufacturing", "construction", "hvac", "plumbing", "plant",
        "petroleum", "oil & gas", "warehouse", "driver"
    ]
    for kw in non_tech_keywords:
        if kw in combined:
            return False
    
    # Prefer companies with tech-related tags
    # (but don't require - YC companies are generally tech)
    return True


def company_to_lead(company: dict) -> dict:
    """Convert YC company data to lead format."""
    name = company.get("name", "")
    one_liner = company.get("one_liner", "")
    long_desc = company.get("long_description", "")
    website = company.get("website", "")
    batch = company.get("batch", "")
    industries = company.get("industries", [])
    tags = company.get("tags", [])
    team_size = company.get("team_size", 0)
    stage = company.get("stage", "")
    yc_url = company.get("url", f"https://www.ycombinator.com/companies/{company.get('slug', '')}")
    
    # Build JD text from available info
    jd_parts = [
        f"Company: {name}",
        f"YC Batch: {batch}",
        f"Stage: {stage}",
        f"Team Size: {team_size}",
        f"\n{one_liner}" if one_liner else "",
        f"\n{long_desc}" if long_desc else "",
        f"\nIndustries: {', '.join(industries)}" if industries else "",
        f"Tags: {', '.join(tags)}" if tags else "",
        "\n\n[YC startup currently hiring — check their careers page for specific roles]",
    ]
    jd_text = "\n".join(filter(None, jd_parts))
    
    # Extract domain from website
    domain = ""
    if website:
        from urllib.parse import urlparse
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc.replace("www.", "")
    
    return {
        "source": "yc",
        "company": name,
        "role": f"Engineering @ {name} (YC {batch})",  # Generic since YC API doesn't list specific roles
        "jd_text": jd_text,
        "listing_url": yc_url,
        "domain": domain,
        "posted_date": "",  # Not available in API
    }


def run(max_leads: int = 20):
    """Main entry point: scrape YC startups that are hiring + recently funded."""
    print(f"\n{'='*60}")
    print("YC Startups Scraper")
    print(f"{'='*60}")
    print(f"Target: Hiring companies from recent batches ({', '.join(RECENT_BATCHES[:3])}...)")
    print(f"Max leads: {max_leads}")
    
    # Strategy 1: Get companies currently hiring
    print(f"\n📡 Fetching YC companies currently hiring...")
    hiring_companies = fetch_hiring_companies()
    print(f"  Found {len(hiring_companies)} companies marked as hiring")
    
    # Filter for recent batches
    recent_hiring = [
        c for c in hiring_companies 
        if is_recent_batch(c.get("batch", ""))
    ]
    print(f"  {len(recent_hiring)} from recent batches")
    
    # Prioritize tech companies
    tech_hiring = [c for c in recent_hiring if is_tech_company(c)]
    non_tech_hiring = [c for c in recent_hiring if not is_tech_company(c)]
    
    # Combine: tech first, then non-tech
    candidates = tech_hiring + non_tech_hiring
    print(f"  {len(tech_hiring)} tech-focused, {len(non_tech_hiring)} other")
    
    # Strategy 2: If not enough, also fetch from recent batches directly
    if len(candidates) < max_leads:
        print(f"\n📡 Fetching additional companies from recent batches...")
        seen_ids = {c.get("id") for c in candidates}
        
        for batch in RECENT_BATCHES[:3]:  # Top 3 most recent
            batch_companies = fetch_batch_companies(batch)
            for c in batch_companies:
                if c.get("id") not in seen_ids and c.get("isHiring"):
                    candidates.append(c)
                    seen_ids.add(c.get("id"))
        
        print(f"  Now have {len(candidates)} total candidates")
    
    # Process candidates
    added = 0
    skipped = 0
    filtered_out = 0
    
    print(f"\n🔍 Processing candidates...")
    
    # Scan the full candidate pool (dedup is now cheap/in-memory) so we skip past
    # already-added companies and keep going until we find max_leads NEW ones.
    for company in candidates:
        if added >= max_leads:
            break
            
        lead = company_to_lead(company)
        name = company.get("name", "Unknown")
        batch = company.get("batch", "")
        
        # Use YC-specific light filter (not the strict relevance_filter)
        # YC companies are already tech startups, so we just exclude non-engineering industries
        if not yc_matches_criteria(lead, company):
            print(f"  ⏭️  {name} ({batch}) — filtered out (non-tech industry)")
            filtered_out += 1
            continue
        
        # Add to sheet
        try:
            was_added = add_lead(lead)
            if was_added:
                print(f"  ✅ {name} ({batch}) — added")
                added += 1
            else:
                print(f"  ⏭️  {name} ({batch}) — duplicate")
                skipped += 1
        except Exception as e:
            print(f"  ❌ {name} — error: {e}")
            skipped += 1
    
    print(f"\n{'='*60}")
    print(f"YC Startups: {added} added, {skipped} skipped, {filtered_out} filtered out")
    print(f"{'='*60}\n")
    
    return added


if __name__ == "__main__":
    max_leads = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    run(max_leads)
