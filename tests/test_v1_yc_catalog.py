"""v1 Task 8: YC startups sync into the shared catalog so match_jobs can
surface them for the hero-chat onboarding. YC API is mocked (no network)."""

from db import repository as repo
import skills.scrape_job_boards.yc_startups as yc
from skills.match_jobs import match_jobs


_FAKE_HIRING = [
    {
        "name": "Acme AI",
        "slug": "acme-ai",
        "id": 1,
        "batch": "Winter 2026",
        "isHiring": True,
        "industries": ["AI", "B2B"],
        "tags": ["Developer Tools"],
        "website": "https://acme.ai",
        "one_liner": "Python and FastAPI tooling for ML teams.",
        "long_description": "We build backend infrastructure in Python for machine learning.",
        "team_size": 12,
        "stage": "Seed",
    },
    {
        "name": "Beta Foods",  # non-tech -> filtered out by yc_matches_criteria
        "slug": "beta-foods",
        "id": 2,
        "batch": "Winter 2026",
        "isHiring": True,
        "industries": ["Food and Beverage"],
        "tags": [],
        "website": "https://betafoods.com",
        "one_liner": "Meal delivery.",
        "long_description": "We deliver food.",
    },
]


def test_run_catalog_writes_yc_jobs_and_they_are_matchable(monkeypatch):
    # run_catalog now syncs the FULL YC directory (all batches) via
    # fetch_all_companies, folding in the hiring feed for isHiring metadata.
    monkeypatch.setattr(yc, "fetch_all_companies", lambda: list(_FAKE_HIRING))
    monkeypatch.setattr(yc, "fetch_hiring_companies", lambda: list(_FAKE_HIRING))
    monkeypatch.setattr(yc, "fetch_batch_companies", lambda batch: [])

    summary = yc.run_catalog(max_companies=10)
    assert summary["provider"] == "yc"
    assert summary["added"] >= 1

    jobs = repo.get_jobs(open_only=True)
    yc_jobs = [j for j in jobs if j.get("source") == "yc"]
    assert len(yc_jobs) >= 1

    names = {repo.get_job_with_company(j["id"])["company_name"] for j in yc_jobs}
    assert "Acme AI" in names
    # Non-tech company was filtered out.
    assert "Beta Foods" not in names

    # match_jobs can surface the YC job against a python/backend resume.
    criteria = {"tech_stack": ["python", "fastapi"], "roles": ["backend"]}
    matched = match_jobs(yc_jobs, criteria)
    matched_names = {repo.get_job_with_company(j["id"])["company_name"] for j in matched}
    assert "Acme AI" in matched_names


def test_run_catalog_is_idempotent(monkeypatch):
    monkeypatch.setattr(yc, "fetch_hiring_companies", lambda: list(_FAKE_HIRING))
    monkeypatch.setattr(yc, "fetch_batch_companies", lambda batch: [])

    first = yc.run_catalog(max_companies=10)
    assert first["added"] >= 1
    second = yc.run_catalog(max_companies=10)
    # Re-running the same companies adds no new jobs (deduped on external_id).
    assert second["added"] == 0
    assert second["skipped"] >= 1
