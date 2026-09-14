"""Repository CRUD tests + the hard tenant-isolation test.

Run with: pytest tests/test_repository.py -v
Requires a reachable Postgres (see tests/conftest.py / docker-compose.yml).
"""

import pytest

from db import repository as repo


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_create_and_get_user():
    user = repo.create_user(firebase_uid="fb-1", email="a@example.com")
    assert user["email"] == "a@example.com"
    assert user["plan"] == "free"

    fetched = repo.get_user(user["id"])
    assert fetched["id"] == user["id"]


def test_get_or_create_user_is_idempotent():
    first = repo.get_or_create_user(firebase_uid="fb-2", email="b@example.com")
    second = repo.get_or_create_user(firebase_uid="fb-2", email="b@example.com")
    assert first["id"] == second["id"]


def test_create_user_requires_uid_and_email():
    with pytest.raises(repo.ValidationError):
        repo.create_user(firebase_uid="", email="")


# ---------------------------------------------------------------------------
# Leads CRUD
# ---------------------------------------------------------------------------


def _make_user(suffix: str = "1") -> dict:
    return repo.create_user(firebase_uid=f"fb-user-{suffix}", email=f"user{suffix}@example.com")


def test_add_lead_and_get_lead():
    user = _make_user("lead1")
    lead = repo.add_lead(user["id"], {"company": "Acme", "role": "Backend Engineer"})
    assert lead["company"] == "Acme"
    assert lead["status"] == "matched"

    fetched = repo.get_lead(user["id"], lead["id"])
    assert fetched["id"] == lead["id"]


def test_add_lead_requires_company_and_role():
    user = _make_user("lead2")
    with pytest.raises(repo.ValidationError):
        repo.add_lead(user["id"], {"company": "Acme"})
    with pytest.raises(repo.ValidationError):
        repo.add_lead(user["id"], {"role": "Engineer"})


def test_add_lead_dedups_case_insensitive_per_user():
    user = _make_user("lead3")
    repo.add_lead(user["id"], {"company": "Acme", "role": "Backend Engineer"})
    with pytest.raises(repo.DuplicateLeadError):
        repo.add_lead(user["id"], {"company": "ACME", "role": "backend engineer"})


def test_add_lead_same_company_role_allowed_for_different_users():
    user_a = _make_user("lead4a")
    user_b = _make_user("lead4b")
    lead_a = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Backend Engineer"})
    lead_b = repo.add_lead(user_b["id"], {"company": "Acme", "role": "Backend Engineer"})
    assert lead_a["id"] != lead_b["id"]


def test_get_leads_filters_by_status():
    user = _make_user("lead5")
    l1 = repo.add_lead(user["id"], {"company": "Acme", "role": "Engineer"})
    repo.add_lead(user["id"], {"company": "Globex", "role": "Engineer"})
    repo.update_lead(user["id"], l1["id"], {"status": "applied"})

    applied = repo.get_leads(user["id"], status="applied")
    assert len(applied) == 1
    assert applied[0]["company"] == "Acme"

    all_leads = repo.get_leads(user["id"])
    assert len(all_leads) == 2


def test_update_lead_writes_fields():
    user = _make_user("lead6")
    lead = repo.add_lead(user["id"], {"company": "Acme", "role": "Engineer"})
    updated = repo.update_lead(user["id"], lead["id"], {"status": "ready_to_apply", "followup_count": 2})
    assert updated["status"] == "ready_to_apply"
    assert updated["followup_count"] == 2


def test_update_lead_rejects_unknown_field():
    user = _make_user("lead7")
    lead = repo.add_lead(user["id"], {"company": "Acme", "role": "Engineer"})
    with pytest.raises(repo.ValidationError):
        repo.update_lead(user["id"], lead["id"], {"not_a_real_field": "x"})


def test_delete_lead():
    user = _make_user("lead8")
    lead = repo.add_lead(user["id"], {"company": "Acme", "role": "Engineer"})
    assert repo.delete_lead(user["id"], lead["id"]) is True
    assert repo.get_lead(user["id"], lead["id"]) is None
    assert repo.delete_lead(user["id"], lead["id"]) is False


def test_malformed_lead_id_treated_as_not_found_not_a_db_error():
    """A malformed id (not a well-formed UUID -- e.g. a leftover Sheets-era
    hex string, a typo, an unrelated string) must behave as "not found" on
    every id-based lookup, not raise a raw DataError from Postgres's ::UUID
    cast. This matters because API callers (api/main.py) pass whatever
    string a client sends straight through to these functions."""
    user = _make_user("lead9malformed")
    assert repo.get_lead(user["id"], "not-a-real-uuid") is None
    assert repo.delete_lead(user["id"], "not-a-real-uuid") is False
    with pytest.raises(repo.NotFoundError):
        repo.update_lead(user["id"], "not-a-real-uuid", {"status": "applied"})


def test_add_lead_with_x_handle_only_is_valid():
    """X-sourced leads (skills/scrape_x_leads.py) have no company/role --
    only an x_handle. Mirrors storage/sheet_client.py's validation rule."""
    user = _make_user("lead9")
    lead = repo.add_lead(user["id"], {"x_handle": "some_founder", "source": "x"})
    assert lead["x_handle"] == "some_founder"
    assert lead["company"] is None
    assert lead["source"] == "x"


def test_add_lead_requires_company_role_or_x_handle():
    user = _make_user("lead10")
    with pytest.raises(repo.ValidationError):
        repo.add_lead(user["id"], {"source": "x"})


def test_add_lead_dedups_x_handle_case_insensitive_per_user():
    user = _make_user("lead11")
    repo.add_lead(user["id"], {"x_handle": "SomeFounder", "source": "x"})
    with pytest.raises(repo.DuplicateLeadError):
        repo.add_lead(user["id"], {"x_handle": "somefounder", "source": "x"})


def test_add_lead_same_x_handle_allowed_for_different_users():
    user_a = _make_user("lead12a")
    user_b = _make_user("lead12b")
    lead_a = repo.add_lead(user_a["id"], {"x_handle": "same_handle", "source": "x"})
    lead_b = repo.add_lead(user_b["id"], {"x_handle": "same_handle", "source": "x"})
    assert lead_a["id"] != lead_b["id"]


def test_add_lead_multiple_x_leads_for_same_user_dont_collide_on_null_company():
    """Regression guard: company/role are nullable (not NOT NULL default="")
    specifically so that two different X leads for the same user (both with
    company=NULL, role=NULL) don't collide on uq_leads_user_company_role --
    Postgres unique constraints treat multiple NULLs as non-colliding."""
    user = _make_user("lead13")
    lead1 = repo.add_lead(user["id"], {"x_handle": "handle_one", "source": "x"})
    lead2 = repo.add_lead(user["id"], {"x_handle": "handle_two", "source": "x"})
    assert lead1["id"] != lead2["id"]


def test_update_lead_writes_new_pipeline_fields():
    """source, x_handle, resume_version, review_decision, posted_date are
    all live pipeline fields (see db/models.py's Lead docstring) -- confirm
    they round-trip through update_lead like any other writable field."""
    user = _make_user("lead14")
    lead = repo.add_lead(user["id"], {"company": "Acme", "role": "Engineer", "source": "arbeitnow"})
    updated = repo.update_lead(user["id"], lead["id"], {
        "resume_version": "jane_doe_resume_acme",
        "review_decision": "approved",
        "posted_date": "2026-08-01",
    })
    assert updated["resume_version"] == "jane_doe_resume_acme"
    assert updated["review_decision"] == "approved"
    assert updated["posted_date"] == "2026-08-01"


# ---------------------------------------------------------------------------
# HARD TENANT ISOLATION -- user A must never read/write/see user B's data
# ---------------------------------------------------------------------------


def test_tenant_isolation_get_lead():
    user_a = _make_user("isoA1")
    user_b = _make_user("isoB1")
    lead = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Engineer"})

    # B trying to fetch A's lead by ID gets nothing back -- not an error that
    # reveals the row exists, just a clean "not found".
    assert repo.get_lead(user_b["id"], lead["id"]) is None
    # A can still fetch it.
    assert repo.get_lead(user_a["id"], lead["id"]) is not None


def test_tenant_isolation_get_leads_list():
    user_a = _make_user("isoA2")
    user_b = _make_user("isoB2")
    repo.add_lead(user_a["id"], {"company": "Acme", "role": "Engineer"})
    repo.add_lead(user_b["id"], {"company": "Globex", "role": "Engineer"})

    a_leads = repo.get_leads(user_a["id"])
    b_leads = repo.get_leads(user_b["id"])

    assert len(a_leads) == 1 and a_leads[0]["company"] == "Acme"
    assert len(b_leads) == 1 and b_leads[0]["company"] == "Globex"


def test_tenant_isolation_update_lead_raises_not_found():
    user_a = _make_user("isoA3")
    user_b = _make_user("isoB3")
    lead = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Engineer"})

    # B attempting to update A's lead by ID must fail as if it doesn't exist.
    with pytest.raises(repo.NotFoundError):
        repo.update_lead(user_b["id"], lead["id"], {"status": "applied"})

    # And the lead must be untouched.
    still_a = repo.get_lead(user_a["id"], lead["id"])
    assert still_a["status"] == "matched"


def test_tenant_isolation_delete_lead_returns_false_not_error():
    user_a = _make_user("isoA4")
    user_b = _make_user("isoB4")
    lead = repo.add_lead(user_a["id"], {"company": "Acme", "role": "Engineer"})

    # B "deleting" A's lead is a no-op, reported as False, and A's lead survives.
    assert repo.delete_lead(user_b["id"], lead["id"]) is False
    assert repo.get_lead(user_a["id"], lead["id"]) is not None


def test_tenant_isolation_search_criteria():
    user_a = _make_user("isoA5")
    user_b = _make_user("isoB5")
    repo.upsert_search_criteria(user_a["id"], {"roles": ["backend"], "tech_stack": ["python"]})

    assert repo.get_search_criteria(user_b["id"]) is None
    assert repo.get_search_criteria(user_a["id"])["roles"] == ["backend"]


def test_tenant_isolation_usage_counters_increment_independently():
    user_a = _make_user("isoA6")
    user_b = _make_user("isoB6")
    repo.increment_usage(user_a["id"], leads_delta=5)
    repo.increment_usage(user_b["id"], leads_delta=1)

    a_counter = repo.get_or_create_usage_counter(user_a["id"])
    b_counter = repo.get_or_create_usage_counter(user_b["id"])
    assert a_counter["leads_used"] == 5
    assert b_counter["leads_used"] == 1


def test_tenant_isolation_notifications():
    user_a = _make_user("isoA7")
    user_b = _make_user("isoB7")
    repo.add_notification(user_a["id"], "jobs_matched", {"count": 3})

    assert repo.get_notifications(user_b["id"]) == []
    assert len(repo.get_notifications(user_a["id"])) == 1


def test_tenant_isolation_mark_notification_read_raises_for_other_user():
    user_a = _make_user("isoA8")
    user_b = _make_user("isoB8")
    note = repo.add_notification(user_a["id"], "jobs_matched", {"count": 1})

    with pytest.raises(repo.NotFoundError):
        repo.mark_notification_read(user_b["id"], note["id"])


def test_tenant_isolation_gmail_accounts():
    user_a = _make_user("isoA9")
    user_b = _make_user("isoB9")
    repo.upsert_gmail_account(user_a["id"], "a@gmail.com", "enc-token-a", ["gmail.send"])

    assert repo.get_gmail_accounts(user_b["id"]) == []
    assert len(repo.get_gmail_accounts(user_a["id"])) == 1


# ---------------------------------------------------------------------------
# Shared catalog (companies/jobs) -- intentionally NOT tenant scoped
# ---------------------------------------------------------------------------


def test_mark_company_scraped_stamps_timestamp():
    company = repo.get_or_create_company("Stamp Co", ats_type="greenhouse", ats_token="stamp-co")
    assert company["last_scraped_at"] is None

    repo.mark_company_scraped(company["id"])

    updated = repo.get_or_create_company("Stamp Co", ats_type="greenhouse", ats_token="stamp-co")
    assert updated["last_scraped_at"] is not None


def test_mark_company_scraped_unknown_id_is_a_noop():
    """A nonexistent company_id must not raise -- callers (the ATS
    connectors) always pass an id they just created/fetched, so this is
    purely a defensive no-op, not an expected error path."""
    import uuid
    repo.mark_company_scraped(str(uuid.uuid4()))  # should not raise


def test_get_or_create_company_dedups_by_ats_token():
    c1 = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme")
    c2 = repo.get_or_create_company("Acme Inc", ats_type="greenhouse", ats_token="acme")
    assert c1["id"] == c2["id"]


def test_add_job_dedups_on_company_and_external_id():
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme")
    job1 = repo.add_job(company["id"], "greenhouse", "ext-1", "Backend Engineer")
    job2 = repo.add_job(company["id"], "greenhouse", "ext-1", "Backend Engineer (dup)")
    assert job1 is not None
    assert job2 is None  # duplicate, not re-inserted

    jobs = repo.get_jobs(company["id"])
    assert len(jobs) == 1


def test_add_job_stamps_last_seen_at_and_is_open_on_insert():
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme-fresh")
    job = repo.add_job(company["id"], "greenhouse", "ext-fresh-1", "Backend Engineer")
    assert job["is_open"] is True
    assert job["last_seen_at"] is not None


def test_add_job_restamps_last_seen_at_on_rescrape():
    """A job that's still returned by the company's live API on a later
    sync must get its last_seen_at bumped, and is_open re-confirmed True
    -- even if it had been marked closed in between (e.g. briefly pulled
    then relisted)."""
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme-restamp")
    repo.add_job(company["id"], "greenhouse", "ext-restamp-1", "Backend Engineer")

    # Simulate it having been closed by an intervening sync.
    repo.close_unseen_jobs(company["id"], seen_external_ids=set())
    closed = repo.get_jobs(company["id"])[0]
    assert closed["is_open"] is False

    # Now it shows up again on a fresh sync.
    result = repo.add_job(company["id"], "greenhouse", "ext-restamp-1", "Backend Engineer")
    assert result is None  # still a dedup hit, not a new row

    reopened = repo.get_jobs(company["id"])[0]
    assert reopened["is_open"] is True


def test_close_unseen_jobs_marks_missing_jobs_closed():
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme-close")
    repo.add_job(company["id"], "greenhouse", "ext-still-open", "Still Open Role")
    repo.add_job(company["id"], "greenhouse", "ext-now-closed", "Now Closed Role")

    closed_count = repo.close_unseen_jobs(company["id"], seen_external_ids={"ext-still-open"})
    assert closed_count == 1

    jobs = {j["external_id"]: j for j in repo.get_jobs(company["id"])}
    assert jobs["ext-still-open"]["is_open"] is True
    assert jobs["ext-now-closed"]["is_open"] is False


def test_close_unseen_jobs_never_reopens_anything():
    """close_unseen_jobs only ever closes -- it must never flip an
    already-closed job back to open just because it wasn't in this
    particular seen_external_ids set (that's add_job's job, on a real
    re-scrape hit)."""
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme-noreopen")
    repo.add_job(company["id"], "greenhouse", "ext-a", "Role A")
    repo.close_unseen_jobs(company["id"], seen_external_ids=set())

    already_closed = repo.get_jobs(company["id"])[0]
    assert already_closed["is_open"] is False

    # Calling it again with the job "seen" this time must not touch it --
    # only add_job re-opens.
    closed_count = repo.close_unseen_jobs(company["id"], seen_external_ids={"ext-a"})
    assert closed_count == 0
    still_closed = repo.get_jobs(company["id"])[0]
    assert still_closed["is_open"] is False


def test_get_jobs_open_only_filters_closed_jobs():
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme-openonly")
    repo.add_job(company["id"], "greenhouse", "ext-open", "Open Role")
    repo.add_job(company["id"], "greenhouse", "ext-closed", "Closed Role")
    repo.close_unseen_jobs(company["id"], seen_external_ids={"ext-open"})

    all_jobs = repo.get_jobs(company["id"])
    open_jobs = repo.get_jobs(company["id"], open_only=True)

    assert len(all_jobs) == 2
    assert len(open_jobs) == 1
    assert open_jobs[0]["external_id"] == "ext-open"


# ---------------------------------------------------------------------------
# Shared caches
# ---------------------------------------------------------------------------


def test_enrichment_cache_roundtrip():
    assert repo.get_cached_enrichment("acme.com", "apollo") is None
    repo.set_cached_enrichment("acme.com", "apollo", {"email": "founder@acme.com"})
    cached = repo.get_cached_enrichment("acme.com", "apollo")
    assert cached["result_json"]["email"] == "founder@acme.com"


def test_research_cache_roundtrip():
    company = repo.get_or_create_company("Acme", ats_type="greenhouse", ats_token="acme-research")
    job = repo.add_job(company["id"], "greenhouse", "ext-research-1", "Backend Engineer")

    assert repo.get_cached_research(job["id"]) is None
    repo.set_cached_research(job["id"], {"overview": "A widget company"})
    cached = repo.get_cached_research(job["id"])
    assert cached["result_json"]["overview"] == "A widget company"


def test_get_job_with_company_returns_company_name():
    company = repo.get_or_create_company("Repo Test Co", ats_type="greenhouse", ats_token="repo-test-co")
    job = repo.add_job(company["id"], "greenhouse", "ext-repo-1", "Backend Engineer", apply_url="https://example.com/apply/1")

    result = repo.get_job_with_company(job["id"])
    assert result is not None
    assert result["company_name"] == "Repo Test Co"
    assert result["apply_url"] == "https://example.com/apply/1"
    assert result["title"] == "Backend Engineer"


def test_get_job_with_company_unknown_id_returns_none():
    assert repo.get_job_with_company("00000000-0000-0000-0000-000000000000") is None


def test_get_job_with_company_malformed_id_returns_none_not_error():
    assert repo.get_job_with_company("not-a-uuid") is None


# ---------------------------------------------------------------------------
# Credits (lifetime, no reset) -- 1 credit per completed-pipeline lead
# ---------------------------------------------------------------------------


def _mark_sent(user_id: str, lead_id: str, status: str = "sent"):
    """Move a lead to a credit-consuming terminal state (stamps sent_at)."""
    from datetime import datetime, timezone
    repo.update_lead(user_id, lead_id, {"status": status, "sent_at": datetime.now(timezone.utc)})


def test_credits_free_plan_has_25_lifetime_and_no_reset():
    user = _make_user("credits-free")
    q = repo.get_outreach_quota(user["id"])
    assert q["plan"] == "free"
    assert q["limit"] == 25
    assert q["used"] == 0
    assert q["remaining"] == 25
    # Lifetime credits never reset.
    assert q["reset"] is None


def test_credit_consumed_only_by_completed_pipeline_lead():
    user = _make_user("credits-consume")
    uid = user["id"]

    # A raw matched lead (never completed the pipeline) costs NOTHING.
    raw = repo.add_lead(uid, {"company": "Raw Co", "role": "Engineer"})
    assert repo.get_outreach_quota(uid)["used"] == 0

    # A lead that reaches 'sent' costs 1 credit.
    sent_lead = repo.add_lead(uid, {"company": "Sent Co", "role": "Engineer"})
    _mark_sent(uid, sent_lead["id"], "sent")
    assert repo.get_outreach_quota(uid)["used"] == 1

    # A lead that reaches 'draft_created' also costs 1 credit.
    draft_lead = repo.add_lead(uid, {"company": "Draft Co", "role": "Engineer"})
    _mark_sent(uid, draft_lead["id"], "draft_created")
    q = repo.get_outreach_quota(uid)
    assert q["used"] == 2
    assert q["remaining"] == 23  # 25 - 2


def test_credits_are_lifetime_not_windowed():
    """A completed lead sent long ago still counts -- credits never reset."""
    from datetime import datetime, timezone
    user = _make_user("credits-lifetime")
    uid = user["id"]
    old = repo.add_lead(uid, {"company": "Old Co", "role": "Engineer"})
    # Stamp sent_at a year in the past; a monthly window would have excluded it.
    repo.update_lead(uid, old["id"], {
        "status": "sent",
        "sent_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
    })
    assert repo.get_outreach_quota(uid)["used"] == 1


def test_credits_are_per_tenant_isolated():
    a = _make_user("credits-a")
    b = _make_user("credits-b")
    la = repo.add_lead(a["id"], {"company": "A Co", "role": "Eng"})
    _mark_sent(a["id"], la["id"], "sent")
    # A consumed 1 credit; B's balance is untouched.
    assert repo.get_outreach_quota(a["id"])["used"] == 1
    assert repo.get_outreach_quota(b["id"])["used"] == 0
    assert repo.get_outreach_quota(b["id"])["remaining"] == 25
