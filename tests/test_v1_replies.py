"""v1 Task 7: a detected reply ("revert") is persisted to the leads table and
surfaced on the dashboard (stats + leads API). No real Gmail calls."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
import api.main as api_main
import skills.track_followups as tf
from orchestrator.check_followups import check_and_queue_followups

client = TestClient(api_main.app, headers={"Authorization": "Bearer test-token"})

_UID = "replies-user"
_EMAIL = "replies@example.com"


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(
        "api.auth.firebase_auth.verify_id_token",
        lambda token: {"uid": _UID, "email": _EMAIL},
    )
    yield


def test_detected_reply_is_persisted_and_shown_on_dashboard(monkeypatch):
    user = repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)

    # A sent lead with a contact -- the follow-up sweep checks it for replies.
    lead = repo.add_lead(user["id"], {"company": "ReplyCo", "role": "Backend Engineer"})
    repo.update_lead(user["id"], lead["id"], {
        "status": "sent", "contact_email": "founder@replyco.com",
    })

    # Force the follow-up graph to observe a reply, with no real Gmail.
    monkeypatch.setattr(tf, "get_gmail_service", lambda user_id=None: MagicMock())
    monkeypatch.setattr(tf, "check_thread_for_reply", lambda service, email, after: True)

    check_and_queue_followups(user_id=user["id"])

    # Persisted to Postgres.
    refreshed = repo.get_lead(user["id"], lead["id"])
    assert refreshed["status"] == "replied"
    assert refreshed["replied_at"] is not None

    # Surfaced on the dashboard: stats reply counter + leads API field.
    api_main._invalidate_leads_cache(user["id"])
    stats = client.get("/api/stats").json()
    assert stats.get("replied", 0) >= 1

    lead_resp = client.get(f"/api/leads/{lead['id']}").json()
    assert lead_resp["status"] == "replied"
    assert lead_resp["replied_at"]  # non-empty ISO timestamp
