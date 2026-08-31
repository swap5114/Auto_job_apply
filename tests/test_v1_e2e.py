"""v1 Task 15: end-to-end happy path through the real API + orchestration,
with every external boundary mocked (resume parse, LLM tailor/draft, contact
lookup, Gmail send, reply check).

Flow:
  hero chat match (YC) -> save matched job as lead -> run_pipeline_for_leads
  -> lead reaches review with a draft -> approve (Gmail connected, direct)
  -> lead is "sent" -> simulate a reply -> dashboard stats show sent + replied.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
import api.main as api_main
import skills.parse_resume as parse_resume
import skills.send_via_gmail as sg
import skills.track_followups as tf
from orchestrator.pipeline_runner import run_pipeline_for_leads
from orchestrator.check_followups import check_and_queue_followups

client = TestClient(api_main.app, headers={"Authorization": "Bearer test-token"})

_UID = "e2e-user"
_EMAIL = "e2e@example.com"

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_PROJECT_ROOT, "config", "base_resume.json"), encoding="utf-8") as f:
    _BASE_RESUME = json.load(f)


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(
        "api.auth.firebase_auth.verify_id_token",
        lambda token: {"uid": _UID, "email": _EMAIL},
    )
    monkeypatch.setattr(
        parse_resume, "parse_resume_cached",
        lambda content, filename, content_type: (_BASE_RESUME, "raw"),
    )
    yield


def _seed_yc_job():
    import time
    company = repo.get_or_create_company("E2E Labs", ats_type="yc", ats_token=f"e2e-{time.time_ns()}")
    return repo.add_job(
        company["id"], source="yc", external_id=f"e2e-{time.time_ns()}",
        title="Backend Engineer @ E2E Labs",
        jd_text="We build a Python and FastAPI backend. Postgres, infrastructure, APIs.",
        apply_url="https://e2elabs.ai",
    )


def test_full_v1_happy_path(monkeypatch):
    user = repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    _seed_yc_job()

    # 1. Hero chat match -> returns the YC startup.
    resp = client.post(
        "/api/chat/match",
        files={"file": ("resume.pdf", b"%PDF", "application/pdf")},
        data={"target": "python backend infrastructure"},
    )
    assert resp.status_code == 200, resp.text
    matched = resp.json()["matched_jobs"]
    assert any(m["company_name"] == "E2E Labs" for m in matched)
    job_id = next(m["id"] for m in matched if m["company_name"] == "E2E Labs")

    # 2. Save the matched job as an outreach lead (domain derived from apply_url).
    save = client.post(f"/api/jobs/{job_id}/save", json={})
    assert save.status_code == 200
    lead = save.json()
    lead_id = lead["id"]
    assert lead["channel"] == ["outreach"]
    assert lead["status"] == "matched"

    # 3. Process the saved lead through to the review queue (mock externals).
    with patch("skills.find_contact_email.find_contact_email_for_lead",
               return_value={"contact_email": "founder@e2elabs.ai", "contact_name": "Ada"}), \
         patch("skills.find_contact_email.HUNTER_API_KEY", "k", create=True), \
         patch("skills.find_contact_email.APOLLO_API_KEY", "k", create=True), \
         patch("skills.tailor_resume.tailor_resume", return_value={"name": "Cand", "skills": {}}), \
         patch("skills.tailor_resume.load_base_resume", return_value={"name": "Cand"}), \
         patch("skills.tailor_resume.save_resume", return_value="e2e_resume"), \
         patch("skills.tailor_resume.keyword_coverage", return_value=60.0), \
         patch("skills.tailor_resume.backfill_pdfs", return_value=None), \
         patch("skills.research_company.research_company",
               return_value={"overview": "x", "demo_project": {"title": "Idea", "why_it_matters": "value"}}), \
         patch("skills.llm_client.llm_generate", return_value="Subject: An idea for E2E Labs\n\nHi Ada — one thing I'd love to explore..."), \
         patch("skills.draft_outreach.load_tailored_resume", return_value={"name": "Cand"}):
        run_pipeline_for_leads(user_id=user["id"], lead_ids=[lead_id])

    api_main._invalidate_leads_cache(user["id"])
    after_process = client.get(f"/api/leads/{lead_id}").json()
    assert after_process["contact_email"] == "founder@e2elabs.ai"
    assert after_process["resume_version"] == "e2e_resume"
    assert after_process["outreach_draft"].startswith("Subject:")
    assert after_process["status"] in ("pending_review", "in_review")

    # 4. Connect Gmail (direct send) and approve -> lead is sent from the user's inbox.
    repo.upsert_gmail_account(user["id"], "me@gmail.com", "enc-token", send_mode="direct")
    fake_service = MagicMock()
    with patch("skills.send_via_gmail.get_user_send_context",
               return_value=(fake_service, "me@gmail.com", "direct")), \
         patch("skills.send_via_gmail.send_email", return_value={"id": "sent-1"}), \
         patch("skills.send_via_gmail.resume_pdf_path", return_value=""):
        approve = client.post(f"/api/leads/{lead_id}/approve")
    assert approve.status_code == 200

    api_main._invalidate_leads_cache(user["id"])
    after_approve = client.get(f"/api/leads/{lead_id}").json()
    assert after_approve["status"] == "sent"

    # 5. Simulate a reply -> lead becomes "replied".
    monkeypatch.setattr(tf, "get_gmail_service", lambda user_id=None: MagicMock())
    monkeypatch.setattr(tf, "check_thread_for_reply", lambda service, email, after: True)
    check_and_queue_followups(user_id=user["id"])

    api_main._invalidate_leads_cache(user["id"])
    final = client.get(f"/api/leads/{lead_id}").json()
    assert final["status"] == "replied"
    assert final["replied_at"]

    # 6. Dashboard stats reflect the journey.
    stats = client.get("/api/stats").json()
    assert stats["replied"] >= 1
