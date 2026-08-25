"""Tests for skills/parse_resume.py -- text extraction across PDF/DOCX/
plain text, and the LLM-structuring step (mocked -- no real LLM calls).

Real PDF/DOCX fixtures are generated in-test (via xhtml2pdf, already a
project dependency, and python-docx) rather than checked-in binary files,
so the fixtures are inspectable as plain Python strings in this file.
"""

import io
from unittest.mock import patch

import pytest

from skills.parse_resume import (
    ResumeParseError,
    UnsupportedFileTypeError,
    extract_text,
    extract_text_from_docx,
    extract_text_from_pdf,
    parse_resume_cached,
    reset_cache,
    structure_resume_text,
    text_hash,
)

SAMPLE_RESUME_TEXT = """Jane Doe
Backend Engineer

Experience:
Acme Corp - Backend Engineer (2022-Present)
- Built REST APIs in Python and FastAPI
- Deployed services on AWS using Docker

Skills: Python, FastAPI, Docker, AWS, PostgreSQL
"""

FAKE_PARSED_RESUME = {
    "name": "Jane Doe",
    "contact": {"location": "Remote", "phone": "", "email": "", "linkedin": "", "github": "", "portfolio": ""},
    "summary": "",
    "education": [],
    "experience": [{"company": "Acme Corp", "title": "Backend Engineer", "start_date": "2022", "end_date": "Present", "bullets": ["Built REST APIs in Python and FastAPI"]}],
    "projects": [],
    "skills": {"Languages": ["Python"], "Tools": ["FastAPI", "Docker", "AWS", "PostgreSQL"]},
    "certifications": [],
}


def setup_function():
    reset_cache()


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def _make_pdf_bytes(text: str) -> bytes:
    from xhtml2pdf import pisa

    html = f"<html><body><p>{text.replace(chr(10), '<br/>')}</p></body></html>"
    buf = io.BytesIO()
    pisa.CreatePDF(html, dest=buf)
    return buf.getvalue()


def _make_docx_bytes(text: str) -> bytes:
    from docx import Document

    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_text_from_real_pdf():
    pdf_bytes = _make_pdf_bytes(SAMPLE_RESUME_TEXT)
    text = extract_text_from_pdf(pdf_bytes)
    assert "Jane Doe" in text
    assert "Backend Engineer" in text


def test_extract_text_from_real_docx():
    docx_bytes = _make_docx_bytes(SAMPLE_RESUME_TEXT)
    text = extract_text_from_docx(docx_bytes)
    assert "Jane Doe" in text
    assert "FastAPI" in text


def test_extract_text_from_docx_includes_table_content():
    """Resume templates often use tables for layout -- table cell text
    must not be silently dropped (only .paragraphs would miss it)."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("Header text")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Skills"
    table.rows[0].cells[1].text = "Kubernetes, Terraform"
    buf = io.BytesIO()
    doc.save(buf)

    text = extract_text_from_docx(buf.getvalue())
    assert "Kubernetes" in text
    assert "Terraform" in text


def test_extract_text_plain_txt():
    text = extract_text(SAMPLE_RESUME_TEXT.encode("utf-8"), "resume.txt")
    assert text == SAMPLE_RESUME_TEXT.strip()


def test_extract_text_unsupported_extension_raises():
    with pytest.raises(UnsupportedFileTypeError):
        extract_text(b"whatever", "resume.exe")


def test_extract_text_from_scanned_pdf_with_no_text_raises_parse_error():
    """A PDF with no extractable text (e.g. a scanned image with no OCR
    layer) must raise ResumeParseError, not silently return an empty
    string that would sail through to the LLM step."""
    blank_pdf = _make_pdf_bytes("")
    with pytest.raises(ResumeParseError):
        extract_text_from_pdf(blank_pdf)


def test_extract_text_malformed_pdf_bytes_raises():
    with pytest.raises(ResumeParseError):
        extract_text_from_pdf(b"this is not a real pdf file")


def test_extract_text_bad_utf8_txt_raises():
    with pytest.raises(ResumeParseError):
        extract_text(b"\xff\xfe\x00\x01invalid utf8 garbage \x80\x81", "resume.txt")


# ---------------------------------------------------------------------------
# Structuring (mocked LLM)
# ---------------------------------------------------------------------------


def test_structure_resume_text_calls_llm_and_returns_parsed_shape():
    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME) as mock_llm:
        result = structure_resume_text(SAMPLE_RESUME_TEXT)

    assert result == FAKE_PARSED_RESUME
    mock_llm.assert_called_once()


def test_structure_resume_text_rejects_too_short_input_without_calling_llm():
    with patch("skills.parse_resume.llm_generate_json") as mock_llm:
        with pytest.raises(ResumeParseError):
            structure_resume_text("short")
    mock_llm.assert_not_called()


def test_structure_resume_text_rejects_empty_input():
    with pytest.raises(ResumeParseError):
        structure_resume_text("")
    with pytest.raises(ResumeParseError):
        structure_resume_text("   ")


# ---------------------------------------------------------------------------
# text_hash -- cache key stability
# ---------------------------------------------------------------------------


def test_text_hash_stable_across_whitespace_differences():
    a = text_hash("Jane Doe\nBackend Engineer")
    b = text_hash("Jane Doe   Backend Engineer")  # different whitespace, same words
    assert a == b


def test_text_hash_differs_for_different_content():
    a = text_hash("Jane Doe")
    b = text_hash("John Smith")
    assert a != b


# ---------------------------------------------------------------------------
# parse_resume_cached -- end-to-end with caching
# ---------------------------------------------------------------------------


def test_parse_resume_cached_hits_cache_on_repeat_upload():
    """The same resume uploaded twice (even in a different format) must
    only pay for the LLM call once."""
    pdf_bytes = _make_pdf_bytes(SAMPLE_RESUME_TEXT)

    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME) as mock_llm:
        first_result, _ = parse_resume_cached(pdf_bytes, "resume.pdf")
        second_result, _ = parse_resume_cached(pdf_bytes, "resume.pdf")

    assert first_result == FAKE_PARSED_RESUME
    assert second_result == FAKE_PARSED_RESUME
    mock_llm.assert_called_once()


def test_parse_resume_cached_same_text_different_format_shares_cache():
    """A PDF and a DOCX with identical extracted text must share one
    cache entry -- caching is keyed on extracted TEXT, not file bytes."""
    pdf_bytes = _make_pdf_bytes(SAMPLE_RESUME_TEXT)
    docx_bytes = _make_docx_bytes(SAMPLE_RESUME_TEXT)

    with patch("skills.parse_resume.llm_generate_json", return_value=FAKE_PARSED_RESUME) as mock_llm:
        parse_resume_cached(pdf_bytes, "resume.pdf")
        parse_resume_cached(docx_bytes, "resume.docx")

    # xhtml2pdf/python-docx don't reproduce whitespace byte-identically,
    # but both should normalize to the same hash via text_hash's
    # whitespace collapsing -- if this ever fails because extraction
    # differs meaningfully, that's a real signal worth investigating,
    # not something to loosen this assertion for.
    assert mock_llm.call_count == 1
