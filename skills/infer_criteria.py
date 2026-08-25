"""Search-criteria inference -- derives role_keywords/tech_stack_keywords/
seniority/locations from an already-parsed resume (skills/parse_resume.py's
output), with NO additional LLM call.

This is a deliberate design choice for Phase 2's 30-second anonymous hook:
the ONLY LLM call in the whole upload-to-feed path is the resume parse
itself. Criteria inference and job matching are both pure functions after
that, so the feed can render near-instantly once the resume is parsed,
with nothing else to wait on.

Inference is heuristic, not exhaustive -- it pulls signal from:
  - resume["skills"] values -> tech_stack_keywords (matched against the
    same known tech vocabulary skills/relevance_filter.py's
    config/search_criteria.json already curates, so inferred criteria
    stay compatible with the existing dual-keyword matching logic)
  - resume["experience"][].title -> role_keywords + seniority signal
  - resume["contact"]["location"] -> locations (plus "remote", always
    included since it costs nothing to also match remote roles)

The output shape matches db.models.SearchCriteria's columns
(roles/tech_stack/seniority/locations/remote_pref/inferred_from_resume)
so it can be persisted as-is once Phase 3's real accounts land -- nothing
here is anonymous-flow-specific.
"""

import json
import os
import re

CRITERIA_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "search_criteria.json")

# Known tech-stack vocabulary to match resume skills against. Sourced from
# config/search_criteria.json's own tech_stack_keywords so inferred
# criteria use the exact same vocabulary the matching step (this module's
# matches_job) and the existing relevance_filter.py both key off of.
_DEFAULT_TECH_VOCAB = [
    "react", "node", "nodejs", "node.js", "javascript", "typescript",
    "python", "django", "flask", "fastapi", "java", "spring", "kotlin",
    "ruby", "rails", "go", "golang", "rust", "mern", "mean", "vue",
    "angular", "svelte", "next.js", "nextjs", "api", "rest", "graphql",
    "microservices", "docker", "kubernetes", "aws", "gcp", "azure",
    "postgresql", "mysql", "mongodb", "redis", "c++", "c#", "swift",
    "sql", "html", "css", "tailwind", "express", "sqlalchemy",
]

# Role-title fragments that signal a software-engineering-family role,
# mapped to the canonical role_keywords vocabulary relevance_filter.py
# already uses -- so an inferred criteria set stays interoperable with the
# existing strict dual-keyword filter, not a second incompatible vocabulary.
_ROLE_TITLE_SIGNALS = [
    "software engineer", "software developer", "backend engineer",
    "backend developer", "back-end", "frontend engineer",
    "frontend developer", "front-end", "full stack", "fullstack",
    "full-stack", "web developer", "web engineer", "mobile developer",
    "app developer", "devops engineer", "site reliability engineer", "sre",
]

_SENIOR_TITLE_SIGNALS = [
    "senior", "sr.", "lead", "principal", "staff", "manager", "director",
    "head of", "vp", "chief",
]


def _load_tech_vocab() -> list[str]:
    """Prefer the live config file's vocabulary when available (keeps
    inference in sync with any hand-tuning done there), falling back to
    the built-in list so this module works standalone in tests/CI."""
    if os.path.exists(CRITERIA_PATH):
        try:
            with open(CRITERIA_PATH, encoding="utf-8") as f:
                data = json.load(f)
            vocab = data.get("tech_stack_keywords")
            if vocab:
                return vocab
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULT_TECH_VOCAB


def _contains_keyword(text: str, keyword: str) -> bool:
    """Whole-word match -- see relevance_filter.py's docstring for why
    this matters (substring matches like 'ai' inside 'maintain' are a
    real, previously-hit bug class)."""
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, text) is not None


def _extract_tech_stack(resume: dict) -> list[str]:
    vocab = _load_tech_vocab()
    skills_section = resume.get("skills") or {}

    # Flatten every skill list in the (arbitrarily-categorized) skills dict
    # into one searchable blob, plus project tech_stack entries -- resumes
    # often list real tech under "Projects" that isn't repeated in Skills.
    skill_texts = []
    for category_skills in skills_section.values():
        if isinstance(category_skills, list):
            skill_texts.extend(str(s) for s in category_skills)
    for project in resume.get("projects") or []:
        skill_texts.extend(str(t) for t in (project.get("tech_stack") or []))

    combined = " ".join(skill_texts).lower()

    found = [kw for kw in vocab if _contains_keyword(combined, kw)]
    return found


def _extract_roles_and_seniority(resume: dict) -> tuple[list[str], str | None]:
    titles = [
        (exp.get("title") or "").lower()
        for exp in (resume.get("experience") or [])
    ]
    combined = " ".join(titles)

    matched_roles = [
        signal for signal in _ROLE_TITLE_SIGNALS if _contains_keyword(combined, signal)
    ]

    is_senior = any(_contains_keyword(combined, signal) for signal in _SENIOR_TITLE_SIGNALS)
    seniority = "senior" if is_senior else "entry_to_mid"

    return matched_roles, seniority


def _extract_locations(resume: dict) -> list[str]:
    location = (resume.get("contact") or {}).get("location") or ""
    locations = ["remote"]  # always include -- costs nothing, widens the match pool
    if location.strip() and location.strip().lower() != "remote":
        locations.append(location.strip())
    return locations


def infer_criteria(resume: dict) -> dict:
    """Derive a SearchCriteria-shaped dict from a parsed resume. Pure
    function, no LLM call, no I/O beyond an optional config file read.

    Returns {"roles": [...], "tech_stack": [...], "seniority": str|None,
    "locations": [...], "remote_pref": None, "inferred_from_resume": True}.
    """
    tech_stack = _extract_tech_stack(resume)
    roles, seniority = _extract_roles_and_seniority(resume)
    locations = _extract_locations(resume)

    return {
        "roles": roles,
        "tech_stack": tech_stack,
        "seniority": seniority,
        "locations": locations,
        "remote_pref": None,
        "inferred_from_resume": True,
    }
