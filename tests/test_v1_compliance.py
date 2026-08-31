"""v1 Task 14: outgoing emails carry a CAN-SPAM compliance footer (opt-out
line always; physical address when configured)."""

import base64

import skills.send_via_gmail as sg


def _decode(raw_b64: str) -> str:
    return base64.urlsafe_b64decode(raw_b64.encode()).decode("utf-8", "ignore")


def test_email_body_includes_optout_line(monkeypatch):
    monkeypatch.delenv("COMPLIANCE_ADDRESS", raising=False)
    monkeypatch.setenv("COMPLIANCE_UNSUBSCRIBE_NOTE", "Reply STOP to opt out.")

    raw = sg.build_email_message(
        to="founder@acme.com", subject="Hi", body="Hello there.", sender="me@gmail.com"
    )
    decoded = _decode(raw)
    assert "Hello there." in decoded
    assert "Reply STOP to opt out." in decoded


def test_email_body_includes_physical_address_when_set(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_ADDRESS", "123 Example St, Springfield, USA")
    monkeypatch.setenv("COMPLIANCE_UNSUBSCRIBE_NOTE", "Reply to opt out.")

    raw = sg.build_email_message(
        to="founder@acme.com", subject="Hi", body="Hello.", sender="me@gmail.com"
    )
    decoded = _decode(raw)
    assert "123 Example St, Springfield, USA" in decoded
    assert "Reply to opt out." in decoded
