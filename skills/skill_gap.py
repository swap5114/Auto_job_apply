"""skills/skill_gap.py — Deterministic Skill-Gap Classifier

Classifies skills found in a Job Description against a candidate's base resume
into three buckets:
  1. `existing`: Named explicitly in the candidate's Skills section.
  2. `supportedByResume`: Not in the Skills section, but demonstrated in work
     experience, project bullets, or summary text.
  3. `gap`: Mentioned in the JD requirement but completely absent from the resume.

Used prior to tailoring so the tailoring prompt can highlight existing/supported
skills while avoiding fabricating unverified `gap` skills.
"""

import re
from typing import TypedDict


class SkillGapResult(TypedDict):
    existing: list[str]
    supported_by_resume: list[str]
    gap: list[str]


# Common noise words in JD skill requirements
STOP_WORDS = {
    "a", "an", "the", "and", "or", "for", "with", "in", "on", "to", "at", "by",
    "of", "is", "are", "be", "must", "have", "has", "ability", "experience",
    "working", "knowledge", "strong", "understanding", "skills", "years", "plus",
    "preferred", "required", "work", "team", "building", "deliver", "using"
}


def _normalize_token(text: str) -> str:
    """Normalize text for fuzzy token comparison."""
    return re.sub(r"[^a-z0-9+#.]+", " ", text.lower()).strip()


def extract_jd_skill_candidates(jd_text: str) -> list[str]:
    """Extract candidate tech stack phrases, languages, tools, and frameworks from a JD text.
    
    Looks for technical terms, capitalized tech keywords, common tech buzzwords,
    and bulleted list items under requirement sections.
    """
    if not jd_text:
        return []

    candidates: set[str] = set()

    # Pattern for tech skills (e.g. React, Node.js, Python, PostgreSQL, AWS, C++, CI/CD, Docker, Kubernetes)
    tech_pattern = re.compile(
        r"\b(?:[A-Z][a-zA-Z0-9+#.]+(?:\s+[A-Z][a-zA-Z0-9+#.]+)*|SQL|AWS|GCP|AZURE|REST|API|CI/CD|CD/CI|HTML|CSS|JS|TS|AI|ML|LLM|RAG|K8s|Docker|Kubernetes|FastAPI|Django|Flask|React|Next\.js|Vue|Angular|TypeScript|Python|Go|Golang|Java|Rust|C\+\+|C#|\.NET|PostgreSQL|MySQL|MongoDB|Redis)\b"
    )

    for match in tech_pattern.finditer(jd_text):
        skill = match.group(0).strip()
        norm = _normalize_token(skill)
        if norm and len(norm) >= 2 and norm not in STOP_WORDS:
            candidates.add(skill)

    # Also scan requirements section bullets
    req_section = False
    for line in jd_text.splitlines():
        line_str = line.strip()
        if re.search(r"\b(requirements|qualifications|what you'll need|what we're looking for|skills)\b", line_str, re.I):
            req_section = True
            continue
        if req_section and (line_str.startswith("-") or line_str.startswith("*") or line_str.startswith("•")):
            matches = tech_pattern.findall(line_str)
            for m in matches:
                if len(m) >= 2 and _normalize_token(m) not in STOP_WORDS:
                    candidates.add(m)

    return sorted(list(candidates), key=lambda x: len(x), reverse=True)


def classify_skill_gap(jd_text: str, base_resume: dict) -> SkillGapResult:
    """Classify JD skill requirements against a base resume.
    
    Returns a dict with 'existing', 'supported_by_resume', and 'gap'.
    """
    candidates = extract_jd_skill_candidates(jd_text)

    # Collect explicit named skills
    named_skills: set[str] = set()
    skills_data = base_resume.get("skills", {}) or {}
    if isinstance(skills_data, dict):
        for items in skills_data.values():
            if isinstance(items, list):
                for item in items:
                    named_skills.add(_normalize_token(str(item)))
            elif isinstance(items, str):
                named_skills.add(_normalize_token(items))
    elif isinstance(skills_data, list):
        for item in skills_data:
            named_skills.add(_normalize_token(str(item)))

    # Collect all prose from base resume
    full_prose = ""

    if base_resume.get("summary"):
        full_prose += " " + base_resume["summary"]

    for exp in base_resume.get("experience", []) or []:
        if exp.get("title"):
            full_prose += " " + exp["title"]
        if exp.get("company"):
            full_prose += " " + exp["company"]
        for b in exp.get("bullets", []) or []:
            full_prose += " " + str(b)

    for proj in base_resume.get("projects", []) or []:
        if proj.get("name"):
            full_prose += " " + proj["name"]
        for t in proj.get("tech_stack", []) or []:
            full_prose += " " + str(t)
        for b in proj.get("bullets", []) or []:
            full_prose += " " + str(b)

    norm_prose = _normalize_token(full_prose)

    existing: list[str] = []
    supported: list[str] = []
    gap: list[str] = []

    for cand in candidates:
        norm_cand = _normalize_token(cand)
        if not norm_cand:
            continue

        # Check existing (exact or substring overlap in named skills)
        is_existing = any(
            norm_cand == ns or norm_cand in ns or ns in norm_cand
            for ns in named_skills
        )
        if is_existing:
            existing.append(cand)
            continue

        # Check supported by resume prose
        if norm_cand in norm_prose:
            supported.append(cand)
            continue

        gap.append(cand)

    return {
        "existing": existing,
        "supported_by_resume": supported,
        "gap": gap,
    }
