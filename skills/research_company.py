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

SYSTEM_PROMPT = """You are a company-research assistant helping a job candidate write outreach that stands out. Your PRIMARY goal is to produce ONE deep, specific, genuinely useful IDEA / USE-CASE for this company that the candidate can lead their outreach with — something that shows real understanding of the company's problem and demonstrates value, not a generic pitch.

Given a company name, domain, role, and job description, produce:
1. A short, accurate company overview (what they do, their product/problem space).
2. ONE specific, high-value use-case or improvement idea that:
   - Targets a real problem or opportunity this specific company has (inferred from the JD / what they build)
   - Would create clear, concrete value for them (a metric moved, a workflow unblocked, a risk reduced)
   - Is realistic for one motivated engineer to prototype
   - Uses tech the company actually signals in the JD when relevant

STRICT RULES (zero fabrication):
1. The idea must be CONCRETE and SPECIFIC to THIS company — never generic ("build a dashboard", "add an API"). Anchor it in their actual product or problem as described in the JD.
2. Base every claim on the JD text and widely-known facts. If uncertain about a fact (funding, headcount, internal stack), hedge ("likely", "appears to be") — never assert it as certain, and never invent one.
3. Tech-stack signals must come from the JD — do not guess technologies not mentioned.
4. The idea is a PROPOSAL — something the candidate is thinking about and could prototype. It is NOT something already built, shipped, or attached. Do not describe it as done.
5. If the idea would benefit from an LLM/AI API, prefer Google Gemini (genuinely free tier) over paid-only options in tech_stack, and only include an LLM API at all if the idea's core value genuinely needs one.

Return ONLY valid JSON in exactly this shape (no markdown, no prose):
{
  "overview": "2-3 sentence summary of what the company does and their core product/problem",
  "stage": "one of: Early-stage | Growth-stage | Established | Unknown",
  "industry": "short industry label",
  "tech_signals": ["tech or tool extracted from the JD", "..."],
  "demo_project": {
    "title": "Short, specific name for the idea/use-case",
    "description": "2-3 sentences: the concrete idea and exactly how it applies to THIS company's product/problem",
    "why_it_matters": "1-2 sentences: the concrete value to the company (what it unblocks, improves, or de-risks)",
    "tech_stack": ["relevant tech, based on JD signals"],
    "deliverable": "What a prototype of this would be (a working prototype, a proof-of-concept, a small tool)",
    "time_estimate": "rough effort, e.g. 2-3 days",
    "why_impressive": "1 sentence on why raising this idea signals genuine understanding to the team"
  },
  "talking_points": ["specific outreach angle referencing the idea", "..."],
  "fit_summary": "1-2 sentences on how the idea + candidate background resonate"
}"""


def research_company(company: str, domain: str, role: str, jd_text: str) -> dict:
    """Generate company research + one deep, valuable use-case/idea from lead data.

    The `demo_project` object holds that idea (the key name is kept for
    backward compatibility with the parked build-demo feature); it is framed
    as a PROPOSAL the candidate could prototype, never as an already-built
    artifact -- see draft_outreach's honest injection.
    """
    user_message = f"""Company: {company or "(unknown)"}
Domain: {domain or "(unknown)"}
Role: {role or "(unknown)"}

Job description / hiring-signal text:
{jd_text or "(no job description provided)"}

Based on this, research the company and propose ONE deep, specific, genuinely useful idea / use-case the candidate could raise in cold outreach to show real understanding of this company's problem and demonstrate value. It is a proposal the candidate could prototype — not something already built."""

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


def run_batch(user_id: str | None = None):
    """Research all leads that need it (have company name but no research yet)."""
    from db import repository as repo
    from db.current_user import get_current_user_id

    if user_id is None:
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
