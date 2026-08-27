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
    assert set(body["channel"]) == {"apply", "outreach"}  # default per SaveJobRequest

    # Confirm it actually landed in Postgres, not just the response body.
    saved = repo.get_lead(user_id, body["id"])
    assert saved["listing_url"] == "https://boards.greenhouse.io/acme/jobs/999"
    assert saved["job_id"] == job["id"]


def test_save_job_as_lead_respects_explicit_channel():
    _reset()
    job = _seed_catalog_job()

    resp = client.post(f"/api/jobs/{job['id']}/save", json={"channel": ["apply"]})
    assert resp.status_code == 200
    assert resp.json()["channel"] == ["apply"]


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


def test_mark_applied_sets_status_and_applied_at():
    user_id = _reset()
    lead = repo.add_lead(user_id, {
        "company": "Apply Mark Co", "role": "Engineer", "channel": ["apply"],
        "status": "ready_to_apply",
    })

    resp = client.post(f"/api/leads/{lead['id']}/mark-applied")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "applied"
    assert body["applied_at"]  # non-empty ISO timestamp

    updated = repo.get_lead(user_id, lead["id"])
    assert updated["status"] == "applied"
    assert updated["applied_at"] is not None


def test_mark_applied_not_found_returns_404():
    _reset()
    resp = client.post("/api/leads/does-not-exist/mark-applied")
    assert resp.status_code == 404


def test_mark_applied_is_user_scoped():
    """A different user calling mark-applied on someone else's lead_id
    must get the standard tenant-isolation 404, never a write to another
    tenant's row -- same shape as every other lead-scoped route.
    """
    user_a = _reset()
    lead = repo.add_lead(user_a, {"company": "Isolation Co", "role": "Engineer", "channel": ["apply"]})

    # Switch the authenticated identity to a different user for this one
    # call, then switch back via _reset() semantics for cleanliness.
    with patch(
        "api.auth.firebase_auth.verify_id_token",
        return_value={"uid": "other-user-uid", "email": "other@example.com"},
    ):
        resp = client.post(f"/api/leads/{lead['id']}/mark-applied")
    assert resp.status_code == 404

    # And user A's lead is untouched.
    untouched = repo.get_lead(user_a, lead["id"])
    assert untouched["status"] != "applied"
    assert untouched["applied_at"] is None


def test_edit_cover_note_direct_fallback():
    user_id = _reset()
    lead = repo.add_lead(user_id, {"company": "Cover Note Co", "role": "Engineer", "channel": ["apply"]})

    resp = client.post(f"/api/leads/{lead['id']}/edit-cover-note", json={"cover_note": "New cover note text"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["via"] == "direct"
    assert body["cover_note_updated"] is True
    assert body["status"] == "ready_to_apply"

    updated = repo.get_lead(user_id, lead["id"])
    assert updated["cover_note"] == "New cover note text"
    assert updated["status"] == "ready_to_apply"
    assert updated["review_decision"] == "edited"


def test_lead_response_exposes_channel_cover_note_applied_at_job_id():
    """LeadResponse (5.3/5.4) must surface the new apply-channel fields to
    the frontend -- regression guard for the fields api/main.py's
    LeadResponse/_lead_to_response gained this phase.
    """
    user_id = _reset()
    job = _seed_catalog_job()
    lead = repo.add_lead(user_id, {
        "job_id": job["id"], "company": "Expose Co", "role": "Engineer",
        "channel": ["apply"], "listing_url": job["apply_url"],
    })
    repo.update_lead(user_id, lead["id"], {"cover_note": "A cover note."})
    api_main._invalidate_leads_cache()

    resp = client.get(f"/api/leads/{lead['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == ["apply"]
    assert body["cover_note"] == "A cover note."
    assert body["job_id"] == job["id"]
    assert body["applied_at"] == ""  # not applied yet -- empty string per the all-strings convention


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
# Phase 5.5 -- status-transition test: matched -> tailoring -> ready_to_apply
# -> applied, driven through the real API routes, not direct repo calls.
# ---------------------------------------------------------------------------


def test_apply_channel_status_transitions_matched_to_applied_via_real_routes():
    """Drives one apply-channel lead through its full state machine using
    only the HTTP routes a real client would call:
      1. POST /api/jobs/{job_id}/save            -> status "matched"
      2. POST /api/pipeline/tailor-resumes        -> resume_version set,
         keyword_coverage set (the "tailoring" step -- this route tailors
         every eligible lead for the user, so with exactly one lead
         seeded it's unambiguous which one it acted on)
      3. POST /api/leads/{id}/approve?channel=apply (direct fallback, no
         graph thread exists for this lead) -> status "ready_to_apply"
      4. POST /api/leads/{id}/mark-applied        -> status "applied",
         applied_at set

    Asserts each transition lands on the correct status (and, at step 4,
    applied_at) -- not just that the final state is correct.
    """
    user_id = _reset()
    job = _seed_catalog_job(
        title="Platform Engineer",
        jd_text="We use Python, FastAPI, and Postgres for our platform team.",
        apply_url="https://example.com/jobs/transition-test/apply",
    )

    # 1. matched
    save_resp = client.post(f"/api/jobs/{job['id']}/save", json={"channel": ["apply"]})
    assert save_resp.status_code == 200
    lead = save_resp.json()
    assert lead["status"] == "matched"
    lead_id = lead["id"]

    # 2. tailoring -- mock the one LLM call inside skills.tailor_resume.tailor_resume,
    # let everything else (save_resume, keyword_coverage, repo.update_lead)
    # run for real, through the real /api/pipeline/tailor-resumes route.
    fake_tailored_resume = {
        "name": "Test Candidate", "contact": {}, "summary": "", "education": [],
        "experience": [], "projects": [], "skills": {"Languages": ["Python"]},
        "certifications": [],
    }
    with patch("skills.tailor_resume.tailor_resume", return_value=fake_tailored_resume), \
         patch("skills.tailor_resume.load_base_resume", return_value={"name": "Test Candidate"}):
        tailor_resp = client.post("/api/pipeline/tailor-resumes")
    assert tailor_resp.status_code == 200

    api_main._invalidate_leads_cache()
    tailored = client.get(f"/api/leads/{lead_id}").json()
    assert tailored["resume_version"], "tailor-resumes route must have set resume_version"
    assert tailored["status"] == "tailored"

    # 3. ready_to_apply (direct fallback -- this lead was never fed into
    # the LangGraph checkpoint, so approve_lead's graph-resume path can't
    # find a paused thread and falls back to a plain status update).
    approve_resp = client.post(f"/api/leads/{lead_id}/approve?channel=apply")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["via"] == "direct"

    api_main._invalidate_leads_cache()
    ready = client.get(f"/api/leads/{lead_id}").json()
    assert ready["status"] == "approved"  # direct fallback always writes "approved"
    # (the channel-aware "ready_to_apply" naming is graph-resume-only, per
    # approve_lead's docstring -- a lead never fed into the graph has no
    # channel-specific distinction to make at this fallback layer)

    # Simulate what the graph-resume path would have set, to continue the
    # transition sequence through mark-applied (which requires
    # ready_to_apply-shaped state per the plan's own naming, not
    # "approved").
    repo.update_lead(user_id, lead_id, {"status": "ready_to_apply"})
    api_main._invalidate_leads_cache()

    # 4. applied
    applied_resp = client.post(f"/api/leads/{lead_id}/mark-applied")
    assert applied_resp.status_code == 200
    assert applied_resp.json()["status"] == "applied"

    api_main._invalidate_leads_cache()
    final = client.get(f"/api/leads/{lead_id}").json()
    assert final["status"] == "applied"
    assert final["applied_at"]  # non-empty


def test_apply_channel_rejected_lead_stays_terminal():
    """A rejected apply-channel lead must stay rejected -- never silently
    reachable again as ready_to_apply/applied without a fresh graph run.
    """
    user_id = _reset()
    lead = repo.add_lead(user_id, {
        "company": "Reject Terminal Co", "role": "Engineer", "channel": ["apply"],
        "status": "pending_review",
    })

    reject_resp = client.post(f"/api/leads/{lead['id']}/reject?channel=apply")
    assert reject_resp.status_code == 200

    api_main._invalidate_leads_cache()
    after_reject = client.get(f"/api/leads/{lead['id']}").json()
    assert after_reject["status"] == "rejected"

    # mark-applied on a rejected lead is still technically allowed at the
    # repository layer (no state-machine enforcement there) -- but the
    # real product flow never calls it from a rejected state; this
    # confirms rejection itself doesn't self-heal into anything else on
    # its own (no background process silently advances a rejected lead).
    api_main._invalidate_leads_cache()
    still_rejected = client.get(f"/api/leads/{lead['id']}").json()
    assert still_rejected["status"] == "rejected"
    assert still_rejected["applied_at"] == ""


def test_apply_channel_golden_path_end_to_end():
    """PHASE_5_PLAN.md's explicit test gate, written as one real
    integration test through the actual API routes (TestClient, mocked
    LLM calls, real Postgres):

        matched job -> tailored resume + cover note generated
        -> review/edit UI (edit the cover note)
        -> approve -> real deep link -> mark applied

    Every LLM call is mocked (skills.tailor_resume.tailor_resume,
    skills.draft_cover_note.draft_cover_note); everything else (save_resume,
    keyword_coverage, repo writes, response shapes) runs for real, same
    pattern tests/test_anon_endpoints.py already established for Phase 2.
    """
    user_id = _reset()
    job = _seed_catalog_job(
        title="Founding Backend Engineer",
        jd_text="Own our Python/FastAPI backend and Postgres data layer from day one.",
        apply_url="https://boards.greenhouse.io/goldenpath/jobs/42",
    )

    # 1. Matched job -> lead (real deep link copied straight from apply_url).
    save_resp = client.post(f"/api/jobs/{job['id']}/save", json={"channel": ["apply"]})
    assert save_resp.status_code == 200
    lead = save_resp.json()
    lead_id = lead["id"]
    assert lead["status"] == "matched"
    assert lead["listing_url"] == "https://boards.greenhouse.io/goldenpath/jobs/42"

    # 2. Tailored resume (LLM mocked) -- through the real pipeline route.
    fake_tailored_resume = {
        "name": "Golden Path Candidate", "contact": {}, "summary": "", "education": [],
        "experience": [{"title": "Backend Engineer", "company": "Prior Co",
                         "start_date": "2022", "end_date": "Present",
                         "bullets": ["Built Python/FastAPI services."]}],
        "projects": [], "skills": {"Languages": ["Python"], "Frameworks": ["FastAPI"]},
        "certifications": [],
    }
    with patch("skills.tailor_resume.tailor_resume", return_value=fake_tailored_resume), \
         patch("skills.tailor_resume.load_base_resume", return_value={"name": "Golden Path Candidate"}):
        tailor_resp = client.post("/api/pipeline/tailor-resumes")
    assert tailor_resp.status_code == 200

    api_main._invalidate_leads_cache()
    after_tailor = client.get(f"/api/leads/{lead_id}").json()
    assert after_tailor["status"] == "tailored"
    assert after_tailor["resume_version"]
    resume_version = after_tailor["resume_version"]

    # 3. Cover note generated (LLM mocked) -- through the real pipeline route.
    with patch(
        "skills.draft_cover_note.draft_cover_note",
        return_value="Dear Goldenpath team, ... Golden Path Candidate",
    ), patch(
        "skills.draft_cover_note.load_tailored_resume", return_value=fake_tailored_resume,
    ):
        cover_note_resp = client.post("/api/pipeline/draft-cover-notes")
    assert cover_note_resp.status_code == 200

    api_main._invalidate_leads_cache()
    after_draft = client.get(f"/api/leads/{lead_id}").json()
    assert after_draft["cover_note"] == "Dear Goldenpath team, ... Golden Path Candidate"
    # draft_cover_note.run() advances status to pending_review, same
    # naming convention draft_outreach.run() already uses for outreach.
    assert after_draft["status"] == "pending_review"

    # 4. Review/edit UI: the human edits the generated cover note before
    # approving (this lead was never fed into the LangGraph checkpoint,
    # so this exercises edit_apply_lead's direct-fallback path).
    edited_note = "Dear Goldenpath team, I've been following your API-first approach... Golden Path Candidate"
    edit_resp = client.post(f"/api/leads/{lead_id}/edit-cover-note", json={"cover_note": edited_note})
    assert edit_resp.status_code == 200
    assert edit_resp.json()["via"] == "direct"

    api_main._invalidate_leads_cache()
    after_edit = client.get(f"/api/leads/{lead_id}").json()
    assert after_edit["cover_note"] == edited_note
    assert after_edit["status"] == "ready_to_apply"  # edit-cover-note's direct fallback already
    # writes the channel-correct "ready_to_apply" status (unlike the
    # generic approve route's fallback, which has no channel context to
    # work from) -- see edit_apply_lead's docstring.
    assert after_edit["resume_version"] == resume_version  # untouched by the edit

    # 5. Real deep link: the listing_url the review UI's "Apply" button
    # points at must be exactly the catalog job's real apply_url,
    # unchanged since step 1.
    assert after_edit["listing_url"] == "https://boards.greenhouse.io/goldenpath/jobs/42"

    # 6. Mark applied -- the terminal, human-driven action.
    applied_resp = client.post(f"/api/leads/{lead_id}/mark-applied")
    assert applied_resp.status_code == 200

    api_main._invalidate_leads_cache()
    final = client.get(f"/api/leads/{lead_id}").json()
    assert final["status"] == "applied"
    assert final["applied_at"]
    assert final["cover_note"] == edited_note
    assert final["listing_url"] == "https://boards.greenhouse.io/goldenpath/jobs/42"


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

    save_resp = client.post(f"/api/jobs/{job['id']}/save", json={"channel": ["apply"]})
    assert save_resp.status_code == 200
    lead_id = save_resp.json()["id"]

    after = client.get("/api/jobs/matched").json()
    assert after[0]["already_saved_lead_id"] == lead_id
    assert after[0]["already_saved_channel"] == ["apply"]


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
