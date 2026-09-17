"""tests/test_playwright_pdf.py — Unit & Integration tests for upgraded resume tailoring & Playwright PDF rendering.
"""

import pytest
from skills.skill_gap import classify_skill_gap, extract_jd_skill_candidates
from skills.verify_facts import verify_tailored_facts, extract_metrics
from skills.tailor_resume import (
    _format_markdown_bold,
    resume_to_html,
    resume_to_pdf_bytes,
    _pdf_page_count,
)


@pytest.fixture
def sample_base_resume():
    return {
        "name": "Jane Developer",
        "contact": {
            "email": "jane@example.com",
            "phone": "555-0199",
            "location": "San Francisco, CA",
            "github": "github.com/janedev",
            "linkedin": "linkedin.com/in/janedev",
        },
        "summary": "Senior Software Engineer with 6+ years of experience building high-scale Python & Node.js backend systems.",
        "skills": {
            "Languages": ["Python", "TypeScript", "SQL"],
            "Frameworks": ["FastAPI", "React", "Node.js"],
            "DevOps & Tools": ["Docker", "PostgreSQL", "AWS"],
        },
        "experience": [
            {
                "company": "Tech Corp",
                "title": "Senior Backend Engineer",
                "start_date": "2022",
                "end_date": "Present",
                "bullets": [
                    "Designed and implemented microservices reducing p99 API latency by **45%** across 12 services.",
                    "Led migration of PostgreSQL databases serving **1.5M** daily active users with zero downtime.",
                ],
            }
        ],
        "projects": [
            {
                "name": "AutoApply Engine",
                "date": "2024",
                "link": "https://github.com/janedev/autoapply",
                "tech_stack": ["Python", "FastAPI", "Docker"],
                "bullets": [
                    "Created open-source job application pipeline handling **500+** applications per hour.",
                ],
            }
        ],
        "education": [
            {
                "institution": "University of California, Berkeley",
                "degree": "B.S. Computer Science",
                "start_date": "2016",
                "end_date": "2020",
            }
        ],
    }


def test_format_markdown_bold():
    raw_text = "Reduced p99 latency from 800ms to **120 ms** across **15 services**."
    formatted = _format_markdown_bold(raw_text)
    assert "<strong>120 ms</strong>" in formatted
    assert "<strong>15 services</strong>" in formatted
    assert "&lt;" not in formatted or "<strong" in formatted


def test_extract_jd_skill_candidates():
    jd_text = """
    Requirements:
    - 5+ years experience with Python, FastAPI, and React.
    - Strong background in PostgreSQL, Kubernetes, and Docker.
    - Experience with AWS and GraphQL is a plus.
    """
    candidates = extract_jd_skill_candidates(jd_text)
    assert "Python" in candidates
    assert "FastAPI" in candidates
    assert "React" in candidates
    assert "Kubernetes" in candidates


def test_classify_skill_gap(sample_base_resume):
    jd_text = """
    Looking for a Senior Engineer with Python, FastAPI, React, and Kubernetes experience.
    """
    res = classify_skill_gap(jd_text, sample_base_resume)
    assert "Python" in res["existing"] or "FastAPI" in res["existing"]
    assert "Kubernetes" in res["gap"]


def test_verify_facts(sample_base_resume):
    # Valid tailored resume (same metrics)
    valid_tailored = dict(sample_base_resume)
    is_valid, warnings = verify_tailored_facts(sample_base_resume, valid_tailored)
    assert is_valid
    assert len(warnings) == 0

    # Fabricated metric
    fabricated_tailored = dict(sample_base_resume)
    fabricated_tailored["summary"] = "Senior Engineer with 10+ years experience generating $10M ARR."
    is_valid, warnings = verify_tailored_facts(sample_base_resume, fabricated_tailored)
    assert not is_valid
    assert any("10M" in w or "10" in w for w in warnings)


def test_resume_to_html_includes_bold_tags(sample_base_resume):
    html = resume_to_html(sample_base_resume, template="standard")
    assert "<strong>45%</strong>" in html
    assert "<strong>1.5M</strong>" in html
    assert "<style>" in html
    assert "Space Grotesk" in html


def test_resume_to_pdf_bytes(sample_base_resume):
    pdf_bytes = resume_to_pdf_bytes(sample_base_resume, template="standard")
    assert pdf_bytes is not None
    assert len(pdf_bytes) > 1000
    page_count = _pdf_page_count(pdf_bytes)
    assert page_count == 1


def test_project_link_sanitization():
    from skills.tailor_resume import sanitize_tailored

    base = {
        "name": "Swapnil Jain",
        "contact": {},
        "projects": [
            {"name": "Artha.ai", "link": "Live Link", "bullets": []},
            {"name": "AutoApply", "link": "https://outra.online/", "bullets": []},
        ],
    }
    tailored = {
        "name": "Swapnil Jain",
        "contact": {},
        "projects": [
            {"name": "Artha.ai", "link": "https://arthfx-one-sigma.vercel.app/", "bullets": []},
            {"name": "AutoApply", "link": "https://outra.online/", "bullets": []},
        ],
    }

    sanitized = sanitize_tailored(base, tailored)
    # The valid URL requested for Artha.ai should be preserved, not overwritten with 'Live Link'
    assert sanitized["projects"][0]["link"] == "https://arthfx-one-sigma.vercel.app/"
    assert sanitized["projects"][1]["link"] == "https://outra.online/"


def test_project_reordering_preserves_titles_and_bullets():
    from skills.tailor_resume import sanitize_tailored

    base = {
        "name": "Swapnil Jain",
        "projects": [
            {
                "name": "Artha.ai — AI-Powered Pre-Trade Analysis Platform",
                "date": "Jan 2026 – Present",
                "link": "https://arthfx-one-sigma.vercel.app/",
                "bullets": ["Artha bullet 1", "Artha bullet 2"],
            },
            {
                "name": "Job Application Multi-Agent Pipeline",
                "date": "2026 – Present",
                "link": "https://outra.online/",
                "bullets": ["Multi-Agent bullet 1", "Multi-Agent bullet 2"],
            },
        ],
    }

    # Tailored output reorders Job Application to index 0 and Artha.ai to index 1
    tailored = {
        "name": "Swapnil Jain",
        "projects": [
            {
                "name": "Job Application Multi-Agent Pipeline",
                "date": "2026 – Present",
                "link": "https://outra.online/",
                "bullets": ["Multi-Agent bullet 1 reworded", "Multi-Agent bullet 2 reworded"],
            },
            {
                "name": "Artha.ai — AI-Powered Pre-Trade Analysis Platform",
                "date": "Jan 2026 – Present",
                "link": "https://arthfx-one-sigma.vercel.app/",
                "bullets": ["Artha bullet 1 reworded", "Artha bullet 2 reworded"],
            },
        ],
    }

    sanitized = sanitize_tailored(base, tailored)
    # Index 0 MUST be Job Application Multi-Agent Pipeline with Multi-Agent bullets!
    assert sanitized["projects"][0]["name"] == "Job Application Multi-Agent Pipeline"
    assert sanitized["projects"][0]["bullets"] == ["Multi-Agent bullet 1 reworded", "Multi-Agent bullet 2 reworded"]
    assert sanitized["projects"][0]["link"] == "https://outra.online/"

    # Index 1 MUST be Artha.ai with Artha bullets!
    assert sanitized["projects"][1]["name"] == "Artha.ai — AI-Powered Pre-Trade Analysis Platform"
    assert sanitized["projects"][1]["bullets"] == ["Artha bullet 1 reworded", "Artha bullet 2 reworded"]
    assert sanitized["projects"][1]["link"] == "https://arthfx-one-sigma.vercel.app/"


