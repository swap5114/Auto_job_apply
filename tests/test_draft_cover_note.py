"""Tests for skills/draft_cover_note.py -- the Apply channel's cover-note
generation skill (Phase 5.1).

Mocks skills.llm_client.llm_generate throughout (same discipline every
other LLM-backed skill's tests use elsewhere in this repo) -- no real
network/API call is ever made here.
"""

from unittest.mock import patch

from skills.draft_cover_note import draft_cover_note, SYSTEM_PROMPT


FAKE_TAILORED_RESUME = {
    "name": "Jane Doe",
    "contact": {"email": "jane@example.com", "github": "github.com/janedoe"},
    "summary": "Backend engineer focused on distributed systems.",
    "education": [],
    "experience": [
        {
            "title": "Backend Engineer",
            "company": "Acme Corp",
            "start_date": "2022",
            "end_date": "Present",
            "bullets": ["Built a Python/FastAPI service handling 10k req/s."],
        }
    ],
    "projects": [],
    "skills": {"Languages": ["Python", "Go"], "Tools": ["Docker", "Postgres"]},
    "certifications": [],
}

REAL_LEAD = {
    "company": "Stripe",
    "role": "Backend Engineer",
    "jd_text": (
        "We're building the payments infrastructure that powers millions of "
        "businesses. Looking for a backend engineer with strong Python and "
        "distributed-systems experience to help scale our ledger service."
    ),
}

# A JD from a completely different domain, with a candidate background
# that has zero honest overlap -- the zero-fabrication stress test's
# mismatched fixture (per PHASE_5_PLAN.md 5.1's explicit test-gate
# requirement).
MISMATCHED_LEAD = {
    "company": "Sunrise Veterinary Clinic",
    "role": "Licensed Veterinary Technician",
    "jd_text": (
        "Seeking a licensed veterinary technician to assist with animal "
        "surgeries, administer medications, and provide compassionate "
        "care for dogs and cats. Must hold a current LVT license and have "
        "hands-on large-animal handling experience."
    ),
}


def test_draft_cover_note_calls_llm_with_expected_content():
    with patch(
        "skills.draft_cover_note.llm_generate",
        return_value="Dear Stripe team, ... Jane Doe",
    ) as mock_llm:
        note = draft_cover_note(FAKE_TAILORED_RESUME, REAL_LEAD)

    assert note == "Dear Stripe team, ... Jane Doe"
    mock_llm.assert_called_once()
    kwargs = mock_llm.call_args.kwargs
    assert kwargs["system_prompt"] == SYSTEM_PROMPT
    assert "Stripe" in kwargs["user_message"]
    assert "Backend Engineer" in kwargs["user_message"]
    assert "ledger service" in kwargs["user_message"]
    # The tailored resume (not just a company/role summary) must be in the
    # prompt -- this is what makes the zero-fabrication rule enforceable
    # by the model at all.
    assert "Jane Doe" in kwargs["user_message"]


def test_draft_cover_note_strips_markdown_fences():
    with patch(
        "skills.draft_cover_note.llm_generate",
        return_value="```\nDear Stripe team, ... Jane Doe\n```",
    ):
        note = draft_cover_note(FAKE_TAILORED_RESUME, REAL_LEAD)

    assert note == "Dear Stripe team, ... Jane Doe"
    assert "```" not in note


def test_draft_cover_note_zero_fabrication_stress_test():
    """PHASE_5_PLAN.md 5.1's explicit test-gate requirement: feed a JD that
    doesn't match the candidate's real background at all, confirm the
    prompt instructs the model to decline rather than fabricate a
    connection -- and confirm a model response that actually follows that
    instruction (the NO_HONEST_CONNECTION refusal) round-trips through
    draft_cover_note() as-is, so a caller can detect and skip it.

    This is not just "some text came back" -- it specifically checks (a)
    the system prompt sent to the model contains the refusal instruction,
    and (b) draft_cover_note() doesn't mangle or hide a refusal response.
    """
    assert "NO_HONEST_CONNECTION" in SYSTEM_PROMPT
    assert "NEVER claim a skill, experience, project, or credential" in SYSTEM_PROMPT

    refusal_text = (
        "NO_HONEST_CONNECTION: The candidate's resume shows backend software "
        "engineering experience with no veterinary licensure, animal-handling "
        "experience, or clinical training relevant to this role."
    )
    with patch("skills.draft_cover_note.llm_generate", return_value=refusal_text) as mock_llm:
        note = draft_cover_note(FAKE_TAILORED_RESUME, MISMATCHED_LEAD)

    # The mismatched JD must actually have been sent to the model -- the
    # refusal has to be a real decision made with the mismatched context
    # in front of it, not a coincidence of the mock.
    kwargs = mock_llm.call_args.kwargs
    assert "Veterinary" in kwargs["user_message"]
    assert note.startswith("NO_HONEST_CONNECTION:")


def test_draft_cover_note_banned_phrases_are_not_in_system_prompt_instructions_only():
    """Regression guard mirroring draft_outreach.py's own banned-phrase
    list -- confirms this module carries the exact same clichés forward
    rather than silently drifting to a different (or shorter) list.
    """
    banned = [
        "I came across your opening",
        "I am writing to express my interest",
        "I wanted to reach out",
        "I believe I would be a great fit",
        "please find attached",
        "I look forward to hearing from you",
    ]
    for phrase in banned:
        assert phrase in SYSTEM_PROMPT


def test_draft_cover_note_word_cap_instruction_present():
    assert "250-300 words" in SYSTEM_PROMPT
