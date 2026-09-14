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

# H-2: read these LIVE (not as import-time constants) so a Settings change
# that writes FOLLOWUP_DAYS/MAX_FOLLOWUPS takes effect on the next run
# without a process restart. The module-level names are kept as backward-
# compatible defaults for any code still referencing them directly, but the
# pipeline reads via get_followup_days()/get_max_followups() at call time.
def _read_env_int_live(key: str, default: int) -> int:
    """Read an int env var live, preferring config/.env at call time so a
    settings write is picked up without restarting. Falls back to the
    process env, then the default."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "config", ".env")
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    try:
                        return int(val)
                    except ValueError:
                        break
    except FileNotFoundError:
        pass
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_followup_days() -> int:
    return _read_env_int_live("FOLLOWUP_DAYS", 5)


def get_max_followups() -> int:
    return _read_env_int_live("MAX_FOLLOWUPS", 1)


# Backward-compatible module constants (import-time snapshot). Prefer the
# get_*() functions above in code paths that must honor a live settings change.
FOLLOWUP_DAYS = get_followup_days()
MAX_FOLLOWUPS = get_max_followups()


def get_gmail_service(user_id: str | None = None):
    """Reuse the Gmail auth from send_via_gmail. When user_id is given, builds
    the service from THAT user's own connected Gmail (v1 Task 6); otherwise
    falls back to the shared single-operator token."""
    from skills.send_via_gmail import get_gmail_service as _get_service
    return _get_service(user_id)


def check_thread_for_reply(service, contact_email: str, sent_after: str) -> bool:
    """Check if there's a reply from contact_email after we sent to them.

    M-1: scope the reply check to messages in threads we actually sent TO
    this contact, AND after the sent timestamp, so unrelated inbound mail
    from the same address (a newsletter, an old thread, a different topic)
    doesn't get miscounted as a "reply" and wrongly suppress a follow-up.

    Query semantics:
      - `from:{contact_email}`  -> messages authored by the contact
      - `in:inbox`              -> received (not our own sent copy)
      - `after:YYYY/MM/DD`      -> only since we sent (when sent_after known)
    We then confirm at least one matching message is in a thread that also
    contains a message we sent to that contact (to:{contact_email}).
    """
    if not contact_email:
        return False
    try:
        query = f"from:{contact_email} in:inbox"
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
        if not messages:
            return False

        # Confirm the reply lives in a thread we actually started with this
        # contact -- i.e. a thread that also has a message we sent TO them.
        for msg in messages:
            thread_id = msg.get("threadId")
            if not thread_id:
                continue
            try:
                thread = service.users().threads().get(
                    userId="me", id=thread_id, format="metadata",
                    metadataHeaders=["From", "To"],
                ).execute()
            except Exception:
                # If we can't fetch the thread, fall back to counting the
                # inbound message as a reply rather than silently dropping it.
                return True
            we_sent_here = False
            for tmsg in thread.get("messages", []):
                headers = {h["name"].lower(): h["value"]
                           for h in tmsg.get("payload", {}).get("headers", [])}
                if contact_email.lower() in (headers.get("to", "") or "").lower():
                    we_sent_here = True
                    break
            if we_sent_here:
                return True
        return False

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
