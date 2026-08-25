"""Single-user bootstrap -- stands in for Firebase Auth until Phase 3 lands.

Every db/repository.py function is user_id-scoped by design (that's the
whole point of the tenant-isolation work in Phase 0). But nothing upstream
of the repository layer can produce a user_id yet -- there's no login flow,
no auth middleware, no session. Until Phase 3 wires up Firebase Auth and a
real per-request user_id, every skill/orchestrator call site needs *some*
concrete user_id to pass in.

This module is that stand-in: it resolves (and lazily creates) exactly one
local "operator" user -- the person running this pipeline instance -- from
env config, and hands back their user_id. It deliberately does NOT try to
support multiple concurrent users; that's Phase 3's job. Its only purpose is
to let today's single-operator pipeline keep working against Postgres
instead of Google Sheets without inventing a fake multi-tenant story that
doesn't exist yet.

Config (config/.env):
    LOCAL_USER_FIREBASE_UID   -- stable identifier for this local user.
                                 Defaults to "local-single-user". Using a
                                 fixed default (rather than e.g. a random
                                 UUID generated per run) means restarting
                                 the process resolves to the SAME user row
                                 every time, via get_or_create_user's
                                 idempotent lookup -- not a new one.
    LOCAL_USER_EMAIL          -- defaults to GMAIL_SENDER_EMAIL if set
                                 (since that's already configured for the
                                 one real person this pipeline acts on
                                 behalf of), else "local@localhost".

Usage:
    from db.current_user import get_current_user_id
    user_id = get_current_user_id()
    repo.add_lead(user_id, {...})
"""

import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

LOCAL_USER_FIREBASE_UID = os.getenv("LOCAL_USER_FIREBASE_UID", "local-single-user")


def _default_email() -> str:
    return os.getenv("GMAIL_SENDER_EMAIL") or os.getenv("LOCAL_USER_EMAIL") or "local@localhost"


# Cached after first resolution so every call site isn't round-tripping to
# Postgres just to find out who "the current user" is. Only the id is
# cached (not plan/email/etc) since nothing here needs those to stay fresh.
_cached_user_id: str | None = None


def get_current_user_id() -> str:
    """Return the single local user's id, creating that user row on first call.

    Safe to call from any skill/orchestrator/API code as a drop-in for
    "whose data is this" until real auth exists. NOT safe to rely on for
    anything that needs actual multi-user isolation guarantees beyond what
    a single fixed user_id provides.
    """
    global _cached_user_id
    if _cached_user_id is not None:
        return _cached_user_id

    from db import repository as repo

    user = repo.get_or_create_user(
        firebase_uid=LOCAL_USER_FIREBASE_UID,
        email=_default_email(),
    )
    _cached_user_id = user["id"]
    return _cached_user_id


def reset_cache() -> None:
    """Clear the cached user_id. Used by tests that reset the schema between runs."""
    global _cached_user_id
    _cached_user_id = None
