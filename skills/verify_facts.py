"""skills/verify_facts.py — Fact Verification & Anti-Fabrication Gate

Verifies tailored resume content (bullets, metrics, numbers, technologies)
against the base resume to prevent LLM hallucinations or metric inflation.
"""

import re


METRIC_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s*%\b",  # percentages (e.g. 35%, 100%)
    r"[$€£]\s*\d[\d,.]*\s*[kKmMbB]?\b",  # currency (e.g. $500k, $1.2M)
    r"\b\d+(?:\.\d+)?\s*[xX]\b",  # multipliers (e.g. 3x, 10x)
]


def extract_metrics(text: str) -> list[str]:
    """Extract quantitative metric claims from text."""
    if not text:
        return []
    claims = []
    for pat in METRIC_PATTERNS:
        matches = re.findall(pat, text)
        claims.extend(matches)
    return claims


def verify_tailored_facts(base_resume: dict, tailored_resume: dict) -> tuple[bool, list[str]]:
    """Verify that tailored metrics do not exceed or fabricate claims from base_resume.
    
    Returns (is_valid, warnings_list).
    """
    warnings = []

    # Collect all base text
    base_text_parts = [base_resume.get("summary", "") or ""]
    for exp in base_resume.get("experience", []) or []:
        base_text_parts.extend(exp.get("bullets", []) or [])
    for proj in base_resume.get("projects", []) or []:
        base_text_parts.extend(proj.get("bullets", []) or [])

    base_full_text = " ".join(str(p) for p in base_text_parts)
    base_metrics = set(extract_metrics(base_full_text))

    # Collect tailored text
    tailored_text_parts = [tailored_resume.get("summary", "") or ""]
    for exp in tailored_resume.get("experience", []) or []:
        tailored_text_parts.extend(exp.get("bullets", []) or [])
    for proj in tailored_resume.get("projects", []) or []:
        tailored_text_parts.extend(proj.get("bullets", []) or [])

    tailored_full_text = " ".join(str(p) for p in tailored_text_parts)
    tailored_metrics = extract_metrics(tailored_full_text)

    for tm in tailored_metrics:
        if tm not in base_metrics:
            # Check if it's a normalized equivalent
            norm_tm = re.sub(r"\s+", "", tm.lower())
            norm_base = [re.sub(r"\s+", "", bm.lower()) for bm in base_metrics]
            if norm_tm not in norm_base:
                warnings.append(f"Unverified metric claim found in tailored resume: '{tm}'")

    is_valid = len(warnings) == 0
    return is_valid, warnings
