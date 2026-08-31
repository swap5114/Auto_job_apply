"""v1 Task 12: the dashboard's data endpoints (/api/stats, /api/leads) are
strictly per-user -- two users never see each other's leads or counts."""

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
import api.main as api_main

client = TestClient(api_main.app, headers={"Authorization": "Bearer test-token"})


def _as_user(monkeypatch, uid, email):
    monkeypatch.setattr(
        "api.auth.firebase_auth.verify_id_token",
        lambda token, _uid=uid, _email=email: {"uid": _uid, "email": _email},
    )
    return repo.get_or_create_user(firebase_uid=uid, email=email)


def test_stats_and_leads_are_per_user(monkeypatch):
    # User A with two leads (one sent, one replied).
    a = _as_user(monkeypatch, "dash-a", "dasha@example.com")
    la1 = repo.add_lead(a["id"], {"company": "A One", "role": "Engineer"})
    la2 = repo.add_lead(a["id"], {"company": "A Two", "role": "Engineer"})
    repo.update_lead(a["id"], la1["id"], {"status": "sent", "contact_email": "x@a.com"})
    repo.update_lead(a["id"], la2["id"], {"status": "replied", "contact_email": "y@a.com"})
    api_main._invalidate_leads_cache(a["id"])

    a_leads = client.get("/api/leads").json()
    a_stats = client.get("/api/stats").json()
    assert {l["company"] for l in a_leads} == {"A One", "A Two"}
    assert a_stats["total"] == 2
    assert a_stats["replied"] >= 1

    # Switch to user B -- brand new, sees nothing of A's.
    b = _as_user(monkeypatch, "dash-b", "dashb@example.com")
    api_main._invalidate_leads_cache(b["id"])
    b_leads = client.get("/api/leads").json()
    b_stats = client.get("/api/stats").json()
    assert b_leads == []
    assert b_stats["total"] == 0

    # A's data is untouched.
    api_main._invalidate_leads_cache(a["id"])
    _as_user(monkeypatch, "dash-a", "dasha@example.com")
    assert client.get("/api/stats").json()["total"] == 2
