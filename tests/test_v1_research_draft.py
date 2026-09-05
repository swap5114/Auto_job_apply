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


def test_research_company_handles_markdown_json_response(monkeypatch):
    import skills.research_company as rc
    import skills.llm_client as llm

    fake_json_md = """```json
{
  "overview": "Stripe builds payment infrastructure.",
  "stage": "Established",
  "industry": "Fintech",
  "tech_signals": ["Ruby", "Go", "Postgres"],
  "demo_project": {
    "title": "Idempotency key analyzer",
    "description": "Tool to simulate edge-case retries.",
    "why_it_matters": "Prevents double charges under high concurrency.",
    "tech_stack": ["Go", "Postgres"],
    "deliverable": "Working POC",
    "time_estimate": "2 days",
    "why_impressive": "Shows awareness of payment consistency requirements."
  },
  "talking_points": ["Loved Stripe's API idempotency architecture."],
  "fit_summary": "Strong Go/Postgres backend match."
}
```"""

    monkeypatch.setattr(llm, "llm_generate", lambda *args, **kwargs: fake_json_md)

    res = rc.research_company("Stripe", "stripe.com", "Backend Engineer", "Go and Postgres payments role.")
    assert res["overview"] == "Stripe builds payment infrastructure."
    assert res["demo_project"]["title"] == "Idempotency key analyzer"
    assert "Go" in res["tech_signals"]


def test_research_company_handles_llm_exception_gracefully(monkeypatch):
    import skills.research_company as rc
    import skills.llm_client as llm

    def raise_error(*args, **kwargs):
        raise RuntimeError("API Rate Limit Exceeded (429)")

    monkeypatch.setattr(llm, "llm_generate", raise_error)

    res = rc.research_company("Acme", "acme.com", "DevOps Engineer", "Kubernetes role.")
    assert "Acme" in res["overview"]
    assert "demo_project" in res
    assert res["demo_project"]["title"] == "Technical Proposal for Acme"


def test_research_company_truncates_long_jd(monkeypatch):
    import skills.research_company as rc
    import skills.llm_client as llm

    captured_prompt = {}

    def capture_user_msg(system_prompt, user_message, max_tokens=1500):
        captured_prompt["user"] = user_message
        return '{"overview": "Acme summary"}'

    monkeypatch.setattr(llm, "llm_generate", capture_user_msg)

    huge_jd = "Python " * 1000  # > 6000 chars
    rc.research_company("Acme", "acme.com", "Engineer", huge_jd)

    assert "[truncated]" in captured_prompt["user"]
    assert len(captured_prompt["user"]) < 5000


def test_research_company_normalizes_missing_fields(monkeypatch):
    import skills.research_company as rc
    import skills.llm_client as llm

    partial_json = '{"overview": "Only overview given"}'
    monkeypatch.setattr(llm, "llm_generate", lambda *args, **kwargs: partial_json)

    res = rc.research_company("Partial Co", "partial.com", "Frontend Dev", "React role.")
    assert res["overview"] == "Only overview given"
    assert res["stage"] == "Unknown"
    assert res["industry"] == "Technology"
    assert isinstance(res["demo_project"], dict)
    assert res["demo_project"]["title"] == "Proposed feature prototype for Partial Co"

