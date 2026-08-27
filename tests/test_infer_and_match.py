"""Tests for skills/infer_criteria.py and skills/match_jobs.py -- the two
pure-function (no LLM) steps between a parsed resume and the anonymous
matched-jobs feed.
"""

from skills.infer_criteria import infer_criteria
from skills.match_jobs import match_jobs, score_job


def _resume(title="", skills=None, location="", projects=None):
    return {
        "name": "Test Candidate",
        "contact": {"location": location},
        "experience": [{"company": "X", "title": title, "bullets": []}] if title else [],
        "skills": skills or {},
        "projects": projects or [],
    }


# ---------------------------------------------------------------------------
# infer_criteria
# ---------------------------------------------------------------------------


def test_infer_criteria_extracts_role_from_title():
    resume = _resume(title="Backend Engineer")
    criteria = infer_criteria(resume)
    assert "backend engineer" in criteria["roles"]


def test_infer_criteria_extracts_tech_stack_from_skills():
    resume = _resume(skills={"Languages": ["Python", "TypeScript"], "Frameworks": ["React", "Django"]})
    criteria = infer_criteria(resume)
    for kw in ("python", "typescript", "react", "django"):
        assert kw in criteria["tech_stack"]


def test_infer_criteria_extracts_tech_stack_from_project_tech_stack_field():
    """A resume with no Skills section but real tech listed under a
    project should still surface that tech -- common for new-grad resumes."""
    resume = _resume(projects=[{"name": "X", "tech_stack": ["Kubernetes", "Docker"]}])
    criteria = infer_criteria(resume)
    assert "kubernetes" in criteria["tech_stack"]
    assert "docker" in criteria["tech_stack"]


def test_infer_criteria_no_false_positive_substring_match():
    """Regression guard for the exact bug class relevance_filter.py already
    had to fix: 'ai' must not match inside 'maintain' or 'email'."""
    resume = _resume(skills={"Tools": ["Gmail maintenance", "Container maintenance"]})
    criteria = infer_criteria(resume)
    assert "ai" not in criteria["tech_stack"]


def test_infer_criteria_detects_seniority_from_title():
    junior = infer_criteria(_resume(title="Software Engineer"))
    senior = infer_criteria(_resume(title="Senior Software Engineer"))
    assert junior["seniority"] == "entry_to_mid"
    assert senior["seniority"] == "senior"


def test_infer_criteria_no_experience_defaults_entry_to_mid():
    """A resume with no work experience yet (new grad, projects-only)
    must not crash or produce an empty/None seniority that would break
    downstream filtering."""
    resume = _resume()
    criteria = infer_criteria(resume)
    assert criteria["seniority"] == "entry_to_mid"
    assert criteria["roles"] == []  # no title to extract a role signal from


def test_infer_criteria_always_includes_remote_location():
    resume = _resume(location="Austin, TX")
    criteria = infer_criteria(resume)
    assert "remote" in criteria["locations"]
    assert "Austin, TX" in criteria["locations"]


def test_infer_criteria_location_remote_not_duplicated():
    resume = _resume(location="Remote")
    criteria = infer_criteria(resume)
    assert criteria["locations"].count("remote") == 1


def test_infer_criteria_marks_inferred_from_resume_true():
    criteria = infer_criteria(_resume(title="Backend Engineer"))
    assert criteria["inferred_from_resume"] is True


# ---------------------------------------------------------------------------
# match_jobs
# ---------------------------------------------------------------------------


def _job(title, jd_text="", posted_at=None):
    return {"id": title, "title": title, "jd_text": jd_text, "posted_at": posted_at}


def _criteria(roles=None, tech_stack=None, seniority="entry_to_mid"):
    return {"roles": roles or [], "tech_stack": tech_stack or [], "seniority": seniority}


def test_match_jobs_true_positive():
    criteria = _criteria(roles=["backend engineer"], tech_stack=["python", "fastapi"])
    jobs = [_job("Backend Engineer", "We use Python and FastAPI.")]
    matched = match_jobs(jobs, criteria)
    assert len(matched) == 1


def test_match_jobs_excludes_zero_signal_jobs():
    """A job matching nothing (no tech, no role signal) must be excluded
    -- this is the one hard filter in an otherwise scored/ranked system."""
    criteria = _criteria(roles=["backend engineer"], tech_stack=["python"])
    jobs = [_job("Marketing Manager", "No tech skills needed, just charisma.")]
    matched = match_jobs(jobs, criteria)
    assert matched == []


def test_match_jobs_avoids_ai_inside_maintain_false_positive():
    """Regression guard for the known false-positive bug class: a JD
    that happens to contain 'maintain' or 'email' must not register as
    an 'ai' tech-stack match."""
    criteria = _criteria(tech_stack=["ai"])
    jobs = [_job("Facilities Technician", "Responsible for building maintenance and email support tickets.")]
    matched = match_jobs(jobs, criteria)
    assert matched == []


def test_match_jobs_excludes_senior_titles_for_entry_to_mid_candidate():
    criteria = _criteria(roles=["backend engineer"], tech_stack=["python"], seniority="entry_to_mid")
    jobs = [_job("Staff Backend Engineer", "Python, 10+ years required.")]
    matched = match_jobs(jobs, criteria)
    assert matched == []


def test_match_jobs_does_not_exclude_senior_titles_for_senior_candidate():
    criteria = _criteria(roles=["backend engineer"], tech_stack=["python"], seniority="senior")
    jobs = [_job("Staff Backend Engineer", "Python, 10+ years required.")]
    matched = match_jobs(jobs, criteria)
    assert len(matched) == 1


def test_match_jobs_ranks_by_score_descending():
    criteria = _criteria(roles=["backend engineer"], tech_stack=["python", "fastapi", "docker"])
    strong = _job("Backend Engineer", "Python, FastAPI, Docker all required.")
    weak = _job("Backend Engineer (Weak Match)", "Python only.")
    matched = match_jobs([weak, strong], criteria)
    assert matched[0]["id"] == strong["id"]  # higher-scoring job ranked first despite input order


def test_match_jobs_respects_limit():
    criteria = _criteria(tech_stack=["python"])
    jobs = [_job(f"Job {i}", "Python role.") for i in range(10)]
    matched = match_jobs(jobs, criteria, limit=3)
    assert len(matched) == 3


def test_score_job_counts_both_role_and_tech_signals():
    criteria = _criteria(roles=["backend engineer"], tech_stack=["python", "fastapi"])
    job = _job("Backend Engineer", "Python and FastAPI role.")
    assert score_job(job, criteria) == 3  # 1 role + 2 tech signals


def test_matched_signals_returns_the_actual_matched_keywords():
    from skills.match_jobs import matched_signals

    criteria = _criteria(roles=["backend engineer"], tech_stack=["python", "fastapi", "kubernetes"])
    job = _job("Backend Engineer", "We use Python and FastAPI.")

    signals = matched_signals(job, criteria)

    assert set(signals) == {"python", "fastapi", "backend engineer"}
    assert "kubernetes" not in signals


def test_matched_signals_empty_for_zero_signal_job():
    from skills.match_jobs import matched_signals

    criteria = _criteria(roles=["backend engineer"], tech_stack=["python"])
    job = _job("Marketing Manager", "No tech skills needed, just charisma.")

    assert matched_signals(job, criteria) == []
