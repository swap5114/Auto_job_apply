"""v1 Task 5: per-user Gmail OAuth -- token encryption, signed state, repo
helpers (tenant isolation), and the connect/status/send-mode/disconnect routes
(Google mocked). No real Google calls.
"""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient

# A stable Fernet key for the whole test module (encryption + state signing).
os.environ.setdefault("GMAIL_TOKEN_ENC_KEY", Fernet.generate_key().decode())
os.environ.setdefault("GMAIL_CLIENT_ID", "test-client-id")
os.environ.setdefault("GMAIL_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/api/gmail/callback")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

from db import repository as repo  # noqa: E402
import api.main as api_main  # noqa: E402
from api import gmail_oauth  # noqa: E402

# A Bearer header must be present for get_current_firebase_user to reach the
# (mocked) token verification instead of short-circuiting to 401.
client = TestClient(api_main.app, headers={"Authorization": "Bearer test-token"})

_TEST_UID = "gmail-oauth-user"
_TEST_EMAIL = "gmailuser@example.com"


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(
        "api.auth.firebase_auth.verify_id_token",
        lambda token: {"uid": _TEST_UID, "email": _TEST_EMAIL},
    )
    yield


def _user_id() -> str:
    return repo.get_or_create_user(firebase_uid=_TEST_UID, email=_TEST_EMAIL)["id"]


# ---------------------------------------------------------------------------
# Encryption + state signing
# ---------------------------------------------------------------------------


def test_token_encrypt_decrypt_roundtrip():
    ciphertext = gmail_oauth.encrypt_token("1//refresh-token-abc")
    assert ciphertext != "1//refresh-token-abc"  # actually encrypted
    assert gmail_oauth.decrypt_token(ciphertext) == "1//refresh-token-abc"


def test_state_sign_verify_roundtrip_and_tamper():
    state = gmail_oauth.sign_state("user-123", "direct")
    decoded = gmail_oauth.verify_state(state)
    assert decoded == {"user_id": "user-123", "send_mode": "direct", "code_verifier": ""}

    # Corrupt a character in the middle -> HMAC check fails.
    i = len(state) // 2
    tampered = state[:i] + ("A" if state[i] != "A" else "B") + state[i + 1:]
    with pytest.raises(gmail_oauth.GmailOAuthStateError):
        gmail_oauth.verify_state(tampered)


# ---------------------------------------------------------------------------
# Repository helpers + tenant isolation
# ---------------------------------------------------------------------------


def test_gmail_account_upsert_get_update_delete():
    user = repo.create_user(firebase_uid="gm-1", email="gm1@example.com")
    acct = repo.upsert_gmail_account(
        user["id"], "gm1@gmail.com", "enc-token", scopes=["a"], send_mode="draft"
    )
    assert acct["email"] == "gm1@gmail.com"
    assert acct["send_mode"] == "draft"

    fetched = repo.get_gmail_account(user["id"])
    assert fetched["encrypted_refresh_token"] == "enc-token"

    # Reconnect updates in place (still one row).
    repo.upsert_gmail_account(user["id"], "gm1b@gmail.com", "enc-token-2", send_mode="direct")
    again = repo.get_gmail_account(user["id"])
    assert again["email"] == "gm1b@gmail.com"
    assert again["send_mode"] == "direct"

    repo.update_gmail_send_mode(user["id"], "draft")
    assert repo.get_gmail_account(user["id"])["send_mode"] == "draft"

    assert repo.delete_gmail_account(user["id"]) is True
    assert repo.get_gmail_account(user["id"]) is None


def test_gmail_account_is_tenant_isolated():
    a = repo.create_user(firebase_uid="gm-a", email="gma@example.com")
    b = repo.create_user(firebase_uid="gm-b", email="gmb@example.com")
    repo.upsert_gmail_account(a["id"], "a@gmail.com", "enc-a")
    # User B has no account even though A does.
    assert repo.get_gmail_account(b["id"]) is None


def test_upsert_rejects_bad_send_mode():
    user = repo.create_user(firebase_uid="gm-bad", email="gmbad@example.com")
    with pytest.raises(repo.ValidationError):
        repo.upsert_gmail_account(user["id"], "x@gmail.com", "enc", send_mode="whenever")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_status_reports_not_connected_then_connected():
    uid = _user_id()
    repo.delete_gmail_account(uid)

    resp = client.get("/api/gmail/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False

    repo.upsert_gmail_account(uid, "me@gmail.com", "enc", send_mode="direct")
    resp = client.get("/api/gmail/status")
    body = resp.json()
    assert body["connected"] is True
    assert body["email"] == "me@gmail.com"
    assert body["send_mode"] == "direct"


def test_connect_returns_google_consent_url():
    resp = client.get("/api/gmail/connect?send_mode=direct")
    assert resp.status_code == 200
    auth_url = resp.json()["auth_url"]
    assert auth_url.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "state=" in auth_url


def test_callback_persists_encrypted_token_and_redirects(monkeypatch):
    uid = _user_id()
    repo.delete_gmail_account(uid)

    # Sign a real state for this user, then mock the code->account exchange.
    state = gmail_oauth.sign_state(uid, "direct")

    def fake_exchange(code, state_arg):
        assert code == "the-code"
        verified = gmail_oauth.verify_state(state_arg)
        return {
            "user_id": verified["user_id"],
            "send_mode": verified["send_mode"],
            "email": "connected@gmail.com",
            "refresh_token": "1//real-refresh",
            "scopes": gmail_oauth.SCOPES,
        }

    monkeypatch.setattr(gmail_oauth, "exchange_code_for_account", fake_exchange)

    resp = client.get(
        f"/api/gmail/callback?code=the-code&state={state}", follow_redirects=False
    )
    assert resp.status_code in (302, 307)
    assert "gmail=connected" in resp.headers["location"]

    acct = repo.get_gmail_account(uid)
    assert acct is not None
    assert acct["email"] == "connected@gmail.com"
    # Stored token is encrypted, and decrypts back to the original.
    assert acct["encrypted_refresh_token"] != "1//real-refresh"
    assert gmail_oauth.decrypt_token(acct["encrypted_refresh_token"]) == "1//real-refresh"
    assert acct["send_mode"] == "direct"


def test_callback_with_bad_state_redirects_to_error(monkeypatch):
    resp = client.get(
        "/api/gmail/callback?code=x&state=garbage", follow_redirects=False
    )
    assert resp.status_code in (302, 307)
    assert "gmail=state_error" in resp.headers["location"]


def test_send_mode_update_and_disconnect():
    uid = _user_id()
    repo.upsert_gmail_account(uid, "me@gmail.com", "enc", send_mode="draft")

    resp = client.put("/api/gmail/send-mode", json={"send_mode": "direct"})
    assert resp.status_code == 200
    assert resp.json()["send_mode"] == "direct"

    resp = client.post("/api/gmail/disconnect")
    assert resp.json()["status"] == "disconnected"
    assert repo.get_gmail_account(uid) is None
