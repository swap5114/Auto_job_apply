"""v1 Task 6: automated send + follow-up from the user's own Gmail.

Verifies send_node honors the per-user send preference, sends from the
connected address, and treats a not-connected Gmail as a soft, recoverable
state (never a hard failure). No real Google calls.
"""

import graph.pipeline as gp
import skills.send_via_gmail as sg


def _approved_state():
    return {
        "status": "approved",
        "user_id": "user-1",
        "contact_email": "founder@acme.com",
        "outreach_draft": "Subject: Quick idea for Acme\n\nHi — one thing I'd love to explore...",
        "company": "Acme",
        "role": "Backend Engineer",
        "resume_version": "r1",
    }


def test_send_node_direct_mode_sends(monkeypatch):
    calls = {"send": 0, "draft": 0}

    monkeypatch.setattr(sg, "get_user_send_context", lambda uid: ("svc", "me@gmail.com", "direct"))
    monkeypatch.setattr(sg, "resume_pdf_path", lambda lead: "")
    monkeypatch.setattr(sg, "send_email", lambda *a, **k: calls.__setitem__("send", calls["send"] + 1) or {"id": "s1"})
    monkeypatch.setattr(sg, "create_draft", lambda *a, **k: calls.__setitem__("draft", calls["draft"] + 1) or {"id": "d1"})

    result = gp.send_node(_approved_state())
    assert result["status"] == "sent"
    assert calls["send"] == 1 and calls["draft"] == 0


def test_send_node_draft_mode_creates_draft(monkeypatch):
    calls = {"send": 0, "draft": 0}

    monkeypatch.setattr(sg, "get_user_send_context", lambda uid: ("svc", "me@gmail.com", "draft"))
    monkeypatch.setattr(sg, "resume_pdf_path", lambda lead: "")
    monkeypatch.setattr(sg, "send_email", lambda *a, **k: calls.__setitem__("send", calls["send"] + 1) or {"id": "s1"})
    monkeypatch.setattr(sg, "create_draft", lambda *a, **k: calls.__setitem__("draft", calls["draft"] + 1) or {"id": "d1"})

    result = gp.send_node(_approved_state())
    assert result["status"] == "draft_created"
    assert calls["draft"] == 1 and calls["send"] == 0


def test_send_node_no_gmail_is_soft(monkeypatch):
    def raise_no_gmail(uid):
        raise sg.NoGmailConnected("nope")

    monkeypatch.setattr(sg, "get_user_send_context", raise_no_gmail)

    result = gp.send_node(_approved_state())
    # Soft, recoverable -- NOT send_failed. The lead stays actionable.
    assert result["status"] == "approved_needs_gmail"


def test_send_node_skips_when_not_approved():
    result = gp.send_node({"status": "rejected", "user_id": "u"})
    assert result["status"] == "rejected"


def test_run_returns_no_gmail_connected_when_unconnected(monkeypatch):
    """skills.send_via_gmail.run(user_id) with no connected Gmail is a soft
    no-op summary, not an exception."""
    monkeypatch.setattr(sg.repo, "get_gmail_account", lambda uid: None)
    summary = sg.run(user_id="user-without-gmail")
    assert summary["error"] == "no_gmail_connected"
    assert summary["sent"] == 0 and summary["draft_created"] == 0
