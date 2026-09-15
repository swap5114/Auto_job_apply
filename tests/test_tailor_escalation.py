"""Tests for production tailoring (single configured model), the model
benchmark primitive, the resume diff, and templates.

Production makes ONE call to the configured model (TAILOR_BACKEND, default
Gemini). The Gemini-vs-Claude comparison is an OFFLINE benchmark, not a
runtime cost. These tests lock in:
  - production tailors with a single call to the configured backend,
  - a fabricated output is rejected (base resume returned, never fabricated),
  - _tailor_once (the benchmark primitive) scores clean output and
    disqualifies fabrications,
  - the positional diff used for live highlighting,
  - both resume templates rendering without error.
"""

import skills.tailor_resume as tr


_BASE = {
    "name": "Real Candidate",
    "contact": {"email": "real@example.com", "github": "https://github.com/realcandidate"},
    "summary": "Backend engineer.",
    "experience": [{"company": "TrueCorp", "title": "Engineer",
                    "bullets": ["Built Python APIs", "Shipped services"]}],
    "projects": [{"name": "Widget", "bullets": ["Made a thing"]}],
    "education": [{"institution": "State University", "degree": "BS CS"}],
    "skills": {"Languages": ["Python", "JavaScript"]},
    "certifications": [],
}


def test_production_makes_a_single_call_to_configured_model(monkeypatch):
    """Production tailoring calls exactly ONE backend (the configured default),
    never a second model — no runtime comparison."""
    jd = "Python, JavaScript engineer."
    calls = {"backends": [], "n": 0}

    def fake_json(system_prompt, user_message, max_tokens=4096, backend=None, model=None):
        calls["backends"].append(backend)
        calls["n"] += 1
        return dict(_BASE)

    monkeypatch.setattr(tr, "llm_generate_json", fake_json)
    monkeypatch.setattr(tr, "TAILOR_BACKEND", None)  # default => Gemini/Vertex

    result = tr.tailor_resume_verbose(_BASE, "Acme", "Engineer", jd)
    assert calls["n"] == 1                       # exactly one LLM call
    assert "vertex_claude" not in calls["backends"]  # never a second model
    assert result["escalated"] is False
    assert result["model_used"]  # some label present


def test_production_uses_claude_when_configured(monkeypatch):
    """If TAILOR_BACKEND is pinned to Claude, production calls only Claude."""
    jd = "Python engineer."
    calls = {"backends": []}

    def fake_json(system_prompt, user_message, max_tokens=4096, backend=None, model=None):
        calls["backends"].append(backend)
        return dict(_BASE)

    monkeypatch.setattr(tr, "llm_generate_json", fake_json)
    monkeypatch.setattr(tr, "TAILOR_BACKEND", "vertex_claude")

    result = tr.tailor_resume_verbose(_BASE, "Acme", "Engineer", jd)
    assert calls["backends"] == ["vertex_claude"]  # one call, to Claude only
    assert result["model_used"] == "vertex_claude"


def test_fabricated_output_is_rejected(monkeypatch):
    """Invented IDENTITY (a renamed employer) is repaired back to the base
    value via sanitize — we never ship a fabricated company/title — while the
    rest of the output is preserved (not reset to base)."""
    jd = "Kubernetes, Terraform, Go, Rust expert needed."
    fabricated = {**_BASE, "experience": [
        {"company": "FakeGiant", "title": "Principal", "bullets": ["Led 100 engineers"]},
    ]}

    monkeypatch.setattr(tr, "llm_generate_json",
                        lambda system_prompt, user_message, max_tokens=4096, backend=None, model=None: dict(fabricated))
    monkeypatch.setattr(tr, "TAILOR_BACKEND", None)

    result = tr.tailor_resume_verbose(_BASE, "Acme", "Engineer", jd)
    exp = result["tailored"].get("experience", [])
    # Company + title pinned back to the base entry (positional match).
    assert exp[0]["company"] == "TrueCorp"
    assert exp[0]["title"] == "Engineer"


def test_reworded_resume_is_kept_not_reset_to_base(monkeypatch):
    """The core fix: a legitimately reworded resume (new bullet wording +
    JD-synonym skill rephrase, same real company/title) must be KEPT, not
    silently reset to the base resume."""
    jd = "Backend engineer: build REST API design, Python services."
    reworked = {
        **_BASE,
        # Same company/title, but bullets reworded to the JD's terms.
        "experience": [{"company": "TrueCorp", "title": "Engineer",
                        "bullets": ["Designed and shipped REST API design in Python",
                                    "Delivered backend services"]}],
        # Skill rephrased to the JD's wording (allowed synonym of "Python").
        "skills": {"Languages": ["Python (backend services)", "JavaScript"]},
    }
    monkeypatch.setattr(tr, "llm_generate_json",
                        lambda system_prompt, user_message, max_tokens=4096, backend=None, model=None: dict(reworked))
    monkeypatch.setattr(tr, "TAILOR_BACKEND", None)

    result = tr.tailor_resume_verbose(_BASE, "TrueCorp", "Engineer", jd)
    t = result["tailored"]
    # Reworded bullet survived (not reverted to the base wording).
    assert "REST API design" in t["experience"][0]["bullets"][0]
    # The skill rephrase survived (it overlaps the base "Python").
    assert any("Python" in s for s in t["skills"]["Languages"])


def test_tailor_once_scores_clean_and_rejects_fabrication(monkeypatch):
    """The benchmark primitive: clean output -> (candidate, score>=0);
    fabricated content is SANITIZED (dropped), not discarded — the rework is
    kept, only the invented parts are removed."""
    jd = "Python, JavaScript."
    msg = tr.build_tailor_message(_BASE, "Acme", "Engineer", jd)

    # Clean (base unchanged) -> scored.
    monkeypatch.setattr(tr, "llm_generate_json",
                        lambda **kw: dict(_BASE))
    cand, score = tr._tailor_once(msg, jd, _BASE, backend=None)
    assert cand is not None and score >= 0

    # A genuinely-new skill ("Haskell") is dropped, but the resume is KEPT
    # (reworded bullets etc. survive) rather than falling back to base.
    monkeypatch.setattr(tr, "llm_generate_json",
                        lambda **kw: {**_BASE, "skills": {"Languages": ["Python", "Haskell"]}})
    cand2, score2 = tr._tailor_once(msg, jd, _BASE, backend="vertex_claude")
    assert cand2 is not None
    assert "Haskell" not in cand2["skills"]["Languages"]  # fabricated skill removed
    assert "Python" in cand2["skills"]["Languages"]        # real skill kept


def test_diff_resumes_flags_changed_bullets_and_skills():
    tailored = {
        **_BASE,
        "summary": "Backend engineer with Python.",  # changed
        "experience": [{"company": "TrueCorp", "title": "Engineer",
                        "bullets": ["Built Python REST APIs", "Shipped services"]}],  # bullet 0 changed
        "skills": {"Languages": ["Python", "JavaScript", "TypeScript"]},  # index 2 is "new" position
    }
    d = tr.diff_resumes(_BASE, tailored)
    assert d["summary"] is True
    assert d["experience"][0][0] is True   # first bullet reworded
    assert d["experience"][0][1] is False  # second bullet unchanged
    assert d["skills"]["Languages"][2] is True  # third skill not in base


def test_both_templates_render():
    for template in ("standard", "jake"):
        html = tr.resume_to_html(_BASE, template=template)
        assert "Real Candidate" in html
        assert "<html>" in html.lower()
    # Unknown template falls back to the default (jake), still renders.
    assert "Real Candidate" in tr.resume_to_html(_BASE, template="nope")
