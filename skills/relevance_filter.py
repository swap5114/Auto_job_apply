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

    Coarse, keyword-based heuristic -- not perfect. A JD saying "1-3 years"
    can get caught by the years-of-experience check, and a lead with no
    role/title (e.g. X leads) is checked on jd_text alone.
    """
    criteria = load_criteria()

    title = (lead.get("role") or "").lower()
    jd_text = (lead.get("jd_text") or "").lower()
    combined = f"{title} {jd_text}"

    role_keywords = criteria.get("role_keywords", [])
    if role_keywords and not any(_contains_keyword(combined, kw) for kw in role_keywords):
        return False

    seniority_keywords = criteria.get("seniority_exclude_keywords", [])
    if any(_contains_keyword(combined, kw) for kw in seniority_keywords):
        return False

    threshold = criteria.get("years_experience_threshold")
    if threshold is not None:
        for match in re.finditer(r"(\d+)\+?\s*years", jd_text):
            if int(match.group(1)) >= threshold:
                return False

    return True
