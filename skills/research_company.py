"""Company research skill — fetches structured company data and generates demo ideas.

Uses Context.dev API to get:
- Company profile (description, industry, tech stack)
- Website content and structure
- Social handles and links

Then uses LLM to suggest a small demo project the candidate could build
that's directly relevant to the company's product/problem.

Usage:
    python -m skills.research_company
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.sheet_client import get_leads, update_lead
from skills.llm_client import llm_generate

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

CONTEXT_API_KEY = os.getenv("CONTEXT_API_KEY")
CONTEXT_API_URL = "https://api.context.dev/v1"


def get_company_domain(lead: dict) -> str | None:
    """Extract domain from lead data.
    
    Priority:
    1. domain field (if pre-populated from company_list)
    2. listing_url (for job board leads)
    3. guess from company name
    """
    # Pre-verified domain
    if lead.get("domain"):
        return lead["domain"].strip()
    
    # Extract from listing URL (for careers pages)
    listing_url = lead.get("listing_url") or ""
    if listing_url and "http" in listing_url:
        from urllib.parse import urlparse
        parsed = urlparse(listing_url)
        # Skip aggregator domains
        if parsed.netloc and not any(x in parsed.netloc for x in ["arbeitnow", "jobicy", "remotive", "weworkremotely"]):
            return parsed.netloc.replace("www.", "")
    
    # Guess from company name
    company = lead.get("company") or ""
    if company:
        from skills.find_contact_email import guess_domain_from_company
        return guess_domain_from_company(company)
    
    return None


def fetch_company_brand(domain: str) -> dict | None:
    """Fetch structured company data from Context.dev Brand API."""
    if not CONTEXT_API_KEY:
        print(f"  ⚠️  CONTEXT_API_KEY not set, skipping brand lookup for {domain}")
        return None
    
    try:
        # Context.dev uses POST /brand/retrieve, not GET
        response = requests.post(
            f"{CONTEXT_API_URL}/brand/retrieve",
            headers={"Authorization": f"Bearer {CONTEXT_API_KEY}"},
            json={
                "type": "by_domain",
                "domain": domain,
            },
            timeout=90,  # Context.dev can take up to 60s for cold hits
        )
        response.raise_for_status()
        data = response.json()
        
        # Context.dev returns status: "ok" or "error"
        if data.get("status") != "ok":
            print(f"  ⚠️  Context.dev returned status={data.get('status')} for {domain}")
            return None
        
        return data
    
    except requests.exceptions.Timeout:
        print(f"  ⚠️  Context.dev timeout for {domain} (>90s)")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Context.dev error for {domain}: {e}")
        return None


def fetch_website_content(domain: str) -> dict | None:
    """Fetch website markdown content from Context.dev Web API."""
    if not CONTEXT_API_KEY:
        return None
    
    try:
        # Context.dev Web API: GET /web/scrape/markdown with query params
        # Note: booleans must be lowercase strings "true"/"false" in query params
        response = requests.get(
            f"{CONTEXT_API_URL}/web/scrape/markdown",
            headers={"Authorization": f"Bearer {CONTEXT_API_KEY}"},
            params={
                "url": f"https://{domain}",
                "useMainContentOnly": "true",  # String, not bool
                "maxAgeMs": 86400000,  # 24h cache
            },
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("success") and data.get("markdown"):
            return {
                "markdown": data["markdown"][:5000],  # Truncate to 5k chars
                "url": data.get("url", f"https://{domain}"),
            }
        return None
    
    except Exception as e:
        print(f"  ⚠️  Context.dev web scrape error for {domain}: {e}")
        return None


def generate_demo_idea(brand_data: dict, website_content: dict | None, lead: dict) -> str:
    """Generate a demo project idea using LLM based on company research."""
    company = lead.get("company") or brand_data.get("brand", {}).get("name", "this company")
    role = lead.get("role") or "this role"
    
    # Extract useful context from brand data
    description = brand_data.get("brand", {}).get("description", "")
    industry = brand_data.get("brand", {}).get("industry", {}).get("name", "")
    
    # Build context for LLM
    context_parts = [f"Company: {company}"]
    
    if description:
        context_parts.append(f"What they do: {description}")
    
    if industry:
        context_parts.append(f"Industry: {industry}")
    
    if website_content and website_content.get("markdown"):
        context_parts.append(f"\nWebsite content (first 5000 chars):\n{website_content['markdown']}")
    
    context_str = "\n".join(context_parts)
    
    prompt = f"""You are helping a job candidate research a company to build a relevant demo project.

{context_str}

Role they're applying for: {role}

Based on this company's product and problem space, suggest a small demo project (2-3 days of work) that would be:
1. Directly relevant to their product/tech stack
2. Impressive but achievable in a short timeframe
3. Something the candidate could build and share as a live link or video

Output format (plain text, 2-3 sentences):
- What to build
- Why it's relevant to {company}
- Suggested tech stack (based on what {company} likely uses)

Keep it concrete and specific. No generic suggestions like "build a dashboard" — make it about their actual product."""

    try:
        result = llm_generate(
            system_prompt="You are a technical product researcher helping job candidates build relevant demo projects.",
            user_message=prompt,
            max_tokens=300,
        )
        return result.strip()
    
    except Exception as e:
        print(f"  ⚠️  LLM demo idea generation failed: {e}")
        return f"Research {company}'s product and build a small feature or tool that solves a problem their users face."


def research_lead(lead: dict) -> dict | None:
    """Research a single lead and return company data + demo idea."""
    lead_id = lead.get("id")
    company = lead.get("company") or lead.get("x_handle") or "Unknown"
    
    # X leads without company names can't be researched via domain
    if not lead.get("company"):
        print(f"  ⏭️  {company} — no company name, skipping research")
        return None
    
    domain = get_company_domain(lead)
    if not domain:
        print(f"  ⏭️  {company} — couldn't determine domain, skipping")
        return None
    
    print(f"  🔍 Researching {company} ({domain})...")
    
    # Fetch brand data (company profile)
    brand_data = fetch_company_brand(domain)
    if not brand_data:
        print(f"  ⚠️  {company} — no brand data returned")
        return None
    
    # Optionally fetch website content for richer context
    website_content = fetch_website_content(domain)
    
    # Generate demo idea
    demo_idea = generate_demo_idea(brand_data, website_content, lead)
    
    # Extract useful fields from brand data
    brand = brand_data.get("brand", {})
    company_info = {
        "name": brand.get("name", company),
        "description": brand.get("description", ""),
        "industry": brand.get("industry", {}).get("name", ""),
        "website": brand.get("website", f"https://{domain}"),
        "careers_url": brand.get("links", {}).get("careers", ""),
        "linkedin": brand.get("social", {}).get("linkedin", ""),
        "github": brand.get("social", {}).get("github", ""),
    }
    
    return {
        "demo_idea": demo_idea,
        "company_info": json.dumps(company_info),  # Store as JSON string in Sheet
    }


def run():
    """Main entry point: research all leads that have a company name but no demo_idea yet."""
    if not CONTEXT_API_KEY:
        print("CONTEXT_API_KEY not set in config/.env — skipping research_company.")
        return
    
    leads = get_leads()
    
    # Target: leads with company name, no demo_idea yet
    targets = [
        l for l in leads 
        if (l.get("company") or "").strip() 
        and not (l.get("demo_idea") or "").strip()
    ]
    
    print(f"Leads eligible for research: {len(targets)}")
    
    researched = 0
    skipped = 0
    
    for lead in targets:
        result = research_lead(lead)
        
        if result:
            update_lead(lead["id"], result)
            researched += 1
            company = lead.get("company")
            print(f"  ✅ {company} researched")
            print(f"     Demo idea: {result['demo_idea'][:100]}...")
        else:
            skipped += 1
    
    print(f"\nresearch_company: {researched} researched, {skipped} skipped.")


if __name__ == "__main__":
    run()
