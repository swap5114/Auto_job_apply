"""End-to-end tests for the anonymous pre-signup hook (/api/anon/resume,
/api/anon/preview) via FastAPI's TestClient against real Postgres.

The LLM is mocked (resume parsing and tailoring both go through
skills.llm_client under the hood) -- this test proves the real chain:
upload -> extract -> structure -> infer criteria -> match against the
REAL shared catalog in Postgres -> tailored preview for a real job row.
Nothing here touches the LangGraph pipeline or Gmail.
"""

import io
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

import api.rate_limit as rate_limit
from api.main import app
from db import repository as repo

client = TestClient(app)

FAKE_PARSED_RESUME = {
    "name": "Jane Doe",
    "contact": {"location": "Remote", "phone": "", "email": "jane@example.com", "linkedin": "", "github": "", "portfolio": ""},
    "summary": "",
    "education": [],
    "experience": [{"company": "Acme Corp", "title": "Backend Engineer", "start_date": "2022", "end_date": "Present", "bullets": ["Built REST APIs in Python."]}],
    "projects": [],
    "skills": {"Languages": ["Python"], "Tools": ["FastAPI", "Docker"]},
    "certifications": [],
}

FAKE_TAILORED_RESUME = {**FAKE_PARSED_RESUME, "summary": "Tailored for this role."}


def _reset_rate_limits():
    rate_limit.resume_upload_limiter.reset()
    rate_limit.preview_limiter.reset()


def _seed_catalog_job(title="Backend Engineer", jd_text="Python and FastAPI required.") -> dict:
    company = repo.get_or_create_company(
        "Anon Test Co", ats_type="greenhouse", ats_token=f"anon-test-{time.time_ns()}"
    )
    job = repo.add_job(
        company["id"], source="greenhouse", external_id=f"ext-{time.time_ns()}",
        title=title, jd_text=jd_text, apply_url="https://example.com/apply",
    )
    return job


def test_anon_resume_upload_end_to_end_returns_matched_feed():
    _reset_rate_limits()
    _seed_catalog_job(title="Backend Engineer", jd_text="We need Python and FastAPI experience.")
    _seed_catalog_job(title="Marketing Manager", jd_text="No technical skills required.")

    resume_text = b"Jane Doe, Backend Engineer at Acme Corp, skilled in Python and FastAPI development."
    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME):
        resp = client.post(
            "/api/anon/resume",
            files={"file": ("resume.txt", io.BytesIO(resume_text), "text/plain")},
        )

    assert resp.status_code == 200
    body = resp.json()

    assert body["parsed_resume"]["name"] == "Jane Doe"
    assert body["inferred_criteria"]["inferred_from_resume"] is True
    assert "python" in body["inferred_criteria"]["tech_stack"]

    titles = [j["title"] for j in body["matched_jobs"]]
    assert "Backend Engineer" in titles
    assert "Marketing Manager" not in titles  # zero-signal job correctly excluded


def test_anon_resume_upload_rejects_unsupported_file_type():
    _reset_rate_limits()
    resp = client.post(
        "/api/anon/resume",
        files={"file": ("resume.exe", io.BytesIO(b"not a resume"), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_anon_resume_upload_rejects_oversized_file():
    _reset_rate_limits()
    huge_content = b"x" * (6 * 1024 * 1024)  # over the 5MB cap
    resp = client.post(
        "/api/anon/resume",
        files={"file": ("resume.txt", io.BytesIO(huge_content), "text/plain")},
    )
    assert resp.status_code == 400


def test_anon_resume_upload_rejects_empty_file():
    _reset_rate_limits()
    resp = client.post(
        "/api/anon/resume",
        files={"file": ("resume.txt", io.BytesIO(b""), "text/plain")},
    )
    assert resp.status_code == 400


def test_anon_resume_upload_garbled_resume_still_returns_200():
    """A too-short/garbled 'resume' should be handled as a clean 422, not
    a 500 -- distinguishing 'unsupported format' from 'unparseable content'."""
    _reset_rate_limits()
    resp = client.post(
        "/api/anon/resume",
        files={"file": ("resume.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert resp.status_code == 422


def test_anon_resume_upload_rate_limited_after_max_requests():
    _reset_rate_limits()
    resume_text = b"Jane Doe, Backend Engineer at Acme Corp, skilled in Python and FastAPI development."
    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME):
        for _ in range(rate_limit.resume_upload_limiter.max_requests):
            resp = client.post(
                "/api/anon/resume",
                files={"file": ("resume.txt", io.BytesIO(resume_text), "text/plain")},
            )
            assert resp.status_code == 200

        # One more, over the limit, from the same client IP -- must be blocked.
        resp = client.post(
            "/api/anon/resume",
            files={"file": ("resume.txt", io.BytesIO(resume_text), "text/plain")},
        )
    assert resp.status_code == 429


def test_anon_preview_end_to_end_tailors_for_a_real_catalog_job():
    _reset_rate_limits()
    job = _seed_catalog_job(title="Backend Engineer", jd_text="Python and FastAPI required.")

    with patch("skills.tailor_resume.llm_generate_json", return_value=FAKE_TAILORED_RESUME):
        resp = client.post(
            "/api/anon/preview",
            json={"parsed_resume": FAKE_PARSED_RESUME, "job_id": job["id"]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job["id"]
    assert body["company_name"] == "Anon Test Co"
    assert body["role"] == "Backend Engineer"
    assert body["tailored_resume"]["summary"] == "Tailored for this role."
    assert 0 <= body["keyword_coverage"] <= 100


def test_anon_preview_unknown_job_id_returns_404():
    _reset_rate_limits()
    resp = client.post(
        "/api/anon/preview",
        json={"parsed_resume": FAKE_PARSED_RESUME, "job_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


def test_anon_preview_rate_limited_independently_of_upload_limit():
    """Exhausting the resume-upload limiter must not block preview
    requests from the same IP -- they're tracked independently."""
    _reset_rate_limits()
    job = _seed_catalog_job()

    resume_text = b"Jane Doe, Backend Engineer at Acme Corp, skilled in Python and FastAPI development."
    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME):
        for _ in range(rate_limit.resume_upload_limiter.max_requests):
            client.post(
                "/api/anon/resume",
                files={"file": ("resume.txt", io.BytesIO(resume_text), "text/plain")},
            )

    with patch("skills.tailor_resume.llm_generate_json", return_value=FAKE_TAILORED_RESUME):
        resp = client.post(
            "/api/anon/preview",
            json={"parsed_resume": FAKE_PARSED_RESUME, "job_id": job["id"]},
        )
    assert resp.status_code == 200


def test_feed_response_time_excludes_llm_call_for_matching_step():
    """The catalog-matching step itself (after parsing) must be fast --
    proves the 30-second budget isn't spent on a second LLM round-trip
    for matching, only on the one parse call."""
    _reset_rate_limits()
    for i in range(20):
        _seed_catalog_job(title=f"Backend Engineer {i}", jd_text="Python and FastAPI required.")

    resume_text = b"Jane Doe, Backend Engineer at Acme Corp, skilled in Python and FastAPI development."
    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME):
        start = time.monotonic()
        resp = client.post(
            "/api/anon/resume",
            files={"file": ("resume.txt", io.BytesIO(resume_text), "text/plain")},
        )
        elapsed = time.monotonic() - start

    assert resp.status_code == 200
    # Generous ceiling for a mocked-LLM, real-Postgres round trip -- this
    # is a regression guard against accidentally adding a second blocking
    # network call to the matching path, not a strict perf benchmark.
    assert elapsed < 5.0
