"""Firebase Auth token verification (Phase 3.2).

Every protected route depends on `get_authenticated_user_id` (or, if it
needs the raw decoded token -- e.g. email for a welcome message --
`get_current_firebase_user` directly). There is no "soft" auth mode: a
missing, malformed, expired, or otherwise invalid token always raises a
401, never a silent fallback to db/current_user.py's single-user stand-in.

db/current_user.py is untouched by this module -- it keeps serving
non-HTTP call sites (CLI scripts, the scheduler) exactly as before. This
module is only for FastAPI route dependencies.

Firebase Admin SDK initialization is lazy (deferred to the first actual
token verification) rather than at import time, so importing this module
(e.g. transitively via api.main) never fails just because
FIREBASE_SERVICE_ACCOUNT_PATH isn't set yet in a dev/test environment
that never exercises a protected route.
"""

import os
import threading

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from google.auth import exceptions as google_auth_exceptions
from fastapi import Depends, HTTPException, Request

from db import repository as repo

_init_lock = threading.Lock()
_initialized = False


def _ensure_firebase_app() -> None:
    """Initialize the default firebase_admin App exactly once.

    Credential resolution order:
      1. FIREBASE_SERVICE_ACCOUNT_PATH (config/.env) -- a service account
         JSON key file, same pattern as config/gmail_credentials.json.
      2. Application Default Credentials -- e.g. Cloud Run's attached
         service account in deployed environments, or
         GOOGLE_APPLICATION_CREDENTIALS if set.
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        if firebase_admin._apps:
            # Some other code path (or a test) already initialized the
            # default app -- don't double-initialize.
            _initialized = True
            return

        cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("FIREBASE_PROJECT_ID") or "auto-job-apply-1859b"
        if cred_path:
            if not os.path.exists(cred_path):
                raise RuntimeError(
                    f"FIREBASE_SERVICE_ACCOUNT_PATH is set to '{cred_path}' but that "
                    "file doesn't exist. Fix the path in config/.env, or unset it to "
                    "fall back to Application Default Credentials."
                )
            firebase_admin.initialize_app(credentials.Certificate(cred_path), options={"projectId": project_id})
        else:
            firebase_admin.initialize_app(options={"projectId": project_id})

        _initialized = True



def get_current_firebase_user(request: Request) -> dict:
    """FastAPI dependency: verify the `Authorization: Bearer <id_token>`
    header via the Firebase Admin SDK.

    Returns the decoded token (a dict with at least "uid", and usually
    "email" for a Google Sign-In token). Raises 401 -- never 403, never a
    silent fallback -- for every failure mode: missing header, malformed
    header, empty token, expired token, revoked token, or garbage/invalid
    signature.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        _ensure_firebase_app()
        decoded = firebase_auth.verify_id_token(token)
    except HTTPException:
        raise
    except (
        google_auth_exceptions.DefaultCredentialsError,
        google_auth_exceptions.GoogleAuthError,
        # firebase_admin raises a plain ValueError("A project ID is
        # required...") when initialize_app() was called with no
        # credential/options and no project id is discoverable any other
        # way (GOOGLE_CLOUD_PROJECT env var, gcloud config, etc) -- this is
        # the exact case of "no FIREBASE_SERVICE_ACCOUNT_PATH set and no
        # ADC available", i.e. still a config problem, not a bad token.
        ValueError,
    ) as e:
        # This is a BACKEND CONFIGURATION problem (no service account
        # configured and no Application Default Credentials available on
        # this machine) -- not the same thing as "this visitor's token is
        # invalid". Collapsing it into a 401 hides a setup bug behind a
        # message that looks like a client auth failure. Surface it as a
        # distinct 500 so it's obvious this is a backend config issue (see
        # config/.env.example's FIREBASE_SERVICE_ACCOUNT_PATH), not
        # something the frontend/user did.
        raise HTTPException(
            status_code=500,
            detail=(
                "Firebase Admin SDK has no credentials configured on the backend. "
                "Set FIREBASE_SERVICE_ACCOUNT_PATH in config/.env to a Firebase "
                "service account JSON key (Firebase console > Project settings > "
                "Service accounts > Generate new private key), then restart the API. "
                f"({e})"
            ),
        )
    except Exception:
        # Covers firebase_admin.auth.InvalidIdTokenError, ExpiredIdTokenError,
        # RevokedIdTokenError, CertificateFetchError, and any other token
        # verification failure -- all collapse to the same clean 401, never
        # a raw 500.
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")

    return decoded


def get_authenticated_user_id(decoded_token: dict = Depends(get_current_firebase_user)) -> str:
    """FastAPI dependency: resolve a verified Firebase token into our
    Postgres user_id, creating the user row on first sign-in.

    This is the drop-in replacement for db.current_user.get_current_user_id()
    on every HTTP route -- same repo.get_or_create_user() call Phase 0
    already relies on, just fed a real per-request firebase_uid/email
    instead of the fixed local-operator identity.
    """
    uid = decoded_token.get("uid")
    email = decoded_token.get("email")
    if not uid or not email:
        raise HTTPException(status_code=401, detail="Token is missing required claims (uid/email)")

    user = repo.get_or_create_user(firebase_uid=uid, email=email)
    return user["id"]
