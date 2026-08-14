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
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.db_client import get_leads, update_lead

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

def get_gmail_service():
    """Build and return the Gmail API service object."""
    from googleapiclient.discovery import build

    creds = get_gmail_credentials()
    service = build("gmail", "v1", credentials=creds)
    return service

# ---------------------------------------------------------------------------
# Email construction
# ---------------------------------------------------------------------------

def build_email_message(to: str, subject: str, body: str, sender: str = "") -> str:
    """Construct a MIME email and return base64url-encoded raw message."""
    message = MIMEMultipart()
    message["to"] = to
    message["subject"] = subject
    if sender:
        message["from"] = sender

    msg_body = MIMEText(body, "plain")
    message.attach(msg_body)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return raw

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
        subject = f"Re: {role} opportunity at {company}" if role else f"Reaching out — {company}"
        body = outreach_draft.strip()

    return subject, body

# ---------------------------------------------------------------------------
# Core actions: create draft / send
# ---------------------------------------------------------------------------

def create_draft(service, to: str, subject: str, body: str) -> dict:
    """Create a Gmail draft. Returns the draft resource."""
    raw_message = build_email_message(to, subject, body, SENDER_EMAIL)
    draft_body = {"message": {"raw": raw_message}}

    draft = service.users().drafts().create(
        userId="me", body=draft_body
    ).execute()

    return draft

def send_email(service, to: str, subject: str, body: str) -> dict:
    """Send an email directly. Returns the message resource."""
    raw_message = build_email_message(to, subject, body, SENDER_EMAIL)
    message_body = {"raw": raw_message}

    sent = service.users().messages().send(
        userId="me", body=message_body
    ).execute()

    return sent

# ---------------------------------------------------------------------------
# Main skill logic
# ---------------------------------------------------------------------------

def process_approved_lead(service, lead: dict) -> bool:
    """Process a single approved lead: create draft or send.

    Returns True if successful, False otherwise.
    """
    lead_id = lead.get("id")
    company = lead.get("company") or lead.get("x_handle") or "Unknown"
    role = lead.get("role") or ""
    contact_email = lead.get("contact_email") or ""
    outreach_draft = lead.get("outreach_draft") or ""

    if not contact_email:
        print(f"  ⚠️  Skipping {company} ({lead_id}) — no contact_email")
        return False

    if not outreach_draft:
        print(f"  ⚠️  Skipping {company} ({lead_id}) — no outreach_draft")
        return False

    subject, body = extract_subject_and_body(outreach_draft, company, role)

    try:
        if GMAIL_DIRECT_SEND:
            result = send_email(service, contact_email, subject, body)
            msg_id = result.get("id", "?")
            update_lead(lead_id, {"status": "sent", "sent_at": _now_iso()})
            print(f"  ✅ SENT to {contact_email} ({company}) — msg_id: {msg_id}")
        else:
            result = create_draft(service, contact_email, subject, body)
            draft_id = result.get("id", "?")
            update_lead(lead_id, {"status": "draft_created"})
            print(f"  📝 DRAFT created for {contact_email} ({company}) — draft_id: {draft_id}")

        return True

    except Exception as e:
        print(f"  ❌ Failed for {company} ({lead_id}): {e}")
        return False

def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def run():
    """Main entry point: process all approved leads."""
    print("=" * 60)
    print("  GMAIL SKILL — Processing approved leads")
    print(f"  Mode: {'DIRECT SEND' if GMAIL_DIRECT_SEND else 'DRAFTS ONLY'}")
    print("=" * 60)
    print()

    try:
        service = get_gmail_service()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return
    except Exception as e:
        print(f"ERROR: Failed to authenticate with Gmail: {e}")
        return

    # Get leads that have been approved (via review CLI) and not yet sent/drafted
    leads = get_leads(status="approved")

    if not leads:
        print("No approved leads to process.")
        return

    success_count = 0
    fail_count = 0

    for lead in leads:
        if process_approved_lead(service, lead):
            success_count += 1
        else:
            fail_count += 1

    print(f"\nDone: {success_count} processed, {fail_count} skipped/failed.")

if __name__ == "__main__":
    run()
