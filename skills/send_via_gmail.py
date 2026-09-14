"""Gmail skill — creates drafts (or sends directly) for approved leads.

OAuth2 flow:
    - First run: opens browser for consent, saves refresh token to config/gmail_token.json
    - Subsequent runs: uses stored token (auto-refreshes when expired)

Config flags (in config/.env):
    GMAIL_DIRECT_SEND=false   -> creates drafts only (v1 default, you send manually)
    GMAIL_DIRECT_SEND=true    -> sends directly for approved leads

Usage:
    python -m skills.send_via_gmail
"""

import os
import sys
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import repository as repo
from db.current_user import get_current_user_id

RESUMES_DIR = os.path.join(os.path.dirname(__file__), "..", "resumes")

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
TOKEN_PATH = os.path.join(CONFIG_DIR, "gmail_token.json")
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "gmail_credentials.json")

# Scopes: compose = create drafts, send = actually send
SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

GMAIL_DIRECT_SEND = os.getenv("GMAIL_DIRECT_SEND", "false").lower() == "true"
SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "")  # Your Gmail address


def is_direct_send() -> bool:
    """Read GMAIL_DIRECT_SEND live from config/.env at call time.

    Reading live (instead of the import-time constant) means toggling the
    Settings -> Gmail Mode switch, which writes to .env, takes effect on the
    next send without restarting the server.
    """
    env_path = os.path.join(CONFIG_DIR, ".env")
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GMAIL_DIRECT_SEND="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return val.lower() == "true"
    except FileNotFoundError:
        pass
    return os.getenv("GMAIL_DIRECT_SEND", "false").lower() == "true"

# ---------------------------------------------------------------------------
# OAuth2 token management
# ---------------------------------------------------------------------------

def get_gmail_credentials():
    """Load or create OAuth2 credentials for Gmail API.

    First run: triggers browser-based consent flow, saves token.
    Subsequent runs: loads saved token, refreshes if expired.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    # Load existing token
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # Refresh or re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed ({e}), re-authorizing...")
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"Gmail OAuth credentials file not found at {CREDENTIALS_PATH}.\n"
                    "Download it from Google Cloud Console:\n"
                    "  1. Go to https://console.cloud.google.com/apis/credentials\n"
                    "  2. Create an OAuth 2.0 Client ID (Desktop app type)\n"
                    "  3. Download the JSON and save it as config/gmail_credentials.json"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for next run
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())
        print(f"Gmail token saved to {TOKEN_PATH}")

    return creds

class NoGmailConnected(Exception):
    """Raised when a per-user send is attempted but the user hasn't connected
    their Gmail (v1 Task 6). Callers treat this as a soft, recoverable state
    ("approved, needs Gmail"), NOT a hard error that kills the batch."""


def _service_from_credentials(creds):
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=creds)


def get_gmail_service(user_id: str | None = None):
    """Build a Gmail API service.

    v1: when user_id is given, build credentials from THAT user's own stored
    (encrypted) OAuth refresh token (per-user Gmail, Task 5/6) so mail sends
    from their inbox, not a shared account. Raises NoGmailConnected if the
    user hasn't connected Gmail yet.

    When user_id is None (the single-operator CLI / legacy path), fall back to
    the shared config/gmail_token.json desktop token, unchanged.
    """
    if user_id is None:
        return _service_from_credentials(get_gmail_credentials())

    from api import gmail_oauth
    from google.auth.transport.requests import Request

    acct = repo.get_gmail_account(user_id)
    if not acct:
        raise NoGmailConnected(f"User {user_id} has not connected a Gmail account")

    refresh_token = gmail_oauth.decrypt_token(acct["encrypted_refresh_token"])
    creds = gmail_oauth.build_credentials_from_refresh_token(refresh_token)
    # Mint a fresh access token from the refresh token before first use.
    creds.refresh(Request())
    return _service_from_credentials(creds)


def get_user_send_context(user_id: str):
    """Return (service, sender_email, send_mode) for a user's connected Gmail.
    Raises NoGmailConnected if none is connected."""
    acct = repo.get_gmail_account(user_id)
    if not acct:
        raise NoGmailConnected(f"User {user_id} has not connected a Gmail account")
    service = get_gmail_service(user_id)
    return service, acct.get("email", ""), acct.get("send_mode", "draft")

# ---------------------------------------------------------------------------
# Email construction
# ---------------------------------------------------------------------------

def _compliance_footer() -> str:
    """CAN-SPAM baseline appended to every outgoing message body (v1 Task 14):
    a clear opt-out line and, when configured, a physical mailing address.

    The opt-out note is always included (a one-line, human "reply to opt out"
    is honest for 1:1 cold outreach). A physical address is appended only when
    COMPLIANCE_ADDRESS is set, since it's user/deployment-specific.
    """
    opt_out = os.getenv(
        "COMPLIANCE_UNSUBSCRIBE_NOTE",
        "P.S. Not the right time? Just reply and I won't follow up.",
    )
    address = os.getenv("COMPLIANCE_ADDRESS", "").strip()
    parts = ["\n\n--\n" + opt_out]
    if address:
        parts.append(address)
    return "\n".join(parts)


def build_email_message(
    to: str,
    subject: str,
    body: str,
    sender: str = "",
    attachment_path: str = "",
) -> str:
    """Construct a MIME email and return base64url-encoded raw message.

    If attachment_path points to an existing file (the tailored resume PDF),
    it's attached to the message. A compliance footer (opt-out + optional
    physical address) is appended to the body.
    """
    message = MIMEMultipart()
    message["to"] = to
    message["subject"] = subject
    if sender:
        message["from"] = sender

    msg_body = MIMEText(body + _compliance_footer(), "plain")
    message.attach(msg_body)

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(attachment_path),
        )
        message.attach(part)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return raw


def resume_pdf_path(lead: dict) -> str:
    """Resolve the tailored resume PDF path from a lead's resume_version."""
    version = (lead.get("resume_version") or "").strip()
    if not version:
        return ""
    # resume_version is the base filename (no extension)
    path = os.path.join(RESUMES_DIR, f"{version}.pdf")
    return path if os.path.exists(path) else ""

def extract_subject_and_body(outreach_draft: str, company: str, role: str) -> tuple[str, str]:
    """Parse the outreach draft into subject line and body.

    Convention: if the draft starts with 'Subject: ...' on the first line,
    that becomes the subject. Otherwise, generate a default subject.
    """
    lines = outreach_draft.strip().split("\n")

    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body = "\n".join(lines[1:]).strip()
    else:
        subject = f"{role} + your team at {company}" if role else f"Reaching out — {company}"
        body = outreach_draft.strip()

    return subject, body

# ---------------------------------------------------------------------------
# Core actions: create draft / send
# ---------------------------------------------------------------------------

def create_draft(service, to: str, subject: str, body: str, attachment_path: str = "", sender: str = "") -> dict:
    """Create a Gmail draft (optionally with a PDF attachment)."""
    raw_message = build_email_message(to, subject, body, sender or SENDER_EMAIL, attachment_path)
    draft_body = {"message": {"raw": raw_message}}

    draft = service.users().drafts().create(
        userId="me", body=draft_body
    ).execute()

    return draft

def send_email(service, to: str, subject: str, body: str, attachment_path: str = "", sender: str = "") -> dict:
    """Send an email directly (optionally with a PDF attachment)."""
    raw_message = build_email_message(to, subject, body, sender or SENDER_EMAIL, attachment_path)
    message_body = {"raw": raw_message}

    sent = service.users().messages().send(
        userId="me", body=message_body
    ).execute()

    return sent

# ---------------------------------------------------------------------------
# Main skill logic
# ---------------------------------------------------------------------------

def process_approved_lead(
    service, lead: dict, user_id: str, direct_send: bool, sender: str = "",
) -> str:
    """Process a single approved lead: create draft or send.

    direct_send: the per-user send preference (True = send now, False = draft).
    sender: the connected Gmail address to put in the From header.

    Returns one of: "sent", "draft_created", "skipped_no_email",
    "skipped_no_draft", "failed".
    """
    lead_id = lead.get("id")
    company = lead.get("company") or lead.get("x_handle") or "Unknown"
    role = lead.get("role") or ""
    contact_email = lead.get("contact_email") or ""
    outreach_draft = lead.get("outreach_draft") or ""

    if not contact_email:
        print(f"  ⚠️  Skipping {company} ({lead_id}) — no contact_email")
        return "skipped_no_email"

    if not outreach_draft:
        print(f"  ⚠️  Skipping {company} ({lead_id}) — no outreach_draft")
        return "skipped_no_draft"

    subject, body = extract_subject_and_body(outreach_draft, company, role)

    # Attach the tailored resume PDF if one exists for this lead
    attachment = resume_pdf_path(lead)
    if not attachment:
        print(f"  ⚠️  {company} ({lead_id}) — no tailored resume PDF found, sending without attachment")

    try:
        if direct_send:
            result = send_email(service, contact_email, subject, body, attachment, sender=sender)
            msg_id = result.get("id", "?")
            repo.update_lead(user_id, lead_id, {"status": "sent", "sent_at": _now_iso()})
            attach_note = " (+resume)" if attachment else ""
            print(f"  ✅ SENT to {contact_email} ({company}){attach_note} — msg_id: {msg_id}")
            return "sent"
        else:
            result = create_draft(service, contact_email, subject, body, attachment, sender=sender)
            draft_id = result.get("id", "?")
            repo.update_lead(user_id, lead_id, {"status": "draft_created", "sent_at": _now_iso()})
            attach_note = " (+resume)" if attachment else ""
            print(f"  📝 DRAFT created for {contact_email} ({company}){attach_note} — draft_id: {draft_id}")
            return "draft_created"

    except Exception as e:
        print(f"  ❌ Failed for {company} ({lead_id}): {e}")
        return "failed"

def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def run(user_id: str | None = None) -> dict:
    """Main entry point: process all of a user's approved leads.

    v1: when user_id is given (the HTTP path), send/draft from THAT user's
    connected Gmail using THEIR send preference. If the user hasn't connected
    Gmail, this is a soft no-op (summary["error"]="no_gmail_connected") -- the
    leads stay 'approved', not failed.

    When user_id is None (single-operator CLI), fall back to the shared token
    + the global GMAIL_DIRECT_SEND flag, unchanged.

    Returns a summary dict: {sent, draft_created, skipped_no_email,
    skipped_no_draft, failed, total, error}.
    """
    summary = {
        "sent": 0, "draft_created": 0, "skipped_no_email": 0,
        "skipped_no_draft": 0, "failed": 0, "skipped_quota": 0, "total": 0,
        "error": None,
    }

    sender = ""
    if user_id is None:
        # Legacy single-operator CLI path: shared token + global flag.
        target_user = get_current_user_id()
        direct_send = is_direct_send()
        sender = SENDER_EMAIL
        try:
            service = get_gmail_service()
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            summary["error"] = str(e)
            return summary
        except Exception as e:
            print(f"ERROR: Failed to authenticate with Gmail: {e}")
            summary["error"] = str(e)
            return summary
    else:
        # Per-user path: this user's own Gmail + their send preference.
        target_user = user_id
        try:
            service, sender, send_mode = get_user_send_context(user_id)
        except NoGmailConnected:
            print(f"  ⚠️  User {user_id} has no Gmail connected — leaving approved leads as-is.")
            summary["error"] = "no_gmail_connected"
            return summary
        except Exception as e:
            print(f"ERROR: Failed to build Gmail service for user {user_id}: {e}")
            summary["error"] = str(e)
            return summary
        direct_send = (send_mode == "direct")

    print("=" * 60)
    print("  GMAIL SKILL — Processing approved leads")
    print(f"  Mode: {'DIRECT SEND' if direct_send else 'DRAFTS ONLY'}"
          + (f"  Sender: {sender}" if sender else ""))
    print("=" * 60)

    # Which statuses to (re)process:
    #  - always 'approved' (newly approved, not yet actioned)
    #  - in DIRECT-SEND mode, also 'draft_created' — those are leads whose
    #    Gmail draft was created but never actually sent (e.g. draft deleted),
    #    so they should now go out as real emails. In drafts-only mode we skip
    #    them to avoid creating duplicate drafts.
    statuses = ["approved"]
    if direct_send:
        statuses.append("draft_created")

    all_leads = repo.get_leads(target_user)
    seen = set()
    leads = []
    for lead in all_leads:
        if str(lead.get("status", "")).strip() in statuses:
            lid = lead.get("id")
            if lid not in seen:
                seen.add(lid)
                leads.append(lead)

    summary["total"] = len(leads)

    if not leads:
        print(f"No leads to process (statuses: {', '.join(statuses)}).")
        return summary

    # --- Monthly outreach quota (backend-enforced) -----------------------
    # Compute the remaining allowance once, then decrement locally as we send
    # so we don't re-query per lead. Once exhausted, remaining leads are left
    # untouched and counted as skipped_quota (they stay 'approved' for next
    # cycle). Quota is not enforced on the legacy single-operator CLI path.
    remaining_quota: Optional[int] = None
    if user_id is not None:
        try:
            q = repo.get_outreach_quota(target_user)
            remaining_quota = int(q.get("remaining", 0))
            summary["quota_limit"] = int(q.get("limit", 0))
        except Exception as e:
            print(f"  ⚠️  Could not read outreach quota, proceeding without cap: {e}")
            remaining_quota = None

    for lead in leads:
        if remaining_quota is not None and remaining_quota <= 0:
            summary["skipped_quota"] = summary.get("skipped_quota", 0) + 1
            continue

        outcome = process_approved_lead(service, lead, target_user, direct_send, sender)
        summary[outcome] = summary.get(outcome, 0) + 1

        # Only successfully-actioned outreach consumes the allowance.
        if remaining_quota is not None and outcome in ("sent", "draft_created"):
            remaining_quota -= 1

    tail = ""
    if summary.get("skipped_quota"):
        tail = f", {summary['skipped_quota']} skipped (quota reached)"
    print(
        f"\nDone: {summary['sent']} sent, {summary['draft_created']} drafts, "
        f"{summary['skipped_no_email']} no-email, {summary['failed']} failed{tail}."
    )
    return summary

if __name__ == "__main__":
    run()
