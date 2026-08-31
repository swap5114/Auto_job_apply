"""v1 Task 9: hero chat onboarding endpoint (/api/chat/match). Parses the
attached resume, blends the target prompt, matches YC startups, persists
criteria. Resume parsing is mocked (no LLM); YC catalog seeded directly."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
import api.main as api_main
import skills.parse_resume as parse_resume

client = TestClient(api_main.app, headers={"Authorization": "Bearer test-token"})

_UID = "chat-user"
_EMAIL = "chat@example.com"

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_PROJECT_ROOT, "config", "base_resume.json"), encoding="utf-8") as f:
    _BASE_RESUME = json.load(f)


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(
        "api.auth.firebase_auth.verify_id_token",
        lambda token: {"uid": _UID, "email": _EMAIL},
    )
    # Resume parsing returns our fixture resume (no real PDF/LLM).
    monkeypatch.setattr(
        parse_resume, "parse_resume_cached",
        lambda content, filename, content_type: (_BASE_RESUME, "raw text"),
    )
    yield


def _seed_yc_job(name="ChatMatch Labs", jd="We build backend infrastructure in Python and FastAPI."):
    import time
    company = repo.get_or_create_company(name, ats_type="yc", ats_token=f"chat-{time.time_ns()}")
    return repo.add_job(
        company["id"], source="yc", external_id=f"yc-{time.time_ns()}",
        title=f"Engineering @ {name}", jd_text=jd, apply_url="https://chatmatch.ai",
    )


def test_chat_match_returns_yc_matches_and_persists_criteria():
    repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    _seed_yc_job()

    resp = client.post(
        "/api/chat/match",
        files={"file": ("resume.pdf", b"%PDF-fake", "application/pdf")},
        data={"target": "python backend infrastructure startups"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "parsed_resume" in body and "matched_jobs" in body
    names = {m["company_name"] for m in body["matched_jobs"]}
    assert "ChatMatch Labs" in names
    # Every returned match is a YC startup (v1 focus).
    assert all(m["source"] == "yc" for m in body["matched_jobs"])

    # Criteria was persisted for the user so /api/jobs/matched works afterward.
    user = repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    saved = repo.get_search_criteria(user["id"])
    assert saved is not None
    # The target prompt's keywords were blended in.
    assert "infrastructure" in (saved.get("tech_stack") or []) or "infrastructure" in (saved.get("roles") or [])


def test_chat_match_excludes_non_yc_catalog_jobs():
    repo.get_or_create_user(firebase_uid=_UID, email=_EMAIL)
    # A greenhouse (non-YC) catalog job that would otherwise match.
    import time
    gh = repo.get_or_create_company("Greenhouse Co", ats_type="greenhouse", ats_token=f"gh-{time.time_ns()}")
    repo.add_job(gh["id"], source="greenhouse", external_id=f"gh-{time.time_ns()}",
                 title="Backend Engineer", jd_text="Python and FastAPI backend.", apply_url="https://x.io")
    _seed_yc_job(name="YC Only Co")

    resp = client.post(
        "/api/chat/match",
        files={"file": ("resume.pdf", b"%PDF-fake", "application/pdf")},
        data={"target": "python backend"},
    )
    assert resp.status_code == 200
    sources = {m["source"] for m in resp.json()["matched_jobs"]}
    assert sources == {"yc"} or sources == set()  # never greenhouse
