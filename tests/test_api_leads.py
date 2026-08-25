"""HTTP-level tests for api/main.py's leads endpoints against real Postgres.

Uses FastAPI's TestClient (in-process, no real network call) so these tests
exercise the actual route handlers -- request parsing, repo.py calls,
response serialization -- without needing a running uvicorn server. Nothing
here touches the LangGraph pipeline, Gmail, or any external API: these
routes only read/write leads directly via db.repository.
"""

import db.current_user as cu
from db import repository as repo
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app

client = TestClient(app)


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
