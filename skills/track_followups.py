"""Gmail follow-up helpers -- checks Gmail threads for replies to sent leads.

These are pure helper functions used by graph/pipeline.py's
followup_check_node (LangGraph follow-up cycle entry point). They intentionally
do NOT read/write leads themselves -- that's orchestrator/check_followups.py's
job (the real cron/API entry point, which drives the followup graph per lead
and persists status changes via storage.sheet_client).

A previous version of this file had its own standalone run()/CLI path that
imported a module (storage.db_client) which never existed in this repo -- it
would have raised ImportError the moment it was invoked directly. That dead
code has been removed; the only things kept are the parts graph/pipeline.py
actually imports and depends on at call time.
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

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
        query = f"from:{contact_email}"
        if sent_after:
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
        return False  # Assume no reply on error -- don't skip the follow-up


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
