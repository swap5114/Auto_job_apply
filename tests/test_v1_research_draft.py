"""v1 Task 4: research produces a deep use-case framed as a proposal, and the
outreach draft offers it as thinking -- never as an already-built artifact."""


def test_research_prompt_emphasizes_usecase_proposal_not_built_demo():
    from skills.research_company import SYSTEM_PROMPT

    low = SYSTEM_PROMPT.lower()
    # Reframed toward a valuable use-case/idea...
    assert "use-case" in low or "use case" in low
    assert "idea" in low
    # ...explicitly a proposal, never claimed as already built.
    assert "already built" in low or "not something already built" in low


def test_draft_node_offers_idea_honestly(monkeypatch):
    """draft_node's LLM prompt must present the research idea as a proposal
    (honest framing present) and must NOT carry the old 'has built/is
    building a demo' claim."""
    import graph.pipeline as gp
    import skills.draft_outreach as do
    import skills.llm_client as llm

    captured = {}

    def fake_llm(system_prompt, user_message, max_tokens=1024):
        captured["system"] = system_prompt
        captured["user"] = user_message
        return "Subject: An idea for Acme\n\nHi Ada — one thing I'd love to explore with you..."

    monkeypatch.setattr(llm, "llm_generate", fake_llm)
    monkeypatch.setattr(do, "load_tailored_resume", lambda rv: {"name": "Jane"})

    state = {
        "company": "Acme",
        "role": "Backend Engineer",
        "resume_version": "r1",
        "source": "yc",
        "jd_text": "Python/FastAPI backend role.",
        "contact_name": "Ada",
        "company_research": {
            "demo_project": {
                "title": "Latency budget tracker",
                "description": "A small service that flags slow endpoints.",
                "why_it_matters": "Cuts p99 regressions before they ship.",
            }
        },
    }

    result = gp.draft_node(state)
    assert result["status"] == "pending_review"

    # Honest framing is injected; the dishonest 'already built' framing is gone.
    assert "NEVER claim it is already built" in captured["user"]
    assert "has built/is building" not in captured["user"]

    # The shared system prompt also forbids claiming a built/attached artifact.
    assert "forbidden" in captured["system"].lower()
