"""Tests for resume-parse robustness (production hardening).

Covers the failure modes behind the reported symptom — a resume that parsed
partially, broke midway, or came back unchanged:
  - LLM output truncated at MAX_TOKENS -> llm_generate_json retries with a
    bigger budget instead of json.loads-ing a broken string
  - JSON polluted with leading/trailing prose or code fences -> extracted cleanly
  - genuine failure -> heuristic fallback is FLAGGED incomplete, not passed off
    as a clean parse, and is NOT cached
"""

import json
import pytest

import skills.parse_resume as pr
from skills import llm_client
from skills.llm_client import LLMTruncatedError, extract_json_object


def setup_function():
    pr.reset_cache()


# --- JSON extraction ------------------------------------------------------

def test_extract_json_strips_fences_and_prose():
    assert json.loads(extract_json_object('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(extract_json_object('Here is the JSON:\n```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(extract_json_object('{"a": 1}\n\nNote: hope this helps!')) == {"a": 1}
    # Braces inside strings don't confuse the balancer.
    assert json.loads(extract_json_object('prefix {"a": "b}c{"} suffix')) == {"a": "b}c{"}


# --- llm_generate_json retry behavior ------------------------------------

def test_json_retries_once_on_truncation_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_generate(system_prompt, user_message, max_tokens, backend=None, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMTruncatedError("truncated at MAX_TOKENS")
        return '{"name": "Jane", "experience": [{"company": "BigCo"}]}'

    monkeypatch.setattr(llm_client, "llm_generate", fake_generate)
    result = llm_client.llm_generate_json("sys", "user", max_tokens=4096)
    assert result["name"] == "Jane"
    assert calls["n"] == 2  # retried once with a bigger budget


def test_json_retries_once_on_invalid_json(monkeypatch):
    calls = {"n": 0}

    def fake_generate(system_prompt, user_message, max_tokens, backend=None, model=None):
        calls["n"] += 1
        # First response is cut off mid-object (invalid); second is clean.
        return '{"name": "Jane", "exp' if calls["n"] == 1 else '{"name": "Jane"}'

    monkeypatch.setattr(llm_client, "llm_generate", fake_generate)
    assert llm_client.llm_generate_json("s", "u")["name"] == "Jane"
    assert calls["n"] == 2


def test_json_raises_after_retry_still_bad(monkeypatch):
    monkeypatch.setattr(llm_client, "llm_generate", lambda *a, **k: '{"broken": ')
    with pytest.raises(json.JSONDecodeError):
        llm_client.llm_generate_json("s", "u")


# --- structure_resume_text: no silent gutting ----------------------------

_REAL_RESUME = (
    "Jane Developer\njane@example.com | github.com/janedev\n\n"
    "EXPERIENCE\nSenior Engineer, BigCo (2020-2024)\n"
    "- Built distributed systems in Python and Go\n"
    "PROJECTS\nWidget - a React dashboard\n"
    "SKILLS\nPython, Go, React, PostgreSQL\n" + ("filler detail line. " * 40)
)


def test_failed_parse_is_flagged_incomplete_not_silently_gutted(monkeypatch):
    # Simulate the LLM path failing outright.
    def boom(**kw):
        raise RuntimeError("provider 503")
    monkeypatch.setattr(pr, "llm_generate_json", boom)

    result = pr.structure_resume_text(_REAL_RESUME)
    assert result.get("_parse_incomplete") is True
    assert "_parse_error" in result


def test_incomplete_parse_is_not_cached(monkeypatch):
    monkeypatch.setattr(pr, "llm_generate_json", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    # First call: fails -> incomplete, not cached.
    pr.parse_resume_cached(_REAL_RESUME.encode("utf-8"), "r.txt", "text/plain")
    # Now the LLM "recovers"; a good parse must be returned (proving the bad
    # one wasn't cached and served again).
    monkeypatch.setattr(pr, "llm_generate_json", lambda **kw: {
        "name": "Jane Developer",
        "experience": [{"company": "BigCo", "title": "Senior Engineer", "bullets": ["x"]}],
        "education": [], "projects": [], "skills": {"Skills": ["Python"]},
    })
    parsed, _ = pr.parse_resume_cached(_REAL_RESUME.encode("utf-8"), "r.txt", "text/plain")
    assert not parsed.get("_parse_incomplete")
    assert parsed["experience"][0]["company"] == "BigCo"


def test_good_parse_is_trusted_and_cached(monkeypatch):
    good = {
        "name": "Jane Developer",
        "experience": [{"company": "BigCo", "title": "Eng", "bullets": ["x"]}],
        "education": [], "projects": [], "skills": {"Skills": ["Python"]},
    }
    calls = {"n": 0}

    def once(**kw):
        calls["n"] += 1
        return dict(good)
    monkeypatch.setattr(pr, "llm_generate_json", once)

    p1, _ = pr.parse_resume_cached(_REAL_RESUME.encode("utf-8"), "r.txt", "text/plain")
    p2, _ = pr.parse_resume_cached(_REAL_RESUME.encode("utf-8"), "r.txt", "text/plain")
    assert not p1.get("_parse_incomplete")
    assert calls["n"] == 1  # second call served from cache


def test_very_short_text_raises():
    with pytest.raises(pr.ResumeParseError):
        pr.structure_resume_text("too short")
