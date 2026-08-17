"""Company research skill — generates structured research for a lead.

Given a lead (company name, domain, job description text), this uses the LLM
to produce concise, outreach-focused research: what the company does, its
likely stage, tech-stack signals pulled from the JD, tailored talking points,
and smart questions to ask.

The output is designed to power the "Company Research" tab in the dashboard's
lead detail view, and to give draft_outreach richer, more specific material.

Can run standalone:
    python -m skills.research_company <lead_id>
"""

import os
import sys
import json

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from skills.llm_client import llm_generate_json

SYSTEM_PROMPT = """You are a company-research assistant for a job candidate preparing personalized outreach. You will be given a company name, optional domain, and a job description. Produce concise, accurate, outreach-focused research.

STRICT RULES:
1. Base every claim on the job description text and widely-known facts. If you are not confident about a fact (funding, headcount, revenue), mark it clearly as an inference, never state it as certain.
2. NEVER fabricate specific numbers (exact funding amounts, exact employee counts, customer names) that are not supported by the input. Prefer ranges/qualitative bands ("early-stage", "growth-stage") over invented precision.
3. Tech-stack signals must be extracted from the job description — do not guess technologies the JD does not mention.
4. Talking points must be specific to THIS company/role, referencing something real from the JD (the product, the problem they solve, a technology, a responsibility). No generic flattery.
5. Questions should be sharp and show genuine engagement — the kind a thoughtful candidate would ask.

Return ONLY valid JSON in exactly this shape (no markdown, no prose):
{
  "overview": "2-3 sentence summary of what the company does",
  "stage": "one of: Early-stage | Growth-stage | Established | Unknown",
  "industry": "short industry label",
  "tech_signals": ["tech or tool extracted from the JD", "..."],
  "talking_points": ["specific, JD-grounded outreach angle", "...", "..."],
  "smart_questions": ["sharp question to ask", "..."],
  "fit_summary": "1-2 sentences on why this candidate angle could resonate"
}"""


def research_company(company: str, domain: str, role: str, jd_text: str) -> dict:
    """Generate structured research for a company/role from the JD."""
    user_message = f"""Company: {company or "(unknown)"}
Domain: {domain or "(unknown)"}
Role: {role or "(unknown)"}

Job description / hiring-signal text:
{jd_text or "(no job description provided)"}"""

    return llm_generate_json(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=1200,
    )


def run(lead_id: str):
    """Standalone: research a single lead by id and print the result."""
    from storage.sheet_client import get_leads

    leads = get_leads()
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        print(f"No lead found with id {lead_id}")
        return

    result = research_company(
        company=lead.get("company", ""),
        domain=lead.get("domain", ""),
        role=lead.get("role", ""),
        jd_text=lead.get("jd_text", ""),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m skills.research_company <lead_id>")
    else:
        run(sys.argv[1])
