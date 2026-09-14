"""GitHub and Vercel 1-click OAuth integration module.

Provides state signing, OAuth authorization URL construction, and authorization code
token exchange for GitHub and Vercel developer accounts.
"""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import uuid
from typing import Optional
import httpx
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

_STATE_TTL_SECONDS = 15 * 60  # 15 minutes


def _ensure_env():
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)


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
    b64_key = base64.urlsafe_b64encode(hashlib.sha256(fallback.encode()).digest())
    return Fernet(b64_key)


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Per RFC 7636 and Vercel Authorization Server API:
    - code_verifier: high-entropy cryptographic random string
    - code_challenge: BASE64URL-ENCODE(SHA256(ASCII(code_verifier))) without padding
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def sign_provider_state(user_id: str, provider: str, extra: Optional[dict] = None) -> str:
    """Sign an OAuth state payload carrying user_id, provider name, and optional metadata."""
    payload = {
        "user_id": user_id,
        "provider": provider,
        "nonce": uuid.uuid4().hex,
        "ts": int(time.time()),
    }
    if extra:
        payload.update(extra)
    return _get_fernet().encrypt(json.dumps(payload).encode()).decode()


def get_provider_state_payload(state: str, expected_provider: str) -> dict:
    """Decrypt and verify state token, returning full verified payload dictionary."""
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
    return data


def verify_provider_state(state: str, expected_provider: str) -> str:
    """Verify state token and return verified user_id."""
    return get_provider_state_payload(state, expected_provider)["user_id"]


# ---------------------------------------------------------------------------
# GitHub OAuth (Web Application Flow)
# ---------------------------------------------------------------------------

def get_github_auth_url(user_id: str) -> str:
    _ensure_env()
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
    _ensure_env()
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
# Vercel OAuth (Sign in with Vercel / Authorization Server API)
# ---------------------------------------------------------------------------

def get_vercel_auth_url(user_id: str) -> str:
    """Construct Vercel OAuth authorization URL with PKCE (S256).

    Per Vercel docs (https://vercel.com/docs/sign-in-with-vercel/authorization-server-api):
    - Required: client_id, redirect_uri, response_type=code, code_challenge, code_challenge_method=S256
    """
    _ensure_env()
    client_id = os.getenv("VERCEL_CLIENT_ID")
    if not client_id:
        raise ProviderOAuthConfigError("VERCEL_CLIENT_ID is not configured in environment.")

    redirect_uri = os.getenv(
        "VERCEL_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/vercel/callback"
    )
    code_verifier, code_challenge = generate_pkce()
    # Embed code_verifier securely inside the encrypted state parameter
    state = sign_provider_state(user_id, "vercel", extra={"code_verifier": code_verifier})
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": "openid email profile offline_access",
        "state": state,
    }
    return f"https://vercel.com/oauth/authorize?{urllib.parse.urlencode(params)}"


async def exchange_vercel_code(code: str, code_verifier: Optional[str] = None) -> str:
    """Exchange authorization code for Vercel access token using Token Endpoint."""
    _ensure_env()
    client_id = os.getenv("VERCEL_CLIENT_ID")
    client_secret = os.getenv("VERCEL_CLIENT_SECRET")
    redirect_uri = os.getenv(
        "VERCEL_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/auth/vercel/callback"
    )

    if not client_id or not client_secret:
        raise ProviderOAuthConfigError("Vercel OAuth credentials are not fully configured.")

    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Standard Vercel Authorization Server Token Endpoint
        res = await client.post(
            "https://api.vercel.com/login/oauth/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if res.status_code == 404:
            # Fallback for legacy app configurations
            res = await client.post(
                "https://api.vercel.com/v2/oauth/access_token",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        data = res.json()
        if "access_token" in data:
            return data["access_token"]
        error_msg = data.get("error_description") or data.get("error") or f"HTTP {res.status_code}: {res.text}"
        raise RuntimeError(f"Vercel OAuth failed: {error_msg}")
