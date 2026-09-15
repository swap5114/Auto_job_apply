"""Tests for the Resume-page backend endpoints: base resume, live JD rephrase
(preview, no persist), and tailored history. Hermetic — the LLM is mocked."""

import pytest
from unittest.mock import patch

import db.current_user as cu
from db import repository as repo
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app

client = TestClient(app)
client.headers.update({"Authorization": "Bearer test-token"})


@pytest.fixture(autouse=True)
def _mock_firebase_token():
    with patch(
        "api.auth.firebase_auth.verify_id_token",
        return_value={"uid": cu.LOCAL_USER_FIREBASE_UID, "email": cu._default_email()},
    ):
        yield


def _reset() -> str:
    cu.reset_cache()
    api_main._invalidate_leads_cache()
    return cu.get_current_user_id()


_BASE = {
    "name": "Real Candidate",
    "contact": {"email": "real@example.com", "github": "https://github.com/realcandidate"},
    "summary": "Backend engineer.",
    "experience": [{"company": "TrueCorp", "title": "Engineer", "bullets": ["Built Python APIs"]}],
    "projects": [],
    "education": [],
    "skills": {"Languages": ["Python"]},
    "certifications": [],
}


def test_base_resume_none_when_no_resume():
    _reset()
    resp = client.get("/api/resume/base")
    assert resp.status_code == 200
    assert resp.json()["has_resume"] is False


def test_base_resume_returns_primary():
    user_id = _reset()
    repo.add_resume(user_id, file_ref="r.pdf", parsed_json=_BASE, is_primary=True)
    resp = client.get("/api/resume/base")
    body = resp.json()
    assert body["has_resume"] is True
    assert body["parsed_json"]["name"] == "Real Candidate"


def test_rephrase_requires_base_resume():
    _reset()
    # The endpoint must 400 when the user has no base resume. (The test client
    # resolves to the local operator, which has a config/base_resume.json
    # fallback, so we force the no-resume path explicitly — this verifies the
    # endpoint's NoResumeError -> 400 handling, not operator identity.)
    from skills.tailor_resume import NoResumeError
    with patch("skills.tailor_resume.load_base_resume", side_effect=NoResumeError("none")):
        resp = client.post("/api/resume/rephrase", json={"jd_text": "We use Python and FastAPI."})
    assert resp.status_code == 400


def test_rephrase_returns_preview_without_persisting():
    user_id = _reset()
    repo.add_resume(user_id, file_ref="r.pdf", parsed_json=_BASE, is_primary=True)

    # Mock the tailoring LLM to return the base unchanged (valid, no fabrication).
    with patch("skills.tailor_resume.llm_generate_json", return_value=dict(_BASE)):
        resp = client.post(
            "/api/resume/rephrase",
            json={"jd_text": "Python and FastAPI backend role.", "company": "Acme",
                  "role": "Engineer", "template": "standard"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tailored_json"]["name"] == "Real Candidate"
    assert body["base_json"]["name"] == "Real Candidate"
    assert body["template"] == "standard"
    assert "keyword_coverage" in body
    assert "diff" in body and "experience" in body["diff"]
    assert "model_used" in body
    # Preview must NOT create a tailored_resumes row.
    assert repo.get_tailored_resumes(user_id) == []


def test_tailored_history_lists_versions():
    user_id = _reset()
    repo.add_tailored_resume(user_id, {
        "company": "Acme", "role": "Engineer", "tailored_json": _BASE,
        "keyword_coverage": 82.0, "pdf_key": "x.pdf", "md_key": "x.md",
        "legacy_version": "x", "source": "pipeline",
    })
    resp = client.get("/api/resume/tailored")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["company"] == "Acme"
    assert items[0]["keyword_coverage"] == 82.0
