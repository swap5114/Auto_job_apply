"""v1 Task 1 regression tests: sourcing/processing skills must operate on the
passed user_id, not the single local-operator stand-in.

These prove the multi-tenancy fix: a signed-in user's pipeline run reads and
writes only THEIR leads. External calls (LLM, Apollo/Hunter, Firecrawl, YC
API) are monkeypatched so the tests are hermetic and free.
"""

import pytest

from db import repository as repo


def _make_user(suffix: str) -> dict:
    return repo.create_user(firebase_uid=f"fb-{suffix}", email=f"{suffix}@example.com")


def test_find_contact_email_run_is_user_scoped(monkeypatch):
    """find_contact_email.run(user_id=A) must only touch user A's leads."""
    import skills.find_contact_email as fce

    user_a = _make_user("scope-a")
    user_b = _make_user("scope-b")

    lead_a = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Backend Engineer"})
    lead_b = repo.add_lead(user_b["id"], {"company": "Beta", "role": "Backend Engineer"})

    # Ensure the run() key guard passes and no real provider is hit.
    monkeypatch.setattr(fce, "HUNTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(fce, "APOLLO_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(
        fce,
        "find_contact_email_for_lead",
        lambda lead: {"contact_email": "founder@acme.com", "contact_name": "Founder"},
    )

    fce.run(user_id=user_a["id"])

    refreshed_a = repo.get_lead(user_a["id"], lead_a["id"])
    refreshed_b = repo.get_lead(user_b["id"], lead_b["id"])

    assert refreshed_a["contact_email"] == "founder@acme.com"
    # User B's lead must be completely untouched by user A's run.
    assert not (refreshed_b.get("contact_email") or "")


def test_draft_outreach_run_is_user_scoped(monkeypatch):
    """draft_outreach.run(user_id=A) must only draft for user A's leads."""
    import skills.draft_outreach as do

    user_a = _make_user("draft-a")
    user_b = _make_user("draft-b")

    # Both leads look "ready to draft": have a resume_version, no draft yet,
    # outreach channel. resume_version/channel aren't accepted by add_lead's
    # core-field writer, so set them via update_lead (same path tailor uses).
    lead_a = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Backend Engineer"})
    lead_b = repo.add_lead(user_b["id"], {"company": "Beta", "role": "Backend Engineer"})
    repo.update_lead(user_a["id"], lead_a["id"], {"resume_version": "resume_acme", "channel": ["outreach"]})
    repo.update_lead(user_b["id"], lead_b["id"], {"resume_version": "resume_beta", "channel": ["outreach"]})

    # draft_outreach.run imports MODEL_BACKEND/ANTHROPIC_API_KEY locally from
    # llm_client at call time, so patch there to pass the guard without a key.
    import skills.llm_client as llm
    monkeypatch.setattr(llm, "MODEL_BACKEND", "gemini", raising=False)
    monkeypatch.setattr(do, "load_tailored_resume", lambda rv: {"name": "Jane"})
    monkeypatch.setattr(do, "draft_outreach_message", lambda resume, lead: "Subject: Hi\n\nHello.")

    do.run(user_id=user_a["id"])

    refreshed_a = repo.get_lead(user_a["id"], lead_a["id"])
    refreshed_b = repo.get_lead(user_b["id"], lead_b["id"])

    assert (refreshed_a.get("outreach_draft") or "").startswith("Subject:")
    assert refreshed_a["status"] == "pending_review"
    # User B's lead must be untouched.
    assert not (refreshed_b.get("outreach_draft") or "")
    assert refreshed_b["status"] == "matched"


# ---------------------------------------------------------------------------
# Task 2: shared cross-user contact-email cache
# ---------------------------------------------------------------------------


def test_contact_email_cache_avoids_repeat_provider_calls(monkeypatch):
    """First domain lookup calls the provider and populates the shared cache;
    a second lookup for the same domain (even a different user) is a cache hit
    with zero provider calls."""
    import skills.find_contact_email as fce

    apollo_calls = {"n": 0}
    hunter_calls = {"n": 0}

    def fake_apollo(domain, company=None, contact_name=None):
        apollo_calls["n"] += 1
        return "founder@acme.com", "Ada Founder"

    def fake_hunter(domain):
        hunter_calls["n"] += 1
        return None

    monkeypatch.setattr(fce, "apollo_lookup", fake_apollo)
    monkeypatch.setattr(fce, "hunter_lookup", fake_hunter)

    # First resolve: provider is hit once, cache populated.
    email1, name1 = fce._lookup_by_domain("acme.com")
    assert email1 == "founder@acme.com"
    assert name1 == "Ada Founder"
    assert apollo_calls["n"] == 1

    # Second resolve of the same domain: cache hit, provider NOT called again.
    email2, name2 = fce._lookup_by_domain("acme.com")
    assert email2 == "founder@acme.com"
    assert name2 == "Ada Founder"
    assert apollo_calls["n"] == 1  # unchanged -> no extra credit burned
    assert hunter_calls["n"] == 0


def test_contact_email_cache_is_cross_user(monkeypatch):
    """The cache is global: a domain resolved during user A's run is reused
    during user B's find_contact_email.run without hitting the provider."""
    import skills.find_contact_email as fce

    user_a = _make_user("cache-a")
    user_b = _make_user("cache-b")

    lead_a = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Backend Engineer"})
    lead_b = repo.add_lead(user_b["id"], {"company": "Acme", "role": "Frontend Engineer"})
    # Both leads share the same verified domain.
    repo.update_lead(user_a["id"], lead_a["id"], {"domain": "acme.com"})
    repo.update_lead(user_b["id"], lead_b["id"], {"domain": "acme.com"})

    provider_calls = {"n": 0}

    def fake_apollo(domain, company=None, contact_name=None):
        provider_calls["n"] += 1
        return "founder@acme.com", "Ada Founder"

    monkeypatch.setattr(fce, "HUNTER_API_KEY", "k", raising=False)
    monkeypatch.setattr(fce, "APOLLO_API_KEY", "k", raising=False)
    monkeypatch.setattr(fce, "apollo_lookup", fake_apollo)
    monkeypatch.setattr(fce, "hunter_lookup", lambda d: None)

    fce.run(user_id=user_a["id"])
    fce.run(user_id=user_b["id"])

    assert provider_calls["n"] == 1  # user B reused user A's cached resolve

    assert repo.get_lead(user_a["id"], lead_a["id"])["contact_email"] == "founder@acme.com"
    assert repo.get_lead(user_b["id"], lead_b["id"])["contact_email"] == "founder@acme.com"
