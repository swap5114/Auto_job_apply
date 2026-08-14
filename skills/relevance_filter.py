import json
import os
import re

CRITERIA_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "search_criteria.json")


def load_criteria() -> dict:
    with open(CRITERIA_PATH) as f:
        return json.load(f)


def _contains_keyword(text: str, keyword: str) -> bool:
    """Whole-word match, not substring -- 'ai' must not match inside
    'maintain' or 'email'. This was a real bug: plain `keyword in text`
    let completely unrelated jobs (accounting, landscape architecture)
    through the filter just because their text happened to contain 'ai'
    as a substring of an ordinary word."""
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, text) is not None


def matches_criteria(lead: dict) -> bool:
    """Returns True if the lead matches the user's job-search criteria.

    STRICT filter: requires BOTH a specific software role keyword AND a tech stack keyword.
    This prevents matching non-software roles like "operations engineer" or "business developer".
    """
    criteria = load_criteria()

    title = (lead.get("role") or "").lower()
    jd_text = (lead.get("jd_text") or "").lower()
    combined = f"{title} {jd_text}"

    # MUST match at least one specific software role keyword
    role_keywords = criteria.get("role_keywords", [])
    has_role_keyword = any(_contains_keyword(combined, kw) for kw in role_keywords)
    
    # MUST match at least one tech stack keyword (programming language, framework, tool)
    tech_keywords = criteria.get("tech_stack_keywords", [])
    has_tech_keyword = any(_contains_keyword(combined, kw) for kw in tech_keywords)
    
    # BOTH required - this is the key change
    if not (has_role_keyword and has_tech_keyword):
        return False

    # Exclude senior/lead roles
    seniority_keywords = criteria.get("seniority_exclude_keywords", [])
    if any(_contains_keyword(combined, kw) for kw in seniority_keywords):
        return False

    # Exclude non-tech roles (operations, business, sales, etc.)
    non_tech_keywords = criteria.get("non_tech_exclude_keywords", [])
    if any(_contains_keyword(combined, kw) for kw in non_tech_keywords):
        return False

    # Exclude roles requiring too much experience
    threshold = criteria.get("years_experience_threshold")
    if threshold is not None:
        for match in re.finditer(r"(\d+)\+?\s*years", jd_text):
            if int(match.group(1)) >= threshold:
                return False

    return True
