"""Resume parsing -- extracts raw text from an uploaded file (PDF/DOCX/plain
text), then uses the LLM to structure it into the same resume JSON shape
tailor_resume.py expects (see config/base_resume.json for the canonical
shape this must match).

This is the entry point for Phase 2's anonymous pre-signup hook: a visitor
uploads a resume, gets it parsed, and its structured form flows straight
into criteria inference (skills/infer_criteria.py) and tailoring
(skills/tailor_resume.py) without ever touching the filesystem-based
resumes/ directory that per-user tailored output uses -- this is a
one-shot parse of the CANDIDATE'S OWN base resume, not a tailored copy.

Text extraction has no LLM cost and is format-specific:
  - PDF: pypdf (already an installed dependency via xhtml2pdf)
  - DOCX: python-docx
  - .txt / pasted plain text: passed through as-is

Structuring raw text into JSON is one LLM call (Gemini Flash by policy --
see llm_client.py's MODEL_BACKEND). Results are cached by a hash of the
EXTRACTED TEXT (not the raw file bytes), so a PDF and a DOCX with
identical text content, or the same file re-uploaded, hit the cache
instead of re-spending an LLM call -- important for an anonymous,
abuse-exposed endpoint with no per-user quota to fall back on yet.
"""

import hashlib
import io
import json
import os
import re
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from skills.llm_client import llm_generate_json

# Same shape as config/base_resume.json -- kept here as a single source of
# truth for what "parsed successfully" means, so infer_criteria.py and the
# anonymous API endpoint can both validate against it without duplicating
# the shape description.
RESUME_JSON_SHAPE_DESCRIPTION = """{
  "name": "Full name",
  "contact": {
    "location": "City, Country", "phone": "", "email": "",
    "linkedin": "", "github": "", "portfolio": ""
  },
  "summary": "One or two sentence professional summary, or empty string if none present",
  "education": [
    {"institution": "", "degree": "", "start_date": "", "end_date": "", "details": ""}
  ],
  "experience": [
    {"company": "", "title": "", "start_date": "", "end_date": "", "bullets": ["..."]}
  ],
  "projects": [
    {"name": "", "date": "", "tech_stack": ["..."], "link": "", "bullets": ["..."]}
  ],
  "skills": {"CategoryName": ["skill1", "skill2"]},
  "certifications": ["..."]
}"""

SYSTEM_PROMPT = f"""You are a resume-parsing assistant. You will be given raw text extracted from a candidate's resume (a PDF or DOCX, converted to plain text -- formatting/whitespace may be imperfect). Your job is to structure this into JSON.

STRICT RULES -- violating any of these is a critical failure:
1. NEVER invent, guess, or infer any fact not literally present in the text -- no company names, dates, degrees, skills, or metrics the candidate didn't write. If a field is genuinely absent from the text, use an empty string "" or empty list [], never a plausible-sounding placeholder.
2. Preserve dates, company names, titles, and institution names EXACTLY as written -- do not normalize, abbreviate, or "correct" them.
3. Extract bullets as separate list items, not as one merged paragraph -- split on the resume's own bullet/line structure.
4. If the raw text is garbled, truncated, or clearly not a resume at all, still return valid JSON in the required shape with whatever real fields you can confidently extract, leaving the rest empty -- never fabricate to fill gaps.
5. skills should be grouped into whatever categories the resume itself uses (e.g. "Languages", "Frameworks") -- if the resume lists skills with no categories, use a single category called "Skills".

Return ONLY valid JSON in exactly this shape (no markdown code fences, no prose):
{RESUME_JSON_SHAPE_DESCRIPTION}"""


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file's extension/content-type isn't one of
    the supported formats (pdf, docx, txt/plain)."""


class ResumeParseError(Exception):
    """Raised when text extraction or LLM structuring fails outright (not
    for a low-quality/garbled resume -- that's handled by the LLM per
    SYSTEM_PROMPT rule 4, not raised as an error here)."""


# ---------------------------------------------------------------------------
# Text extraction (no LLM, format-specific)
# ---------------------------------------------------------------------------


def extract_text_from_pdf(file_bytes: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise ResumeParseError(f"Could not read PDF: {e}")

    pages_text = []
    for page in reader.pages:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception:
            continue  # a single bad page shouldn't fail the whole extract

    text = "\n".join(pages_text).strip()
    if not text:
        raise ResumeParseError(
            "No extractable text found in PDF -- it may be a scanned image "
            "without OCR text, which this parser doesn't support."
        )
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    from docx import Document

    try:
        document = Document(io.BytesIO(file_bytes))
    except Exception as e:
        raise ResumeParseError(f"Could not read DOCX: {e}")

    parts = [p.text for p in document.paragraphs if p.text.strip()]
    # Tables (common in resume templates for skills/contact layout) aren't
    # walked by .paragraphs -- pull their cell text too, or a template-based
    # resume can silently lose entire sections.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)

    text = "\n".join(parts).strip()
    if not text:
        raise ResumeParseError("No extractable text found in DOCX.")
    return text


def extract_text(file_bytes: bytes, filename: str, content_type: str = "") -> str:
    """Dispatch to the right extractor based on filename extension (primary
    signal) or content_type (fallback) -- browsers/clients are inconsistent
    about setting content_type on multipart uploads, but a filename is
    almost always present.
    """
    ext = os.path.splitext(filename or "")[1].lower()

    if ext == ".pdf" or "pdf" in content_type:
        return extract_text_from_pdf(file_bytes)
    if ext == ".docx" or "wordprocessingml" in content_type:
        return extract_text_from_docx(file_bytes)
    if ext in (".txt", "") or "text/plain" in content_type:
        try:
            return file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise ResumeParseError("Could not decode file as UTF-8 plain text.")

    raise UnsupportedFileTypeError(
        f"Unsupported file type '{ext or content_type or 'unknown'}'. "
        "Supported: .pdf, .docx, .txt, or pasted plain text."
    )


# ---------------------------------------------------------------------------
# Structuring (one LLM call, cached by extracted-text hash)
# ---------------------------------------------------------------------------


def text_hash(text: str) -> str:
    """Stable cache key for a block of resume text -- hashing the
    EXTRACTED text (not raw file bytes) means a PDF and a DOCX with
    identical content, or the same resume re-uploaded in a different
    format, share one cache entry instead of paying for the LLM call twice.
    """
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _heuristic_resume_fallback(raw_text: str) -> dict:
    """Fallback parser when LLM provider is unavailable or returns an error."""
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    name = lines[0] if lines else "Candidate"
    
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', raw_text)
    email = emails[0] if emails else ""
    
    phones = re.findall(r'\+?\d[\d\s\-\(\)]{8,}\d', raw_text)
    phone = phones[0] if phones else ""
    
    linkedin = ""
    github = ""
    urls = re.findall(r'https?://[^\s]+', raw_text)
    for url in urls:
        if "linkedin" in url.lower():
            linkedin = url
        elif "github" in url.lower():
            github = url

    known_tech = [
        "python", "react", "javascript", "typescript", "node", "nodejs", "node.js",
        "fastapi", "django", "flask", "java", "c++", "c#", "go", "golang", "rust",
        "aws", "gcp", "azure", "docker", "kubernetes", "sql", "postgresql", "mongodb",
        "redis", "graphql", "rest", "api", "html", "css", "tailwind", "next.js", "nextjs",
        "express", "vue", "angular", "svelte", "ruby", "rails"
    ]
    found_skills = []
    text_lower = raw_text.lower()
    for tech in known_tech:
        if re.search(r'\b' + re.escape(tech) + r'\b', text_lower):
            found_skills.append(tech)

    return {
        "name": name,
        "contact": {
            "location": "",
            "phone": phone,
            "email": email,
            "linkedin": linkedin,
            "github": github,
            "portfolio": ""
        },
        "summary": lines[1] if len(lines) > 1 else "",
        "education": [],
        "experience": [],
        "projects": [],
        "skills": {"Skills": found_skills},
        "certifications": []
    }


def structure_resume_text(raw_text: str) -> dict:
    """The one LLM call in this module: raw extracted text -> structured
    resume JSON. Callers should go through parse_resume_cached() instead
    of calling this directly, so repeated uploads of the same resume text
    don't repeatedly pay for this call.
    """
    if not raw_text or not raw_text.strip():
        raise ResumeParseError("No text to parse (empty input).")

    if len(raw_text.strip()) < 50:
        raise ResumeParseError(
            "Extracted text is too short to be a resume (fewer than 50 characters)."
        )

    try:
        result = llm_generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_message=f"Resume text:\n\n{raw_text}",
            max_tokens=4096,
        )
        return result
    except Exception as e:
        print(f"  ⚠️  structure_resume_text LLM call failed ({e}); falling back to heuristic parser.")
        return _heuristic_resume_fallback(raw_text)



# In-memory cache: text_hash -> parsed resume dict. Shared across all
# anonymous visitors (not per-user), same design as db.models.EnrichmentCache/
# ResearchCache -- a resume's parsed structure is a pure function of its
# text content, reusable by anyone who happens to upload identical text.
# Process-local and unbounded is an accepted tradeoff for now (mirrors
# api/main.py's existing in-memory leads cache) -- a restart clears it, and
# a truly high-traffic anonymous endpoint would move this to Postgres or
# Redis, which is out of scope for this phase.
_parse_cache: dict[str, dict] = {}


def parse_resume_cached(file_bytes: bytes, filename: str, content_type: str = "") -> tuple[dict, str]:
    """Extract text, then structure it into resume JSON, using the
    in-memory cache keyed by extracted-text hash to avoid re-spending an
    LLM call on a repeat upload.

    Returns (parsed_resume, extracted_text). extracted_text is returned
    alongside the parsed JSON because callers (the anonymous API endpoint)
    need it for the "malformed/garbled resume" acceptance test -- a
    resume that parsed to an almost-entirely-empty shape is still a valid,
    non-error outcome per this module's rules, but the raw text is useful
    for surfacing a helpful message to the visitor.
    """
    raw_text = extract_text(file_bytes, filename, content_type)
    key = text_hash(raw_text)

    if key in _parse_cache:
        return _parse_cache[key], raw_text

    parsed = structure_resume_text(raw_text)
    _parse_cache[key] = parsed
    return parsed, raw_text


def reset_cache() -> None:
    """Clear the in-memory parse cache. Used by tests."""
    _parse_cache.clear()
