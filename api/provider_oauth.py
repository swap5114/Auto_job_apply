"""GitHub and Vercel 1-click OAuth integration module.

Provides state signing, OAuth authorization URL construction, and authorization code
token exchange for GitHub and Vercel developer accounts.
"""

import json
import os
import time
import urllib.parse
import uuid
import httpx
from cryptography.fernet import Fernet, InvalidToken

_STATE_TTL_SECONDS = 15 * 60  # 15 minutes


class ProviderOAuthConfigError(RuntimeError):
    """Raised when required provider OAuth config (Client ID/Secret) is missing."""


class ProviderOAuthStateError(Exception):
    """Raised when OAuth state verification fails."""


def _get_fernet() -> Fernet:
    key = os.getenv("GMAIL_TOKEN_ENC_KEY")
    if key:
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            pass
    # Deterministic fallback key derived from secret if GMAIL_TOKEN_ENC_KEY not explicitly set
    fallback = os.getenv("SECRET_KEY", "auto-job-apply-default-secret-key-32b!")
    import base64
    import hashlib
    b64_key = base64.urlsafe_b64encode(hashlib.sha256(fallback.encode()).digest())
    return Fernet(b64_key)


def sign_provider_state(user_id: str, provider: str) -> str:
    """Sign an OAuth state payload carrying user_id and provider name."""
    payload = json.dumps({
        "user_id": user_id,
        "provider": provider,
        "nonce": uuid.uuid4().hex,
        "ts": int(time.time()),
    })
    return _get_fernet().encrypt(payload.encode()).decode()


def verify_provider_state(state: str, expected_provider: str) -> str:
    """Verify state token and return verified user_id."""
    if not state:
        raise ProviderOAuthStateError("Missing OAuth state parameter")
    try:
        raw = _get_fernet().decrypt(state.encode())
        data = json.loads(raw.decode())
    except Exception:
        raise ProviderOAuthStateError("OAuth state failed integrity check")

    if data.get("provider") != expected_provider:
        raise ProviderOAuthStateError(f"OAuth state provider mismatch (expected {expected_provider})")

    if time.time() - data.get("ts", 0) > _STATE_TTL_SECONDS:
        raise ProviderOAuthStateError("OAuth state expired")

    user_id = data.get("user_id")
    if not user_id:
        raise ProviderOAuthStateError("Invalid state payload: missing user_id")
    return user_id


# ---------------------------------------------------------------------------
# GitHub OAuth
# ---------------------------------------------------------------------------

def get_github_auth_url(user_id: str) -> str:
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise ProviderOAuthConfigError("GITHUB_CLIENT_ID is not configured in environment.")

    redirect_uri = os.getenv(
        "GITHUB_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/github/callback"
    )
    state = sign_provider_state(user_id, "github")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "repo workflow",
        "state": state,
    }
    return f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"


async def exchange_github_code(code: str) -> str:
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    redirect_uri = os.getenv(
        "GITHUB_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/github/callback"
    )

    if not client_id or not client_secret:
        raise ProviderOAuthConfigError("GitHub OAuth credentials are not fully configured.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        data = res.json()
        if "access_token" in data:
            return data["access_token"]
        error_msg = data.get("error_description") or data.get("error") or "Unknown error exchanging GitHub authorization code."
        raise RuntimeError(f"GitHub OAuth failed: {error_msg}")


# ---------------------------------------------------------------------------
# Vercel OAuth
# ---------------------------------------------------------------------------

def get_vercel_auth_url(user_id: str) -> str:
    client_id = os.getenv("VERCEL_CLIENT_ID")
    if not client_id:
        raise ProviderOAuthConfigError("VERCEL_CLIENT_ID is not configured in environment.")

    redirect_uri = os.getenv(
        "VERCEL_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/vercel/callback"
    )
    state = sign_provider_state(user_id, "vercel")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"https://vercel.com/oauth/authorize?{urllib.parse.urlencode(params)}"


async def exchange_vercel_code(code: str) -> str:
    client_id = os.getenv("VERCEL_CLIENT_ID")
    client_secret = os.getenv("VERCEL_CLIENT_SECRET")
    redirect_uri = os.getenv(
        "VERCEL_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/vercel/callback"
    )

    if not client_id or not client_secret:
        raise ProviderOAuthConfigError("Vercel OAuth credentials are not fully configured.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            "https://api.vercel.com/v2/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = res.json()
        if "access_token" in data:
            return data["access_token"]
        error_msg = data.get("error_description") or data.get("error") or "Unknown error exchanging Vercel authorization code."
        raise RuntimeError(f"Vercel OAuth failed: {error_msg}")
