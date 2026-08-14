"""Follow-up tracker — checks Gmail threads for sent leads, triggers
follow-up drafts after N days of silence.

This is designed to run as a LangGraph node. When a sent lead has no reply
after FOLLOWUP_DAYS, it returns a state update that signals the graph to
route back into the draft_outreach node with is_followup=True.

Can also run standalone:
    python -m skills.track_followups
"""

import os
import sys
import base64
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.db_client import get_leads, update_lead

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

FOLLOWUP_DAYS = int(os.getenv("FOLLOWUP_DAYS", "5"))
MAX_FOLLOWUPS = int(os.getenv("MAX_FOLLOWUPS", "2"))

def get_gmail_service():
    """Reuse the Gmail auth from send_via_gmail."""
    from skills.send_via_gmail import get_gmail_service as _get_service
    return _get_service()

def check_thread_for_reply(service, contact_email: str, sent_after: str) -> bool:
    """Check if there's a reply from contact_email after the sent_at timestamp.

    Uses Gmail search to find messages FROM the contact in threads where we
    sent TO them. Returns True if a reply exists.
    """
    try:
        # Search for messages from the contact email
        query = f"from:{contact_email}"
        if sent_after:
            # Convert ISO to Gmail's date format (YYYY/MM/DD)
            try:
                dt = datetime.fromisoformat(sent_after.replace("Z", "+00:00"))
                query += f" after:{dt.strftime('%Y/%m/%d')}"
            except (ValueError, TypeError):
                pass

        results = service.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()

        messages = results.get("messages", [])
        return len(messages) > 0

    except Exception as e:
        print(f"  ⚠️  Error checking thread for {contact_email}: {e}")
        return False  # Assume no reply on error — don't skip the follow-up

def days_since_sent(sent_at: str) -> int:
    """Calculate days elapsed since the lead was sent."""
    if not sent_at:
        return 0
    try:
        sent_dt = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - sent_dt).days
    except (ValueError, TypeError):
        return 0

def check_lead_for_followup(service, lead: dict) -> dict | None:
    """Check a single sent lead. Returns a state dict if follow-up needed, else None."""
    lead_id = lead.get("id")
    company = lead.get("company") or lead.get("x_handle") or "Unknown"
    contact_email = lead.get("contact_email") or ""
    sent_at = lead.get("sent_at") or ""
    followup_count = int(lead.get("followup_count") or 0)

    if not contact_email:
        return None

    if followup_count >= MAX_FOLLOWUPS:
        print(f"  ⏭️  {company} — max follow-ups ({MAX_FOLLOWUPS}) reached, skipping")
        return None

    elapsed = days_since_sent(sent_at)
    if elapsed < FOLLOWUP_DAYS:
        print(f"  ⏳ {company} — only {elapsed} days since sent (threshold: {FOLLOWUP_DAYS})")
        return None

    # Check for reply
    has_reply = check_thread_for_reply(service, contact_email, sent_at)

    if has_reply:
        # Mark as replied — no follow-up needed
        update_lead(lead_id, {"status": "replied", "last_checked": _now_iso()})
        print(f"  💬 {company} — reply detected! Status → replied")
        return None

    # No reply after N days — needs a follow-up
    print(f"  📨 {company} — no reply after {elapsed} days, queuing follow-up #{followup_count + 1}")
    return {
        "lead_id": lead_id,
        "company": company,
        "role": lead.get("role") or "",
        "source": lead.get("source") or "",
        "jd_text": lead.get("jd_text") or "",
        "contact_name": lead.get("contact_name") or "",
        "contact_email": contact_email,
        "x_handle": lead.get("x_handle") or "",
        "resume_version": lead.get("resume_version") or "",
        "outreach_draft": lead.get("outreach_draft") or "",
        "followup_count": followup_count + 1,
        "is_followup": True,
        "status": "needs_followup",
    }

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def run():
    """Standalone runner: checks all sent leads and queues follow-ups."""
    print("=" * 60)
    print("  FOLLOW-UP TRACKER — Checking sent leads for replies")
    print(f"  Threshold: {FOLLOWUP_DAYS} days | Max follow-ups: {MAX_FOLLOWUPS}")
    print("=" * 60)
    print()

    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"ERROR: Failed to authenticate with Gmail: {e}")
        return

    leads = get_leads(status="sent")

    if not leads:
        print("No sent leads to check.")
        return

    needs_followup = []

    for lead in leads:
        result = check_lead_for_followup(service, lead)
        if result:
            needs_followup.append(result)

    print(f"\n{len(needs_followup)} leads need follow-ups.")

    # Update their status so draft_outreach picks them up with followup context
    for item in needs_followup:
        lead_id = item["lead_id"]
        update_lead(lead_id, {
            "status": "needs_followup",
            "followup_count": str(item["followup_count"]),
            "last_checked": _now_iso(),
        })

    if needs_followup:
        print("Run draft_outreach next to generate follow-up drafts,")
        print("then feed_graph to queue them for review.")

if __name__ == "__main__":
    run()
