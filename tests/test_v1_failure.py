"""v1 Task 11: pipeline failure handling + surfacing. Leads that can't be
processed get a failure_reason (surfaced on the dashboard); a retry clears it
and re-runs processing."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
import api.main as api_main

client = TestClient(api_main.app, headers={"Authorization": "Bearer test-token"})

_UID = "failure-user"
_EMAIL = "failure@example.com"


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(
        "api.auth.firebase_auth.verify_id_token",
        lambda token: {"uid": _UID, "email": _EMAIL},
    )
    yield


def test_find_email_flags_no_contact_found(monkeypatch):
    import skills.find_contact_email as fce

    user = repo.create_user(firebase_uid="fail-nc", email="failnc@example.com")
    lead = repo.add_lead(user["id"], {"company": "NoContact Co", "role": "Engineer"})

    monkeypatch.setattr(fce, "HUNTER_API_KEY", "k", raising=False)
    monkeypatch.setattr(fce, "APOLLO_API_KEY", "k", raising=False)
    monkeypatch.setattr(fce, "find_contact_email_for_lead",
                        lambda l: {"contact_email": None, "contact_name": None})

    fce.run(user_id=user["id"])

    refreshed = repo.get_lead(user["id"], lead["id"])
    assert refreshed["failure_reason"] == "no_contact_found"


def test_find_email_clears_failure_on_success(monkeypatch):
    import skills.find_contact_email as fce

    user = repo.create_user(firebase_uid="fail-clear", email="failclear@example.com")
    lead = repo.add_lead(user["id"], {"company": "Clear Co", "role": "Engineer"})
    repo.update_lead(user["id"], lead["id"], {"failure_reason": "no_contact_found"})

    monkeypatch.setattr(fce, "HUNTER_API_KEY", "k", raising=False)
    monkeypatch.setattr(fce, "APOLLO_API_KEY", "k", raising=False)
    monkeypatch.setattr(fce, "find_contact_email_for_lead",
                        lambda l: {"contact_email": "founder@clear.co", "contact_name": None})

    fce.run(user_id=user["id"])

    refreshed = repo.get_lead(user["id"], lead["id"])
    assert refreshed["contact_email"] == "founder@clear.co"
    assert not refreshed["failure_reason"]


def test_retry_route_clears_failure_and_starts_run(monkeypatch):
    # Don't actually run the heavy processing chain in the background thread.
    import orchestrator.pipeline_runner as pr
    monkeypatch.setattr(pr, "run_pipeline_for_leads",
                        lambda user_id=None, lead_ids=None, progress_callback=None: {"ok": 4, "failed": 0})

    user = repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    lead = repo.add_lead(user["id"], {"company": "Retry Co", "role": "Engineer"})
    repo.update_lead(user["id"], lead["id"], {"failure_reason": "tailor_failed"})
    api_main._invalidate_leads_cache(user["id"])

    resp = client.post(f"/api/leads/{lead['id']}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "retrying"

    refreshed = repo.get_lead(user["id"], lead["id"])
    assert not refreshed["failure_reason"]


def test_retry_unknown_lead_404():
    repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    resp = client.post("/api/leads/does-not-exist/retry")
    assert resp.status_code == 404


def test_lead_response_exposes_failure_reason():
    user = repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    lead = repo.add_lead(user["id"], {"company": "Surface Co", "role": "Engineer"})
    repo.update_lead(user["id"], lead["id"], {"failure_reason": "no_contact_found"})
    api_main._invalidate_leads_cache(user["id"])

    body = client.get(f"/api/leads/{lead['id']}").json()
    assert body["failure_reason"] == "no_contact_found"
