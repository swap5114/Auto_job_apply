"""HTTP-level tests for api/main.py's leads endpoints against real Postgres.

Uses FastAPI's TestClient (in-process, no real network call) so these tests
exercise the actual route handlers -- request parsing, repo.py calls,
response serialization -- without needing a running uvicorn server. Nothing
here touches the LangGraph pipeline, Gmail, or any external API: these
routes only read/write leads directly via db.repository.
"""

import pytest
from unittest.mock import patch

import db.current_user as cu
from db import repository as repo
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app

client = TestClient(app)
# Every route these tests exercise is now behind Firebase auth (Phase 3.2)
# -- attach a bearer token to every request this client makes so existing
# assertions don't have to change one-by-one. The token's contents don't
# matter; verify_id_token is mocked below to always accept it and resolve
# to the same local-operator identity db.current_user already uses, so
# repo.add_lead(user_id, ...) calls made directly against the repo layer
# (bypassing the API) line up with the user_id the API resolves per request.
client.headers.update({"Authorization": "Bearer test-token"})


@pytest.fixture(autouse=True)
def _mock_firebase_token():
    with patch(
        "api.auth.firebase_auth.verify_id_token",
        return_value={"uid": cu.LOCAL_USER_FIREBASE_UID, "email": cu._default_email()},
    ):
        yield


def _reset() -> str:
    """Reset both the current-user cache and the API's leads TTL cache, so
    each test starts from a clean slate rather than seeing another test's
    leads through the 8-second in-process cache (api/main.py's
    _leads_cache, distinct from db.current_user's own cache).
    """
    cu.reset_cache()
    api_main._invalidate_leads_cache()
    return cu.get_current_user_id()


def test_list_leads_empty():
    _reset()
    resp = client.get("/api/leads")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_leads_returns_seeded_lead():
    user_id = _reset()
    repo.add_lead(user_id, {
        "company": "API Test Co", "role": "Engineer", "source": "arbeitnow",
        "jd_text": "test jd",
    })
    api_main._invalidate_leads_cache()

    resp = client.get("/api/leads")
    assert resp.status_code == 200
    bodies = resp.json()
    assert len(bodies) == 1
    assert bodies[0]["company"] == "API Test Co"
    assert bodies[0]["source"] == "arbeitnow"
    # followup_count is an int in Postgres (0), must come back as the string "0"
    # per LeadResponse's all-strings contract (matches the existing frontend).
    assert bodies[0]["followup_count"] == "0"


def test_get_lead_by_id():
    user_id = _reset()
    lead = repo.add_lead(user_id, {"company": "Single Co", "role": "Engineer"})
    api_main._invalidate_leads_cache()

    resp = client.get(f"/api/leads/{lead['id']}")
    assert resp.status_code == 200
    assert resp.json()["company"] == "Single Co"


def test_get_lead_not_found_returns_404():
    _reset()
    resp = client.get("/api/leads/does-not-exist")
    assert resp.status_code == 404


def test_list_leads_filters_by_status():
    user_id = _reset()
    l1 = repo.add_lead(user_id, {"company": "Filter Co A", "role": "Engineer"})
    repo.add_lead(user_id, {"company": "Filter Co B", "role": "Engineer"})
    repo.update_lead(user_id, l1["id"], {"status": "applied"})
    api_main._invalidate_leads_cache()

    resp = client.get("/api/leads", params={"status": "applied"})
    assert resp.status_code == 200
    bodies = resp.json()
    assert len(bodies) == 1
    assert bodies[0]["company"] == "Filter Co A"


def test_approve_lead_direct_fallback_when_not_in_graph():
    """This lead was never fed into feed_graph, so approve_lead must fall
    back to a direct Postgres update rather than erroring."""
    user_id = _reset()
    lead = repo.add_lead(user_id, {"company": "Approve Co", "role": "Engineer"})

    resp = client.post(f"/api/leads/{lead['id']}/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["via"] == "direct"

    updated = repo.get_lead(user_id, lead["id"])
    assert updated["status"] == "approved"
    assert updated["review_decision"] == "approved"


def test_approve_lead_not_found_returns_404():
    """A lead_id that doesn't exist (well-formed UUID or not) must produce
    a clean 404, never a raw 500 from a malformed-UUID DB error."""
    _reset()
    resp = client.post("/api/leads/does-not-exist/approve")
    assert resp.status_code == 404


def test_reject_lead_direct_fallback():
    user_id = _reset()
    lead = repo.add_lead(user_id, {"company": "Reject Co", "role": "Engineer"})

    resp = client.post(f"/api/leads/{lead['id']}/reject")
    assert resp.status_code == 200
    assert resp.json()["via"] == "direct"

    updated = repo.get_lead(user_id, lead["id"])
    assert updated["status"] == "rejected"
    assert updated["review_decision"] == "rejected"


def test_edit_lead_direct_fallback():
    user_id = _reset()
    lead = repo.add_lead(user_id, {"company": "Edit Co", "role": "Engineer"})

    resp = client.post(f"/api/leads/{lead['id']}/edit", json={"outreach_draft": "New draft text"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["via"] == "direct"
    assert body["draft_updated"] is True

    updated = repo.get_lead(user_id, lead["id"])
    assert updated["outreach_draft"] == "New draft text"
    assert updated["status"] == "approved"
    assert updated["review_decision"] == "edited"


def test_stats_reflect_seeded_leads():
    user_id = _reset()
    l1 = repo.add_lead(user_id, {"company": "Stats Co A", "role": "Engineer"})
    repo.add_lead(user_id, {"company": "Stats Co B", "role": "Engineer"})
    repo.update_lead(user_id, l1["id"], {"status": "sent"})
    api_main._invalidate_leads_cache()

    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["sent"] == 1


# ---------------------------------------------------------------------------
# Phase 5.3 -- Apply channel: save-job-as-lead, mark-applied, edit-cover-note
# ---------------------------------------------------------------------------


def _seed_catalog_job(title="Backend Engineer", jd_text="Python and FastAPI required.", apply_url="https://example.com/jobs/123/apply"):
    import time
    company = repo.get_or_create_company(
        "Save Job Test Co", ats_type="greenhouse", ats_token=f"savejob-{time.time_ns()}"
    )
    return repo.add_job(
        company["id"], source="greenhouse", external_id=f"ext-{time.time_ns()}",
        title=title, jd_text=jd_text, apply_url=apply_url,
    )


def test_save_job_as_lead_copies_apply_url_into_listing_url():
    """The job-to-lead conversion path's one hard requirement: listing_url
    must be copied straight from the catalog job's apply_url, not left
    empty or derived some other way.
    """
    user_id = _reset()
    job = _seed_catalog_job(apply_url="https://boards.greenhouse.io/acme/jobs/999")

    resp = client.post(f"/api/jobs/{job['id']}/save")
    assert resp.status_code == 200
    body = resp.json()
    assert body["listing_url"] == "https://boards.greenhouse.io/acme/jobs/999"
    assert body["job_id"] == job["id"]
    assert body["company"] == "Save Job Test Co"
    assert body["role"] == "Backend Engineer"
    assert body["channel"] == ["outreach"]  # v1 is outreach-only

    # Confirm it actually landed in Postgres, not just the response body.
    saved = repo.get_lead(user_id, body["id"])
    assert saved["listing_url"] == "https://boards.greenhouse.io/acme/jobs/999"
    assert saved["job_id"] == job["id"]


def test_save_job_as_lead_forces_outreach_channel_in_v1():
    """Even if a client requests the apply channel, v1 coerces every saved
    job to outreach (the apply channel was removed)."""
    _reset()
    job = _seed_catalog_job()

    resp = client.post(f"/api/jobs/{job['id']}/save", json={"channel": ["apply"]})
    assert resp.status_code == 200
    assert resp.json()["channel"] == ["outreach"]


def test_save_job_as_lead_unknown_job_returns_404():
    _reset()
    resp = client.post("/api/jobs/00000000-0000-0000-0000-000000000000/save")
    assert resp.status_code == 404


def test_save_job_as_lead_duplicate_returns_409():
    _reset()
    job = _seed_catalog_job()

    first = client.post(f"/api/jobs/{job['id']}/save")
    assert first.status_code == 200

    # Same company+role for the same user -- add_lead's own dedup rule.
    second = client.post(f"/api/jobs/{job['id']}/save")
    assert second.status_code == 409


def test_lead_response_exposes_channel_and_job_id():
    """LeadResponse must surface channel and job_id to the frontend."""
    user_id = _reset()
    job = _seed_catalog_job()
    lead = repo.add_lead(user_id, {
        "job_id": job["id"], "company": "Expose Co", "role": "Engineer",
        "channel": ["outreach"], "listing_url": job["apply_url"],
    })
    api_main._invalidate_leads_cache()

    resp = client.get(f"/api/leads/{lead['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == ["outreach"]
    assert body["job_id"] == job["id"]


def test_resume_pdf_route_404s_with_no_resume_version():
    user_id = _reset()
    lead = repo.add_lead(user_id, {"company": "No Resume Co", "role": "Engineer"})
    resp = client.get(f"/api/leads/{lead['id']}/resume-pdf")
    assert resp.status_code == 404


def test_resume_pdf_route_404s_lead_not_found():
    _reset()
    resp = client.get("/api/leads/does-not-exist/resume-pdf")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phase 6 -- signed-in "Matched Jobs" feed (GET /api/jobs/matched)
# ---------------------------------------------------------------------------


def test_matched_jobs_returns_empty_list_with_no_saved_criteria():
    """A brand-new account with no search_criteria row yet gets an empty
    list, not a 404/500 -- this is an expected, normal state for a
    first-time user who hasn't uploaded a resume or filled in a profile.
    """
    _reset()
    resp = client.get("/api/jobs/matched")
    assert resp.status_code == 200
    assert resp.json() == []


def test_matched_jobs_scores_and_ranks_against_saved_criteria():
    user_id = _reset()
    repo.upsert_search_criteria(user_id, {
        "roles": ["backend engineer"], "tech_stack": ["python", "fastapi"],
        "seniority": "entry_to_mid", "locations": ["remote"], "remote_pref": "remote",
        "inferred_from_resume": False,
    })
    strong = _seed_catalog_job(title="Backend Engineer", jd_text="Python and FastAPI required.")
    weak = _seed_catalog_job(title="Backend Engineer (Python only)", jd_text="Python required.")
    _seed_catalog_job(title="Marketing Manager", jd_text="No technical skills needed.")

    resp = client.get("/api/jobs/matched")
    assert resp.status_code == 200
    body = resp.json()

    ids = [j["id"] for j in body]
    assert strong["id"] in ids
    assert weak["id"] in ids
    # Marketing Manager has zero tech/role signal -- excluded entirely.
    assert len(body) == 2

    # Higher-scoring job (python + fastapi + role title) ranks first.
    assert body[0]["id"] == strong["id"]
    assert body[0]["match_score"] > body[1]["match_score"]
    assert set(body[0]["matched_signals"]) == {"python", "fastapi", "backend engineer"}


def test_matched_jobs_marks_already_saved_leads():
    user_id = _reset()
    repo.upsert_search_criteria(user_id, {
        "roles": ["backend engineer"], "tech_stack": ["python"],
        "seniority": None, "locations": [], "remote_pref": None,
        "inferred_from_resume": False,
    })
    job = _seed_catalog_job(title="Backend Engineer", jd_text="Python required.")

    # Not saved yet.
    before = client.get("/api/jobs/matched").json()
    assert before[0]["already_saved_lead_id"] is None

    save_resp = client.post(f"/api/jobs/{job['id']}/save", json={})
    assert save_resp.status_code == 200
    lead_id = save_resp.json()["id"]

    after = client.get("/api/jobs/matched").json()
    assert after[0]["already_saved_lead_id"] == lead_id
    assert after[0]["already_saved_channel"] == ["outreach"]


def test_matched_jobs_is_tenant_scoped_for_already_saved():
    """User A saving a job must never show up as 'already saved' for user B."""
    user_a = _reset()
    repo.upsert_search_criteria(user_a, {
        "roles": ["backend engineer"], "tech_stack": ["python"],
        "seniority": None, "locations": [], "remote_pref": None,
        "inferred_from_resume": False,
    })
    job = _seed_catalog_job(title="Backend Engineer", jd_text="Python required.")
    client.post(f"/api/jobs/{job['id']}/save")

    with patch(
        "api.auth.firebase_auth.verify_id_token",
        return_value={"uid": "matched-jobs-user-b", "email": "matched-b@example.com"},
    ):
        user_b_resp = client.get("/api/jobs/matched")
        assert user_b_resp.status_code == 200
        # User B has no saved criteria -- empty list, and crucially not an
        # error leaking user A's data.
        assert user_b_resp.json() == []
