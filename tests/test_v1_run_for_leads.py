"""v1 Task 10: approve matches -> start the pipeline bridge.

Saving matched YC jobs then running run_pipeline_for_leads drives them from
"matched" to "pending_review" with a drafted outreach message and a tailored
resume version. All external calls (email lookup, LLM tailor/draft, Gmail) are
mocked; the graph + repo run for real.
"""

from unittest.mock import patch

import pytest

from db import repository as repo
from orchestrator.pipeline_runner import run_pipeline_for_leads


def _make_user(suffix: str) -> dict:
    return repo.create_user(firebase_uid=f"fb-{suffix}", email=f"{suffix}@example.com")


def test_run_pipeline_for_leads_drives_matched_to_pending_review():
    user = _make_user("bridge")
    # Two saved-from-catalog leads (status "matched", with a domain so email
    # lookup has something to resolve).
    lead1 = repo.add_lead(user["id"], {"company": "Acme AI", "role": "Backend Engineer",
                                       "jd_text": "Python/FastAPI backend.", "domain": "acme.ai",
                                       "status": "matched"})
    lead2 = repo.add_lead(user["id"], {"company": "Beta Labs", "role": "Platform Engineer",
                                       "jd_text": "Go and Kubernetes platform.", "domain": "beta.dev",
                                       "status": "matched"})

    with patch("skills.find_contact_email.find_contact_email_for_lead",
               return_value={"contact_email": "founder@acme.ai", "contact_name": "Ada"}), \
         patch("skills.find_contact_email.HUNTER_API_KEY", "k", create=True), \
         patch("skills.find_contact_email.APOLLO_API_KEY", "k", create=True), \
         patch("skills.tailor_resume.tailor_resume", return_value={"name": "Cand", "skills": {}}), \
         patch("skills.tailor_resume.load_base_resume", return_value={"name": "Cand"}), \
         patch("skills.tailor_resume.save_resume", return_value="resume_slug"), \
         patch("skills.tailor_resume.keyword_coverage", return_value=50.0), \
         patch("skills.tailor_resume.backfill_pdfs", return_value=None), \
         patch("skills.research_company.research_company", return_value={"overview": "x", "demo_project": {}}), \
         patch("skills.llm_client.llm_generate", return_value="Subject: Hi\n\nHello."), \
         patch("skills.draft_outreach.load_tailored_resume", return_value={"name": "Cand"}), \
         patch("graph.pipeline.load_tailored_resume", create=True, return_value={"name": "Cand"}):
        summary = run_pipeline_for_leads(user_id=user["id"], lead_ids=[lead1["id"], lead2["id"]])

    assert summary["failed"] == 0

    for lid in (lead1["id"], lead2["id"]):
        lead = repo.get_lead(user["id"], lid)
        assert lead["contact_email"] == "founder@acme.ai"
        assert lead["resume_version"] == "resume_slug"
        assert (lead["outreach_draft"] or "").startswith("Subject:")
        # feed_graph flips pending_review -> in_review once fed into the graph.
        assert lead["status"] in ("pending_review", "in_review")
