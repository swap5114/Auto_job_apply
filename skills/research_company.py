"""Company research skill — generates company insights + demo project ideas.

The core purpose is to help candidates stand out by:
1. Understanding what the company does and their problem space
2. Suggesting a small demo project (2-3 days of work) directly relevant to
   the company's product that the candidate can build and attach to outreach

This gives cold emails a concrete, personalized hook that shows genuine effort.

Usage:
    python -m skills.research_company <lead_id>
"""

import os
import sys
import json

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from skills.llm_client import llm_generate_json

SYSTEM_PROMPT = """You are a company-research assistant helping a job candidate prepare personalized outreach. Your PRIMARY goal is to suggest a small demo project the candidate can build to attach to their cold email and stand out.

Given a company name, domain, role, and job description, produce:
1. Company overview (what they do, their product/problem space)
2. A SPECIFIC demo project idea that:
   - Is directly relevant to their product/tech stack
   - Can be built in 2-3 days
   - Shows the candidate understands their problem
   - Can be shared as a live link, video, or GitHub repo
   - Uses tech mentioned in the JD when possible

STRICT RULES:
1. Demo ideas must be CONCRETE and SPECIFIC to THIS company — not generic like "build a dashboard" or "create an API". Reference their actual product or problem.
2. Base claims on the JD text and widely-known facts. If uncertain about facts (funding, headcount), say "likely" or "appears to be", never state as certain.
3. Tech-stack signals must come from the JD — don't guess technologies not mentioned.
4. The demo should solve a real problem the company faces or showcase a feature relevant to their product.
5. If the demo idea would benefit from an LLM/AI API call, prefer Google Gemini (it has a genuinely free tier) over OpenAI or Anthropic in tech_stack — never suggest a paid-only API when a free equivalent covers the same need. Only include an LLM API in tech_stack at all if the demo's core value genuinely depends on one; don't add "OpenAI API" or similar just because the company is AI-adjacent.

Return ONLY valid JSON in exactly this shape (no markdown, no prose):
{
  "overview": "2-3 sentence summary of what the company does and their core product/problem",
  "stage": "one of: Early-stage | Growth-stage | Established | Unknown",
  "industry": "short industry label",
  "tech_signals": ["tech or tool extracted from the JD", "..."],
  "demo_project": {
    "title": "Short, catchy name for the demo",
    "description": "2-3 sentences: What to build and why it's relevant to this company",
    "tech_stack": ["recommended tech to use, based on JD signals"],
    "deliverable": "What the candidate will share (live link, video demo, GitHub repo)",
    "time_estimate": "2-3 days",
    "why_impressive": "1 sentence on why this will catch the hiring manager's attention"
  },
  "talking_points": ["specific angle for outreach referencing the demo", "..."],
  "fit_summary": "1-2 sentences on how the demo + candidate background could resonate"
}"""


def research_company(company: str, domain: str, role: str, jd_text: str) -> dict:
    """Generate company research and demo project idea from lead data."""
    user_message = f"""Company: {company or "(unknown)"}
Domain: {domain or "(unknown)"}
Role: {role or "(unknown)"}

Job description / hiring-signal text:
{jd_text or "(no job description provided)"}

Based on this information, provide company research and suggest a SPECIFIC demo project the candidate can build to attach to their cold email outreach. The demo should be directly relevant to what this company does."""

    return llm_generate_json(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=1500,
    )


def run(lead_id: str):
    """Standalone: research a single lead by id and print the result."""
    from db import repository as repo
    from db.current_user import get_current_user_id

    user_id = get_current_user_id()
    leads = repo.get_leads(user_id)
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        print(f"No lead found with id {lead_id}")
        return

    company = lead.get("company", "") or lead.get("x_handle", "")
    print(f"\n🔍 Researching {company}...")
    
    result = research_company(
        company=lead.get("company", ""),
        domain=lead.get("domain", ""),
        role=lead.get("role", ""),
        jd_text=lead.get("jd_text", ""),
    )
    
    # Pretty print the result
    print(f"\n{'='*60}")
    print(f"COMPANY: {result.get('overview', 'N/A')}")
    print(f"STAGE: {result.get('stage', 'Unknown')} | INDUSTRY: {result.get('industry', 'N/A')}")
    print(f"\nTECH STACK: {', '.join(result.get('tech_signals', []))}")
    
    demo = result.get('demo_project', {})
    if demo:
        print(f"\n{'='*60}")
        print(f"🚀 DEMO PROJECT IDEA: {demo.get('title', 'N/A')}")
        print(f"{'='*60}")
        print(f"\n{demo.get('description', 'N/A')}")
        print(f"\nTech: {', '.join(demo.get('tech_stack', []))}")
        print(f"Deliverable: {demo.get('deliverable', 'N/A')}")
        print(f"Time: {demo.get('time_estimate', '2-3 days')}")
        print(f"\n💡 Why impressive: {demo.get('why_impressive', 'N/A')}")
    
    print(f"\n{'='*60}")
    print("Full JSON:")
    print(json.dumps(result, indent=2))


def run_batch():
    """Research all leads that need it (have company name but no research yet)."""
    from db import repository as repo
    from db.current_user import get_current_user_id

    user_id = get_current_user_id()
    leads = repo.get_leads(user_id)
    
    # Target: leads with company/role but no research done yet
    # We could add a 'company_research' column to track this
    targets = [
        l for l in leads 
        if (l.get("company") or "").strip() 
        and (l.get("jd_text") or "").strip()
    ]
    
    print(f"Leads eligible for research: {len(targets)}")
    
    for lead in targets[:5]:  # Limit to 5 for testing
        company = lead.get("company", "")
        print(f"\n🔍 Researching {company}...")
        
        try:
            result = research_company(
                company=lead.get("company", ""),
                domain=lead.get("domain", ""),
                role=lead.get("role", ""),
                jd_text=lead.get("jd_text", ""),
            )
            
            demo = result.get('demo_project', {})
            if demo:
                print(f"  ✅ Demo idea: {demo.get('title', 'N/A')}")
                print(f"     {demo.get('description', '')[:100]}...")
            
        except Exception as e:
            print(f"  ❌ Failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m skills.research_company <lead_id>  # Research single lead")
        print("  python -m skills.research_company --batch    # Research all eligible leads")
    elif sys.argv[1] == "--batch":
        run_batch()
    else:
        run(sys.argv[1])
