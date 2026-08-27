"""Phase 4 (Pipeline Engine) tests.

Covers:
  4.1 -- user-scoping regression: feed_pending_leads(user_id=...) only
         touches the caller's own leads (same shape as Phase 0's
         tenant-isolation tests in test_repository.py).
  4.2 -- Postgres checkpointer survives a simulated worker restart (new
         connection pool, same thread_id) with paused state intact.
  4.3 -- PipelineState carries user_id, and it flows through
         feed_pending_leads/check_and_queue_followups into the graph.
  4.4 -- Cloud Tasks enqueue path: with USE_CLOUD_TASKS=false (default),
         pipeline tasks still run via the in-process fallback; a task with
         an invalid type is rejected; /tasks/run rejects missing/invalid
         auth.
  4.6 -- Concurrency: two users' leads paused at review are independently
         resumable, and neither's approve/reject call touches the other's
         checkpoint or leads row.

Every external boundary the graph can reach (find_contact_email_for_lead,
research_company, tailor_resume_for_lead, llm_generate, load_tailored_resume,
the Gmail service) is mocked, same discipline as tests/test_phase7_review.py
-- these tests exercise the pipeline engine's plumbing (checkpointing,
user_id threading, task dispatch), not real network calls.
"""

import os
import threading
import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from graph.pipeline import (
    build_pipeline_graph,
    get_postgres_checkpointer,
    reset_postgres_checkpointer_pool,
    make_thread_id,
)


def _make_user(suffix: str) -> dict:
    return repo.create_user(firebase_uid=f"fb-phase4-{suffix}", email=f"phase4-{suffix}@example.com")


def _mock_graph_externals():
    """Returns a list of unittest.mock.patch objects covering every
    external boundary the pipeline graph can reach -- same set
    tests/test_phase7_review.py mocks, reused here so these tests never
    place a real network call either.
    """
    fake_gmail_service = MagicMock()
    return [
        patch(
            "skills.find_contact_email.find_contact_email_for_lead",
            return_value={"contact_email": "contact@example.com", "contact_name": "Jamie Contact"},
        ),
        patch(
            "skills.research_company.research_company",
            return_value={
                "overview": "A test company.",
                "stage": "Growth-stage",
                "industry": "Software",
                "tech_signals": ["Python"],
                "demo_project": {
                    "title": "Test demo",
                    "description": "A small demo.",
                    "tech_stack": ["Python"],
                    "deliverable": "GitHub repo",
                    "time_estimate": "2-3 days",
                },
                "talking_points": [],
                "smart_questions": [],
                "fit_summary": "Good fit.",
            },
        ),
        patch(
            "skills.tailor_resume.tailor_resume_for_lead",
            return_value={"resume_version": "fake_resume_version", "keyword_coverage": 50.0},
        ),
        patch(
            "skills.llm_client.llm_generate",
            return_value="Subject: Test outreach\n\nThis is a test draft.",
        ),
        patch(
            "skills.draft_outreach.load_tailored_resume",
            return_value={"name": "Test Candidate", "contact": {}, "skills": {}},
        ),
        patch("skills.send_via_gmail.get_gmail_service", return_value=fake_gmail_service),
        patch("skills.send_via_gmail.send_email", return_value={"id": "fake-sent-id"}),
        patch("skills.send_via_gmail.create_draft", return_value={"id": "fake-draft-id"}),
        # Phase 5.2: draft_cover_note_node's external boundary (the apply
        # channel's counterpart to draft_outreach.load_tailored_resume /
        # llm_generate above).
        patch(
            "skills.draft_cover_note.load_tailored_resume",
            return_value={"name": "Test Candidate", "contact": {}, "skills": {}},
        ),
        patch(
            "skills.draft_cover_note.draft_cover_note",
            return_value="Dear hiring team, ... Test Candidate",
        ),
    ]


@pytest.fixture
def mocked_graph_externals():
    patchers = _mock_graph_externals()
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


@pytest.fixture
def pg_checkpointer():
    """A real Postgres checkpointer against the test database, cleaned up
    (pool closed) after each test so tests don't leak pooled connections
    into each other.
    """
    reset_postgres_checkpointer_pool()
    cp = get_postgres_checkpointer()
    yield cp
    reset_postgres_checkpointer_pool()


# ---------------------------------------------------------------------------
# 4.1 -- user-scoping regression test
# ---------------------------------------------------------------------------


def test_feed_pending_leads_only_touches_callers_own_leads(mocked_graph_externals, pg_checkpointer):
    from orchestrator.feed_graph import feed_pending_leads

    user_a = _make_user("feedA")
    user_b = _make_user("feedB")

    lead_a = repo.add_lead(user_a["id"], {
        "company": "Only A", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })
    lead_b = repo.add_lead(user_b["id"], {
        "company": "Only B", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })

    fed_count = feed_pending_leads(user_id=user_a["id"])

    assert fed_count == 1

    # User A's lead was fed (marked in_review); user B's was left untouched
    # at pending_review -- feed_pending_leads(user_id=A) must never process
    # or even look at B's rows.
    a_after = repo.get_lead(user_a["id"], lead_a["id"])
    b_after = repo.get_lead(user_b["id"], lead_b["id"])
    assert a_after["status"] == "in_review"
    assert b_after["status"] == "pending_review"

    # And the checkpoint store only has a thread for A's lead, scoped by
    # user_id (Phase 4.2) -- confirms structural isolation, not just "we
    # didn't call update_lead for B."
    from orchestrator.review_cli import get_all_thread_ids

    a_threads = get_all_thread_ids(user_a["id"], checkpointer=pg_checkpointer)
    b_threads = get_all_thread_ids(user_b["id"], checkpointer=pg_checkpointer)
    # Phase 5.2: feed_pending_leads now creates channel-scoped threads (a
    # lead with no explicit channel defaults to ["outreach"]) -- so the
    # thread actually created is the 3-part outreach-scoped id, not the
    # legacy 2-arg shape (which is still supported by make_thread_id for
    # already-in-flight pre-Phase-5 threads, just not what a fresh feed
    # produces anymore).
    assert make_thread_id(user_a["id"], lead_a["id"], channel="outreach") in a_threads
    assert make_thread_id(user_b["id"], lead_b["id"], channel="outreach") not in a_threads
    assert b_threads == []


# ---------------------------------------------------------------------------
# 4.2 -- Postgres checkpointer survives a simulated worker restart
# ---------------------------------------------------------------------------


def test_postgres_checkpointer_survives_simulated_restart(mocked_graph_externals, pg_checkpointer):
    from orchestrator.feed_graph import feed_pending_leads

    user = _make_user("restart")
    lead = repo.add_lead(user["id"], {
        "company": "Restart Co", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })

    feed_pending_leads(user_id=user["id"])

    # Phase 5.2: a lead with no explicit channel defaults to ["outreach"],
    # fed as a channel-scoped thread.
    thread_id = make_thread_id(user["id"], lead["id"], channel="outreach")
    config = {"configurable": {"thread_id": thread_id}}

    graph_before = build_pipeline_graph(pg_checkpointer)
    state_before = graph_before.get_state(config)
    assert state_before is not None
    assert "review" in state_before.next
    assert state_before.values.get("company") == "Restart Co"

    # Simulate a worker restart: close the pool, drop the module-level
    # singleton, and get a brand new checkpointer/connection pool -- the
    # exact same as what actually happens when a real worker process is
    # killed and relaunched.
    reset_postgres_checkpointer_pool()
    new_checkpointer = get_postgres_checkpointer()

    graph_after = build_pipeline_graph(new_checkpointer)
    state_after = graph_after.get_state(config)

    assert state_after is not None
    assert "review" in state_after.next
    assert state_after.values.get("company") == "Restart Co"
    assert state_after.values.get("user_id") == user["id"]

    # And the resumed graph can still be driven forward correctly after
    # the "restart" -- approve_lead using the new checkpointer instance.
    from orchestrator.review_cli import approve_lead

    approved = approve_lead(lead["id"], user_id=user["id"], checkpointer=new_checkpointer)
    assert approved is True

    final_state = graph_after.get_state(config)
    assert final_state.next == ()
    assert final_state.values.get("review_decision") == "approved"


# ---------------------------------------------------------------------------
# 4.3 -- user_id flows through PipelineState
# ---------------------------------------------------------------------------


def test_user_id_is_set_in_pipeline_state_after_feed(mocked_graph_externals, pg_checkpointer):
    from orchestrator.feed_graph import feed_pending_leads

    user = _make_user("stateuid")
    lead = repo.add_lead(user["id"], {
        "company": "State Co", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })

    feed_pending_leads(user_id=user["id"])

    graph = build_pipeline_graph(pg_checkpointer)
    # Phase 5.2: a lead with no explicit channel defaults to ["outreach"],
    # fed as a channel-scoped thread.
    thread_id = make_thread_id(user["id"], lead["id"], channel="outreach")
    state = graph.get_state({"configurable": {"thread_id": thread_id}})

    assert state.values.get("user_id") == user["id"]


def test_check_and_queue_followups_sets_user_id_and_is_scoped(mocked_graph_externals, pg_checkpointer):
    from orchestrator.check_followups import check_and_queue_followups

    user_a = _make_user("followA")
    user_b = _make_user("followB")

    lead_a = repo.add_lead(user_a["id"], {
        "company": "Follow A", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "sent", "contact_email": "a@example.com", "followup_count": 0,
    })
    lead_b = repo.add_lead(user_b["id"], {
        "company": "Follow B", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "sent", "contact_email": "b@example.com", "followup_count": 0,
    })

    with patch("skills.track_followups.get_gmail_service", return_value=MagicMock()), \
         patch("skills.track_followups.check_thread_for_reply", return_value=False):
        check_and_queue_followups(user_id=user_a["id"])

    from graph.pipeline import build_followup_graph, make_followup_thread_id

    followup_graph = build_followup_graph(pg_checkpointer)
    thread_a = make_followup_thread_id(user_a["id"], lead_a["id"], 0)
    thread_b = make_followup_thread_id(user_b["id"], lead_b["id"], 0)

    state_a = followup_graph.get_state({"configurable": {"thread_id": thread_a}})
    state_b = followup_graph.get_state({"configurable": {"thread_id": thread_b}})

    # A's follow-up ran (state exists, user_id correctly set); B's never
    # started because check_and_queue_followups was scoped to user_a only.
    assert state_a is not None
    assert state_a.values.get("user_id") == user_a["id"]
    assert state_b is None or not state_b.values


# ---------------------------------------------------------------------------
# 4.4 -- Cloud Tasks enqueue path (local fallback + worker auth)
# ---------------------------------------------------------------------------


def test_enqueue_pipeline_task_runs_locally_when_cloud_tasks_disabled(monkeypatch):
    import api.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "USE_CLOUD_TASKS", False)

    called = {}

    def _fake_dispatch(user_id, task_type, payload):
        called["user_id"] = user_id
        called["task_type"] = task_type
        called["payload"] = payload
        return {"task_type": task_type, "result": {}}

    with patch("orchestrator.task_dispatch.dispatch_task", side_effect=_fake_dispatch):
        result = tasks_mod.enqueue_pipeline_task(
            "some-user-id", "check_followups", {"foo": "bar"}
        )

    assert result["mode"] == "local"
    # Local dispatch runs on a daemon thread -- give it a moment to execute.
    for _ in range(50):
        if called:
            break
        time.sleep(0.02)

    assert called.get("user_id") == "some-user-id"
    assert called.get("task_type") == "check_followups"
    assert called.get("payload") == {"foo": "bar"}


def test_enqueue_pipeline_task_rejects_unknown_task_type():
    import api.tasks as tasks_mod
    from orchestrator.task_dispatch import UnknownTaskTypeError

    with pytest.raises(UnknownTaskTypeError):
        tasks_mod.enqueue_pipeline_task("some-user-id", "not_a_real_task_type", {})


def test_worker_tasks_run_rejects_missing_auth_header(monkeypatch):
    import worker.main as worker_mod

    monkeypatch.setattr(worker_mod, "WORKER_SHARED_SECRET", "correct-secret")
    client = TestClient(worker_mod.app)

    resp = client.post("/tasks/run", json={"user_id": "x", "task_type": "check_followups"})
    assert resp.status_code == 401


def test_worker_tasks_run_rejects_wrong_secret(monkeypatch):
    import worker.main as worker_mod

    monkeypatch.setattr(worker_mod, "WORKER_SHARED_SECRET", "correct-secret")
    client = TestClient(worker_mod.app)

    resp = client.post(
        "/tasks/run",
        json={"user_id": "x", "task_type": "check_followups"},
        headers={"X-Worker-Shared-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401


def test_worker_tasks_run_fails_closed_when_secret_unconfigured(monkeypatch):
    import worker.main as worker_mod

    monkeypatch.setattr(worker_mod, "WORKER_SHARED_SECRET", "")
    client = TestClient(worker_mod.app)

    resp = client.post(
        "/tasks/run",
        json={"user_id": "x", "task_type": "check_followups"},
        headers={"X-Worker-Shared-Secret": "anything"},
    )
    assert resp.status_code == 401


def test_worker_tasks_run_dispatches_with_valid_secret(monkeypatch):
    import worker.main as worker_mod

    monkeypatch.setattr(worker_mod, "WORKER_SHARED_SECRET", "correct-secret")
    client = TestClient(worker_mod.app)

    with patch(
        "orchestrator.task_dispatch.dispatch_task",
        return_value={"task_type": "check_followups", "result": {"followups_queued": 0}},
    ) as mock_dispatch:
        resp = client.post(
            "/tasks/run",
            json={"user_id": "some-user", "task_type": "check_followups", "payload": {}},
            headers={"X-Worker-Shared-Secret": "correct-secret"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    mock_dispatch.assert_called_once_with(user_id="some-user", task_type="check_followups", payload={})


def test_worker_tasks_run_rejects_unknown_task_type_as_400(monkeypatch):
    import worker.main as worker_mod

    monkeypatch.setattr(worker_mod, "WORKER_SHARED_SECRET", "correct-secret")
    client = TestClient(worker_mod.app)

    resp = client.post(
        "/tasks/run",
        json={"user_id": "some-user", "task_type": "not_a_real_task_type"},
        headers={"X-Worker-Shared-Secret": "correct-secret"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4.6 -- Concurrency: two users' pipelines run independently
# ---------------------------------------------------------------------------


def test_two_users_paused_leads_are_independently_resumable(mocked_graph_externals, pg_checkpointer):
    """The plan's own test gate, in miniature: two different users, each
    with a lead paused at review, resolved independently -- approving
    user A's lead must never affect user B's paused state, and vice versa.
    """
    from orchestrator.feed_graph import feed_pending_leads
    from orchestrator.review_cli import approve_lead, reject_lead, get_pending_review_leads

    user_a = _make_user("concA")
    user_b = _make_user("concB")

    lead_a = repo.add_lead(user_a["id"], {
        "company": "Concurrent A", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })
    lead_b = repo.add_lead(user_b["id"], {
        "company": "Concurrent B", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })

    # Feed both users' leads "at the same time" (sequential calls are
    # sufficient to prove no cross-contamination; true thread-level
    # concurrency is exercised by the threading.Thread pair below).
    feed_pending_leads(user_id=user_a["id"])
    feed_pending_leads(user_id=user_b["id"])

    pending_a = get_pending_review_leads(user_a["id"], checkpointer=pg_checkpointer)
    pending_b = get_pending_review_leads(user_b["id"], checkpointer=pg_checkpointer)
    assert [p["lead_id"] for p in pending_a] == [lead_a["id"]]
    assert [p["lead_id"] for p in pending_b] == [lead_b["id"]]

    # Approve A, reject B -- confirm each only affected their own tenant.
    assert approve_lead(lead_a["id"], user_id=user_a["id"], checkpointer=pg_checkpointer) is True
    assert reject_lead(lead_b["id"], user_id=user_b["id"], checkpointer=pg_checkpointer) is True

    a_lead_after = repo.get_lead(user_a["id"], lead_a["id"])
    b_lead_after = repo.get_lead(user_b["id"], lead_b["id"])
    assert a_lead_after["status"] == "approved"
    assert b_lead_after["status"] == "rejected"

    # Neither user has any leads left paused at review.
    assert get_pending_review_leads(user_a["id"], checkpointer=pg_checkpointer) == []
    assert get_pending_review_leads(user_b["id"], checkpointer=pg_checkpointer) == []


def test_two_users_pipelines_run_concurrently_on_separate_threads(mocked_graph_externals, pg_checkpointer):
    """Runs two users' feed_pending_leads calls on separate real threads at
    the same time (the actual shape of two people clicking "Run Pipeline"
    simultaneously), then confirms both landed correctly with no
    cross-contamination -- this is what a single global threading.Lock
    (the pre-Phase-4 bug) would have serialized/corrupted.
    """
    from orchestrator.feed_graph import feed_pending_leads

    user_a = _make_user("threadA")
    user_b = _make_user("threadB")

    lead_a = repo.add_lead(user_a["id"], {
        "company": "Thread A", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })
    lead_b = repo.add_lead(user_b["id"], {
        "company": "Thread B", "role": "Engineer", "jd_text": "Python backend role.",
        "status": "pending_review",
    })

    results = {}

    def _feed(label, user_id):
        results[label] = feed_pending_leads(user_id=user_id)

    t_a = threading.Thread(target=_feed, args=("a", user_a["id"]))
    t_b = threading.Thread(target=_feed, args=("b", user_b["id"]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=30)
    t_b.join(timeout=30)

    assert results.get("a") == 1
    assert results.get("b") == 1

    a_after = repo.get_lead(user_a["id"], lead_a["id"])
    b_after = repo.get_lead(user_b["id"], lead_b["id"])
    assert a_after["status"] == "in_review"
    assert b_after["status"] == "in_review"

    from orchestrator.review_cli import get_pending_review_leads

    pending_a = get_pending_review_leads(user_a["id"], checkpointer=pg_checkpointer)
    pending_b = get_pending_review_leads(user_b["id"], checkpointer=pg_checkpointer)
    assert [p["lead_id"] for p in pending_a] == [lead_a["id"]]
    assert [p["lead_id"] for p in pending_b] == [lead_b["id"]]


# ---------------------------------------------------------------------------
# 4.5 -- Apply/Outreach router scaffold
# ---------------------------------------------------------------------------


def test_route_channel_node_defaults_to_outreach_and_continues():
    from graph.pipeline import route_channel_node

    result = route_channel_node({"channel": ["outreach"], "company": "X"})
    assert result["active_channel"] == "outreach"
    assert result["status"] != "apply_channel_not_implemented"


def test_route_channel_node_apply_only_continues():
    """Phase 5.2 replaces the old apply -> apply_channel_not_implemented
    dead-end: an apply-only lead now continues into the shared research/
    tailor flow, same as outreach, rather than ending the run.
    """
    from graph.pipeline import route_channel_node

    result = route_channel_node({"channel": ["apply"], "company": "X"})
    assert result["active_channel"] == "apply"
    assert result["status"] != "apply_channel_not_implemented"


# ---------------------------------------------------------------------------
# Phase 5.2 -- apply-channel graph run + dual-channel thread independence
# ---------------------------------------------------------------------------


def test_apply_channel_lead_reaches_review_interrupt_not_end(mocked_graph_externals, pg_checkpointer):
    """Direct regression guard for 5.2's replacement of route_channel_node's
    old dead-end: an apply-only lead run through the real graph must pause
    at the review interrupt (with a cover_note drafted), not run straight
    to END via the old dead-end, and must never reach the outreach-only
    send node (no contact_email/outreach_draft is even present in state).
    """
    user = _make_user("applyReview")
    lead_id = "apply-lead-001"

    graph = build_pipeline_graph(pg_checkpointer)
    thread_id = make_thread_id(user["id"], lead_id, channel="apply")
    config = {"configurable": {"thread_id": thread_id}}

    state = {
        "user_id": user["id"],
        "lead_id": lead_id,
        "source": "greenhouse",
        "company": "Apply Test Co",
        "role": "Backend Engineer",
        "jd_text": "Python backend role.",
        "listing_url": "https://example.com/jobs/apply-lead-001",
        "channel": ["apply"],
        "active_channel": "apply",
        "status": "matched",
    }

    graph.invoke(state, config)

    result_state = graph.get_state(config)
    assert result_state is not None
    assert "review" in result_state.next
    assert result_state.values.get("cover_note") == "Dear hiring team, ... Test Candidate"
    assert result_state.values.get("resume_version") == "fake_resume_version"
    # Never touched the outreach-only fields/nodes.
    assert not result_state.values.get("outreach_draft")


def test_apply_channel_approve_sets_ready_to_apply_not_approved(mocked_graph_externals, pg_checkpointer):
    """Approving an apply-channel review must land on "ready_to_apply"
    (the plan's own state-machine naming), not "approved" -- and must
    never reach send_node (apply has no send step).
    """
    from orchestrator.review_cli import approve_lead

    user = _make_user("applyApprove")
    lead_id = "apply-lead-002"
    repo.add_lead(user["id"], {
        "company": "Apply Approve Co", "role": "Engineer", "jd_text": "Python backend role.",
        "channel": ["apply"], "status": "pending_review",
    })

    graph = build_pipeline_graph(pg_checkpointer)
    thread_id = make_thread_id(user["id"], lead_id, channel="apply")
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke({
        "user_id": user["id"], "lead_id": lead_id, "company": "Apply Approve Co",
        "role": "Engineer", "jd_text": "Python backend role.", "channel": ["apply"],
        "active_channel": "apply", "status": "matched",
    }, config)

    approved = approve_lead(lead_id, user_id=user["id"], checkpointer=pg_checkpointer, channel="apply")
    assert approved is True

    final_state = graph.get_state(config)
    assert final_state.next == ()  # completed, no send node reached
    assert final_state.values.get("status") == "ready_to_apply"
    assert final_state.values.get("review_decision") == "approved"


def test_dual_channel_lead_gets_two_independent_threads(mocked_graph_externals, pg_checkpointer):
    """A lead with channel = ["apply", "outreach"] must produce two
    independent, correctly-scoped graph threads (5.2's thread_id-per-channel
    decision) -- approving one must not affect the other's paused state.
    """
    from orchestrator.feed_graph import feed_pending_leads
    from orchestrator.review_cli import approve_lead, get_pending_review_leads

    user = _make_user("dualChannel")
    lead = repo.add_lead(user["id"], {
        "company": "Dual Channel Co", "role": "Engineer", "jd_text": "Python backend role.",
        "channel": ["apply", "outreach"], "status": "pending_review",
    })

    fed_count = feed_pending_leads(user_id=user["id"])
    assert fed_count == 2  # one run per channel, same lead

    graph = build_pipeline_graph(pg_checkpointer)
    apply_thread = make_thread_id(user["id"], lead["id"], channel="apply")
    outreach_thread = make_thread_id(user["id"], lead["id"], channel="outreach")

    apply_state = graph.get_state({"configurable": {"thread_id": apply_thread}})
    outreach_state = graph.get_state({"configurable": {"thread_id": outreach_thread}})
    assert "review" in apply_state.next
    assert "review" in outreach_state.next
    assert apply_state.values.get("cover_note") == "Dear hiring team, ... Test Candidate"
    assert outreach_state.values.get("outreach_draft") == "Subject: Test outreach\n\nThis is a test draft."

    pending = get_pending_review_leads(user["id"], checkpointer=pg_checkpointer)
    assert len(pending) == 2
    channels_pending = sorted(p["active_channel"] for p in pending)
    assert channels_pending == ["apply", "outreach"]

    # Approve only the apply-channel thread.
    approved = approve_lead(lead["id"], user_id=user["id"], checkpointer=pg_checkpointer, channel="apply")
    assert approved is True

    apply_after = graph.get_state({"configurable": {"thread_id": apply_thread}})
    outreach_after = graph.get_state({"configurable": {"thread_id": outreach_thread}})
    assert apply_after.next == ()  # apply thread resolved
    assert apply_after.values.get("status") == "ready_to_apply"
    # The outreach thread must be completely untouched by approving apply.
    assert "review" in outreach_after.next
    assert outreach_after.values.get("review_decision") is None


def test_route_channel_node_both_channels_prefers_outreach():
    from graph.pipeline import route_channel_node

    result = route_channel_node({"channel": ["apply", "outreach"], "company": "X"})
    assert result["active_channel"] == "outreach"


# ---------------------------------------------------------------------------
# 4.4 -- PipelineRun repository layer + per-user /api/pipeline/run-status
# ---------------------------------------------------------------------------


def test_pipeline_run_repo_crud_and_tenant_scoping():
    user_a = _make_user("runA")
    user_b = _make_user("runB")

    run_a = repo.create_pipeline_run(user_a["id"])
    assert run_a["status"] == "running"
    assert run_a["steps"] == []

    # get_running_pipeline_run is scoped -- B has no running run even
    # though A does.
    assert repo.get_running_pipeline_run(user_a["id"]) is not None
    assert repo.get_running_pipeline_run(user_b["id"]) is None

    repo.append_pipeline_run_step(run_a["id"], "scrape:arbeitnow", "running")
    repo.append_pipeline_run_step(run_a["id"], "scrape:arbeitnow", "ok")
    updated = repo.update_pipeline_run(run_a["id"], {"status": "completed", "summary": {"ok": 1}})

    assert updated["status"] == "completed"
    assert updated["steps"] == [{"step": "scrape:arbeitnow", "status": "ok"}]
    assert updated["summary"] == {"ok": 1}

    # No longer "running" once completed.
    assert repo.get_running_pipeline_run(user_a["id"]) is None

    latest_a = repo.get_latest_pipeline_run(user_a["id"])
    assert latest_a["id"] == run_a["id"]
    assert repo.get_latest_pipeline_run(user_b["id"]) is None


def test_run_status_and_run_endpoints_are_scoped_per_user():
    """api/main.py's /api/pipeline/run + /api/pipeline/run-status must
    never let one user's run block or leak into another's -- the exact
    concurrency bug PHASE_4_PLAN.md's 4.4 calls out (a single global dict
    + lock meant a second user's call got a spurious 409).
    """
    import api.main as api_main
    from api.main import app

    client = TestClient(app)
    token_a = {"uid": "fb-run-status-a", "email": "run-status-a@example.com"}
    token_b = {"uid": "fb-run-status-b", "email": "run-status-b@example.com"}

    def _headers():
        return {"Authorization": "Bearer whatever-a-real-token-would-be"}

    # Before either user has ever run anything, run-status returns the
    # "nothing running" shape, not a leftover global dict shared with
    # whichever other test ran last in this process.
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_a):
        resp = client.get("/api/pipeline/run-status", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["running"] is False

    user_a = repo.get_or_create_user(firebase_uid=token_a["uid"], email=token_a["email"])

    # Seed a running run directly for user A (bypassing the real
    # sourcing pipeline, which would hit real scrapers/LLMs) -- this is
    # exactly the state /api/pipeline/run's 409 check reads.
    repo.create_pipeline_run(user_a["id"])

    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_a):
        resp_a_status = client.get("/api/pipeline/run-status", headers=_headers())
    assert resp_a_status.json()["running"] is True

    # User B triggering /api/pipeline/run must NOT get a 409 just because
    # A has a run in progress -- this is the core Phase 4.4 bug fix.
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_b), \
         patch("threading.Thread") as mock_thread:
        resp_b_run = client.post("/api/pipeline/run", json={}, headers=_headers())
    assert resp_b_run.status_code == 200
    mock_thread.assert_called_once()

    # And user A triggering it again WHILE their own run is still marked
    # running must 409 (the per-user check still works).
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_a):
        resp_a_run_again = client.post("/api/pipeline/run", json={}, headers=_headers())
    assert resp_a_run_again.status_code == 409

    # User B's run-status is unaffected by A's running/finished state.
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_b):
        resp_b_status = client.get("/api/pipeline/run-status", headers=_headers())
    # B's own run was "started" via the (mocked) background thread above,
    # so a pipeline_runs row exists for B too, but it must never report A's
    # data.
    assert resp_b_status.status_code == 200
