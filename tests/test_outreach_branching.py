"""Task 8 verification: outreach branching (WITH/WITHOUT demo link).

Runnable script:
    python tests/test_outreach_branching.py

The LLM is mocked to capture the exact user_message the drafter builds, so we can
assert the live link is present only when approved + deployed, and that no demo is
ever claimed otherwise (zero fabrication). Also covers the manual-draft override.
"""

import contextlib
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import graph.pipeline as p
import skills.llm_client as llm
import skills.draft_outreach as do


@contextlib.contextmanager
def _capture_llm_in(module, attr="llm_generate"):
    """Patch `module.attr` with a capturing fake; yields a dict with last user_message."""
    box = {"user_message": None, "calls": 0}

    def fake(**kw):
        box["calls"] += 1
        box["user_message"] = kw.get("user_message", "")
        return "Subject: Hi\n\nBody text."

    saved = getattr(module, attr)
    setattr(module, attr, fake)
    try:
        yield box
    finally:
        setattr(module, attr, saved)


@contextlib.contextmanager
def _patch(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


_RESEARCH = {
    "overview": "They do observability.",
    "talking_points": ["p50/p95 latency UX"],
    "demo_project": {"title": "LatencyLens", "description": "latency board"},
}


def _base_state(**over):
    s = {
        "lead_id": "id1", "company": "ObservaCo", "role": "FE", "source": "greenhouse",
        "jd_text": "observability dashboards", "resume_version": "r1",
        "company_research": _RESEARCH, "status": "approved",
    }
    s.update(over)
    return s


def test_draft_with_link_when_approved_and_deployed():
    state = _base_state(include_demo=True, demo_status="deployed",
                        demo_url="https://demo-observaco.vercel.app")
    with _patch(do, load_tailored_resume=lambda rv: {"name": "Cand"}), \
         _capture_llm_in(llm) as box:
        out = p.draft_node(state)

    msg = box["user_message"]
    assert "https://demo-observaco.vercel.app" in msg, "live link must be in the prompt"
    assert "LIVE DEMO" in msg, "should instruct to reference the live demo"
    assert out["status"] == "approved", out  # send stays authorized
    print("✅ test_draft_with_link_when_approved_and_deployed passed")


def test_draft_without_link_when_demo_excluded():
    # include_demo False (reviewer chose send-plain) even though a demo is live.
    state = _base_state(include_demo=False, demo_status="deployed",
                        demo_url="https://demo-observaco.vercel.app")
    with _patch(do, load_tailored_resume=lambda rv: {"name": "Cand"}), \
         _capture_llm_in(llm) as box:
        p.draft_node(state)

    msg = box["user_message"]
    assert "https://demo-observaco.vercel.app" not in msg, "link must NOT leak when excluded"
    assert "LIVE DEMO TO REFERENCE" not in msg
    assert "do NOT claim" in msg, "must instruct against fabricating a demo"
    print("✅ test_draft_without_link_when_demo_excluded passed")


def test_draft_without_link_when_build_failed():
    state = _base_state(include_demo=False, demo_status="build_failed", demo_url="")
    with _patch(do, load_tailored_resume=lambda rv: {"name": "Cand"}), \
         _capture_llm_in(llm) as box:
        p.draft_node(state)
    msg = box["user_message"]
    assert "LIVE DEMO" not in msg
    assert "do NOT claim" in msg
    print("✅ test_draft_without_link_when_build_failed passed")


def test_manual_draft_override_skips_llm():
    state = _base_state(include_demo=True, demo_status="deployed",
                        demo_url="https://x.app", outreach_draft="MY MANUAL DRAFT")
    with _patch(do, load_tailored_resume=lambda rv: {"name": "Cand"}), \
         _capture_llm_in(llm) as box:
        out = p.draft_node(state)
    assert out == {"outreach_draft": "MY MANUAL DRAFT", "status": "approved"}, out
    assert box["calls"] == 0, "manual override must not call the LLM"
    print("✅ test_manual_draft_override_skips_llm passed")


def test_standalone_drafter_demo_gating():
    # WITH a live demo -> link appears in prompt.
    lead_live = {"source": "greenhouse", "company": "ObservaCo", "role": "FE",
                 "jd_text": "x", "demo_status": "deployed", "demo_url": "https://live.app"}
    with _capture_llm_in(do) as box:
        do.draft_outreach_message({"name": "Cand"}, lead_live)
    assert "https://live.app" in box["user_message"]
    assert "LIVE DEMO URL" in box["user_message"]

    # WITHOUT -> no demo context.
    lead_none = {"source": "greenhouse", "company": "ObservaCo", "role": "FE", "jd_text": "x"}
    with _capture_llm_in(do) as box:
        do.draft_outreach_message({"name": "Cand"}, lead_none)
    assert "LIVE DEMO URL" not in box["user_message"]
    print("✅ test_standalone_drafter_demo_gating passed")


if __name__ == "__main__":
    test_draft_with_link_when_approved_and_deployed()
    test_draft_without_link_when_demo_excluded()
    test_draft_without_link_when_build_failed()
    test_manual_draft_override_skips_llm()
    test_standalone_drafter_demo_gating()
    print("\nTask 8 checks complete.")
