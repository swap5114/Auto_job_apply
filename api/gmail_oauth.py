"""Per-user Gmail OAuth (web flow) + refresh-token encryption (v1, Task 5).

Each signed-in user connects their OWN Gmail via browser consent. We store
only an ENCRYPTED refresh token in Postgres (gmail_accounts table) -- never a
plaintext token, never the shared config/gmail_token.json desktop token the
pre-v1 single-operator flow used.

Flow:
  1. GET /api/gmail/connect (authenticated) -> build_consent_url(user_id,
     send_mode): returns a Google consent URL. The user's identity + chosen
     send preference are carried through OAuth's `state` param, SIGNED +
     ENCRYPTED (Fernet) so the unauthenticated callback can trust them.
  2. Google redirects the browser to GET /api/gmail/callback?code=...&state=...
     exchange_code_for_account(...) verifies the state, exchanges the code for
     a refresh token, reads the connected Gmail address from the id_token, and
     hands back everything the route needs to persist a gmail_accounts row.

Config (config/.env):
  GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET   Google OAuth *Web* client credentials
  GMAIL_OAUTH_REDIRECT_URI                e.g. http://localhost:8000/api/gmail/callback
  GMAIL_TOKEN_ENC_KEY                     a Fernet key (base64, 32 bytes) for
                                          encrypting refresh tokens + signing state
  FRONTEND_URL                            where the callback redirects the browser
                                          back to (e.g. http://localhost:3000)
"""

import json
import os
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken

# Restricted scopes: create drafts + send. openid/email let us read which
# Gmail address the user actually connected (stored for display + as sender).
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

# state tokens are short-lived: a consent round-trip is seconds, not hours.
_STATE_TTL_SECONDS = 15 * 60


class GmailOAuthConfigError(RuntimeError):
    """Raised when required Gmail OAuth env config is missing -- surfaced as a
    500 (backend misconfiguration), never a client-facing auth error."""


class GmailOAuthStateError(Exception):
    """Raised when the OAuth `state` param is missing, tampered, or expired."""


def _fernet() -> Fernet:
    key = os.getenv("GMAIL_TOKEN_ENC_KEY")
    if not key:
        raise GmailOAuthConfigError(
            "GMAIL_TOKEN_ENC_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and put it in config/.env."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:  # malformed key
        raise GmailOAuthConfigError(f"GMAIL_TOKEN_ENC_KEY is not a valid Fernet key: {e}")


# ---------------------------------------------------------------------------
# Refresh-token encryption
# ---------------------------------------------------------------------------

def encrypt_token(plaintext: str) -> str:
    """Encrypt a refresh token for at-rest storage. Returns a str token."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored refresh token. Raises InvalidToken if tampered or if
    the encryption key changed."""
    return _fernet().decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# OAuth `state` signing (carries user_id + send_mode through the redirect)
# ---------------------------------------------------------------------------

def sign_state(user_id: str, send_mode: str) -> str:
    payload = json.dumps({
        "user_id": user_id,
        "send_mode": send_mode,
        "nonce": uuid.uuid4().hex,
        "ts": int(time.time()),
    })
    return _fernet().encrypt(payload.encode()).decode()


def verify_state(state: str) -> dict:
    """Verify + decode a state token. Returns {user_id, send_mode}. Raises
    GmailOAuthStateError on any tamper/expiry/format problem."""
    if not state:
        raise GmailOAuthStateError("Missing OAuth state")
    try:
        raw = _fernet().decrypt(state.encode())
    except (InvalidToken, ValueError, TypeError):
        # InvalidToken = tampered/expired signature; ValueError/TypeError =
        # malformed (non-base64) input. All mean "don't trust this state".
        raise GmailOAuthStateError("OAuth state failed integrity check")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise GmailOAuthStateError("OAuth state is malformed")
    if int(time.time()) - int(data.get("ts", 0)) > _STATE_TTL_SECONDS:
        raise GmailOAuthStateError("OAuth state expired -- please reconnect")
    if not data.get("user_id"):
        raise GmailOAuthStateError("OAuth state missing user_id")
    return {"user_id": data["user_id"], "send_mode": data.get("send_mode", "draft")}


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

def _client_config() -> dict:
    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    redirect_uri = os.getenv("GMAIL_OAUTH_REDIRECT_URI")
    missing = [
        name for name, val in [
            ("GMAIL_CLIENT_ID", client_id),
            ("GMAIL_CLIENT_SECRET", client_secret),
            ("GMAIL_OAUTH_REDIRECT_URI", redirect_uri),
        ] if not val
    ]
    if missing:
        raise GmailOAuthConfigError(
            f"Missing Gmail OAuth config in config/.env: {', '.join(missing)}. "
            "Create an OAuth *Web application* client in Google Cloud Console, "
            "add the redirect URI, and set these values."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _build_flow():
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=os.getenv("GMAIL_OAUTH_REDIRECT_URI"),
    )


def build_consent_url(user_id: str, send_mode: str = "draft") -> str:
    """Build the Google consent URL for a user to connect their Gmail.

    access_type=offline + prompt=consent guarantees Google returns a refresh
    token (not just an access token), which is what we persist."""
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=sign_state(user_id, send_mode),
    )
    return auth_url


def exchange_code_for_account(code: str, state: str) -> dict:
    """Verify state, exchange the auth code for tokens, and read the connected
    Gmail address. Returns:
        {user_id, send_mode, email, refresh_token, scopes}
    Raises GmailOAuthStateError / GmailOAuthConfigError on failure."""
    verified = verify_state(state)

    flow = _build_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        # Without a refresh token we can't send later without re-consent.
        raise GmailOAuthConfigError(
            "Google did not return a refresh token. Ensure the consent screen "
            "used access_type=offline + prompt=consent."
        )

    email = _email_from_credentials(creds)

    return {
        "user_id": verified["user_id"],
        "send_mode": verified["send_mode"],
        "email": email,
        "refresh_token": creds.refresh_token,
        "scopes": list(creds.scopes or SCOPES),
    }


def _email_from_credentials(creds) -> str:
    """Read the connected account's email from the OAuth id_token."""
    import google.auth.transport.requests
    from google.oauth2 import id_token as google_id_token

    try:
        info = google_id_token.verify_oauth2_token(
            creds.id_token,
            google.auth.transport.requests.Request(),
            os.getenv("GMAIL_CLIENT_ID"),
        )
        email = info.get("email")
        if email:
            return email
    except Exception:
        pass
    # Fall back to the userinfo endpoint if the id_token wasn't usable.
    try:
        import requests

        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("email", "") or ""
    except Exception:
        pass
    return ""


def build_credentials_from_refresh_token(refresh_token: str):
    """Build a google.oauth2.credentials.Credentials from a stored refresh
    token, ready to call the Gmail API (used by the send path, Task 6)."""
    from google.oauth2.credentials import Credentials

    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise GmailOAuthConfigError(
            "GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET must be set to use a per-user "
            "Gmail refresh token."
        )
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
