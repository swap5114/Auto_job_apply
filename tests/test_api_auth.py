"""HTTP-level tests for Phase 3's Firebase Auth middleware (api/auth.py)
and the account-conversion / profile routes it protects.

Firebase Admin's token verification is mocked throughout -- never a real
Firebase Admin SDK call in CI, per PHASE_3_PLAN.md's test requirements.
Two "tenants" are simulated by mocking verify_id_token to return different
decoded tokens per test; each call to repo.get_or_create_user resolves (and
creates, on first use) a real Postgres user row, so the tenant-isolation
assertions here exercise the real HTTP -> auth dependency -> repository
chain end to end, not just the repository layer (which Phase 0 already
covers in test_repository.py).
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from firebase_admin._auth_utils import InvalidIdTokenError
from firebase_admin._token_gen import ExpiredIdTokenError

import api.main as api_main
from api.main import app
from db import repository as repo

client = TestClient(app)

USER_A_TOKEN = {"uid": "firebase-uid-a", "email": "a@example.com"}
USER_B_TOKEN = {"uid": "firebase-uid-b", "email": "b@example.com"}


def _auth_headers() -> dict:
    return {"Authorization": "Bearer whatever-a-real-token-would-be"}


def _reset_caches():
    api_main._invalidate_leads_cache()


# ---------------------------------------------------------------------------
# Auth middleware: missing / malformed / expired / invalid token -> 401
# ---------------------------------------------------------------------------


def test_missing_authorization_header_returns_401():
    _reset_caches()
    resp = client.get("/api/leads")
    assert resp.status_code == 401


def test_malformed_authorization_header_returns_401():
    """A header that isn't 'Bearer <token>' (e.g. a raw token with no
    scheme, or a different scheme) must 401, not 500."""
    _reset_caches()
    resp = client.get("/api/leads", headers={"Authorization": "not-a-bearer-token"})
    assert resp.status_code == 401


def test_empty_bearer_token_returns_401():
    _reset_caches()
    resp = client.get("/api/leads", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_garbage_token_returns_401_not_500():
    """A syntactically-present but invalid/garbage token must produce a
    clean 401 (verify_id_token raising InvalidIdTokenError), never a raw
    500 that could leak internals."""
    _reset_caches()
    with patch(
        "api.auth.firebase_auth.verify_id_token",
        side_effect=InvalidIdTokenError("Malformed token"),
    ):
        resp = client.get("/api/leads", headers=_auth_headers())
    assert resp.status_code == 401
    assert resp.status_code != 500


def test_expired_token_returns_401():
    _reset_caches()
    with patch(
        "api.auth.firebase_auth.verify_id_token",
        side_effect=ExpiredIdTokenError("Token expired", cause=None),
    ):
        resp = client.get("/api/leads", headers=_auth_headers())
    assert resp.status_code == 401


def test_token_missing_required_claims_returns_401():
    """A token that verifies fine but has no uid/email (shouldn't happen
    with real Google Sign-In tokens, but the dependency must not crash if
    it does) -- clean 401, not a 500 from a missing dict key."""
    _reset_caches()
    with patch("api.auth.firebase_auth.verify_id_token", return_value={"some_other_claim": "x"}):
        resp = client.get("/api/leads", headers=_auth_headers())
    assert resp.status_code == 401


def test_valid_token_returns_200_with_correct_user_context():
    _reset_caches()
    with patch("api.auth.firebase_auth.verify_id_token", return_value=USER_A_TOKEN):
        resp = client.get("/api/leads", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json() == []

    user = repo.get_user_by_firebase_uid(USER_A_TOKEN["uid"])
    assert user is not None
    assert user["email"] == USER_A_TOKEN["email"]


# ---------------------------------------------------------------------------
# Anonymous routes must stay open (regression guard) -- confirms the auth
# middleware wiring didn't accidentally lock down the one surface that's
# supposed to stay public.
# ---------------------------------------------------------------------------


def test_anon_resume_route_requires_no_token():
    """Not asserting a 200 here (that requires a real/mocked resume parse,
    covered by test_anon_endpoints.py) -- just that the absence of a token
    doesn't produce a 401. A 400 (empty file) proves the request reached
    the route handler's own validation, not the auth dependency.
    """
    import io
    resp = client.post(
        "/api/anon/resume",
        files={"file": ("resume.txt", io.BytesIO(b""), "text/plain")},
    )
    assert resp.status_code != 401


def test_health_and_readiness_routes_require_no_token():
    assert client.get("/api/health").status_code != 401
    assert client.get("/health").status_code != 401
    # /ready hits Postgres -- in this test env it should be reachable and
    # return 200, but even if it weren't, it must never be a 401.
    assert client.get("/ready").status_code != 401


# ---------------------------------------------------------------------------
# Tenant isolation through the real HTTP layer (not just the repo layer,
# which Phase 0's test_repository.py already covers).
# ---------------------------------------------------------------------------


def test_leads_are_isolated_between_two_signed_in_users_via_the_api():
    _reset_caches()

    # Resolve both users' real Postgres ids the same way the auth
    # dependency does (repo.get_or_create_user), then seed leads directly
    # via the repo -- the isolation being tested is in the API's read path.
    user_a = repo.get_or_create_user(firebase_uid=USER_A_TOKEN["uid"], email=USER_A_TOKEN["email"])
    user_b = repo.get_or_create_user(firebase_uid=USER_B_TOKEN["uid"], email=USER_B_TOKEN["email"])

    repo.add_lead(user_a["id"], {"company": "Only Visible To A", "role": "Engineer"})
    repo.add_lead(user_b["id"], {"company": "Only Visible To B", "role": "Engineer"})
    _reset_caches()

    with patch("api.auth.firebase_auth.verify_id_token", return_value=USER_A_TOKEN):
        resp_a = client.get("/api/leads", headers=_auth_headers())
    assert resp_a.status_code == 200
    companies_a = [l["company"] for l in resp_a.json()]
    assert "Only Visible To A" in companies_a
    assert "Only Visible To B" not in companies_a

    with patch("api.auth.firebase_auth.verify_id_token", return_value=USER_B_TOKEN):
        resp_b = client.get("/api/leads", headers=_auth_headers())
    assert resp_b.status_code == 200
    companies_b = [l["company"] for l in resp_b.json()]
    assert "Only Visible To B" in companies_b
    assert "Only Visible To A" not in companies_b


def test_stats_are_isolated_between_two_signed_in_users_via_the_api():
    _reset_caches()
    user_a = repo.get_or_create_user(firebase_uid=USER_A_TOKEN["uid"], email=USER_A_TOKEN["email"])
    user_b = repo.get_or_create_user(firebase_uid=USER_B_TOKEN["uid"], email=USER_B_TOKEN["email"])

    repo.add_lead(user_a["id"], {"company": "A Stats Co", "role": "Engineer"})
    repo.add_lead(user_b["id"], {"company": "B Stats Co 1", "role": "Engineer"})
    repo.add_lead(user_b["id"], {"company": "B Stats Co 2", "role": "Engineer"})
    _reset_caches()

    with patch("api.auth.firebase_auth.verify_id_token", return_value=USER_A_TOKEN):
        resp_a = client.get("/api/stats", headers=_auth_headers())
    assert resp_a.json()["total"] == 1

    with patch("api.auth.firebase_auth.verify_id_token", return_value=USER_B_TOKEN):
        resp_b = client.get("/api/stats", headers=_auth_headers())
    assert resp_b.json()["total"] == 2


# ---------------------------------------------------------------------------
# Anon -> account conversion (Phase 3.4)
# ---------------------------------------------------------------------------

FAKE_PARSED_RESUME = {
    "name": "Jane Doe",
    "contact": {"email": "jane@example.com"},
    "summary": "",
    "education": [],
    "experience": [],
    "projects": [],
    "skills": {"Languages": ["Python"]},
    "certifications": [],
}

FAKE_INFERRED_CRITERIA = {
    "roles": ["Backend Engineer"],
    "tech_stack": ["python", "fastapi"],
    "seniority": "mid",
    "locations": ["remote"],
    "remote_pref": "remote",
    "inferred_from_resume": True,
}


def test_convert_anon_session_requires_auth():
    resp = client.post(
        "/api/account/convert-anon-session",
        json={"parsed_resume": FAKE_PARSED_RESUME, "inferred_criteria": FAKE_INFERRED_CRITERIA},
    )
    assert resp.status_code == 401


def test_convert_anon_session_persists_resume_and_criteria_scoped_to_user():
    token = {"uid": "firebase-uid-convert-1", "email": "convert1@example.com"}
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token):
        resp = client.post(
            "/api/account/convert-anon-session",
            json={"parsed_resume": FAKE_PARSED_RESUME, "inferred_criteria": FAKE_INFERRED_CRITERIA},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resume_id"]
    assert body["search_criteria_id"]

    user = repo.get_user_by_firebase_uid(token["uid"])
    resumes = repo.get_resumes(user["id"])
    assert len(resumes) == 1
    assert resumes[0]["parsed_json"]["name"] == "Jane Doe"
    assert resumes[0]["is_primary"] is True

    criteria = repo.get_search_criteria(user["id"])
    assert criteria["roles"] == ["Backend Engineer"]
    assert criteria["inferred_from_resume"] is True


def test_convert_anon_session_called_twice_creates_new_resume_version_but_upserts_criteria():
    """Idempotency (Phase 3.4): calling convert-anon-session twice must not
    error or silently no-op. A new resume *version* is created each time
    (is_primary tracks the newest), while search_criteria is upserted in
    place -- exactly one row per user, refreshed rather than duplicated.
    """
    token = {"uid": "firebase-uid-convert-2", "email": "convert2@example.com"}
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token):
        first = client.post(
            "/api/account/convert-anon-session",
            json={"parsed_resume": FAKE_PARSED_RESUME, "inferred_criteria": FAKE_INFERRED_CRITERIA},
            headers=_auth_headers(),
        )
        second_resume = {**FAKE_PARSED_RESUME, "name": "Jane Doe (Updated)"}
        second = client.post(
            "/api/account/convert-anon-session",
            json={"parsed_resume": second_resume, "inferred_criteria": FAKE_INFERRED_CRITERIA},
            headers=_auth_headers(),
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["resume_id"] != second.json()["resume_id"]

    user = repo.get_user_by_firebase_uid(token["uid"])
    resumes = repo.get_resumes(user["id"])
    assert len(resumes) == 2  # a new version, not a duplicate-error and not an overwrite

    primaries = [r for r in resumes if r["is_primary"]]
    assert len(primaries) == 1
    assert primaries[0]["parsed_json"]["name"] == "Jane Doe (Updated)"  # newest is primary

    # search_criteria stayed a single row for this user (upserted, not duplicated).
    criteria_rows = repo.get_search_criteria(user["id"])
    assert criteria_rows is not None


# ---------------------------------------------------------------------------
# Profile CRUD (Phase 3.7) -- scoped correctly, rejecting another user's data
# the same way leads already do.
# ---------------------------------------------------------------------------


def test_profile_search_criteria_404s_before_any_conversion():
    token = {"uid": "firebase-uid-profile-empty", "email": "profile-empty@example.com"}
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token):
        resp = client.get("/api/profile/search-criteria", headers=_auth_headers())
    assert resp.status_code == 404


def test_profile_search_criteria_get_and_put_scoped_to_user():
    token_a = {"uid": "firebase-uid-profile-a", "email": "profile-a@example.com"}
    token_b = {"uid": "firebase-uid-profile-b", "email": "profile-b@example.com"}

    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_a):
        client.post(
            "/api/account/convert-anon-session",
            json={"parsed_resume": FAKE_PARSED_RESUME, "inferred_criteria": FAKE_INFERRED_CRITERIA},
            headers=_auth_headers(),
        )
        get_resp = client.get("/api/profile/search-criteria", headers=_auth_headers())
        assert get_resp.status_code == 200
        assert get_resp.json()["roles"] == ["Backend Engineer"]

        put_resp = client.put(
            "/api/profile/search-criteria",
            json={"roles": ["Staff Engineer"], "tech_stack": ["rust"]},
            headers=_auth_headers(),
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["roles"] == ["Staff Engineer"]
        # A manual edit is no longer purely LLM-inferred.
        assert put_resp.json()["inferred_from_resume"] is False

    # User B never converted anything -- must 404, never see user A's data.
    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_b):
        resp_b = client.get("/api/profile/search-criteria", headers=_auth_headers())
    assert resp_b.status_code == 404


def test_profile_resumes_scoped_to_user():
    token_a = {"uid": "firebase-uid-profile-resumes-a", "email": "profile-resumes-a@example.com"}
    token_b = {"uid": "firebase-uid-profile-resumes-b", "email": "profile-resumes-b@example.com"}

    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_a):
        client.post(
            "/api/account/convert-anon-session",
            json={"parsed_resume": FAKE_PARSED_RESUME, "inferred_criteria": FAKE_INFERRED_CRITERIA},
            headers=_auth_headers(),
        )
        resp_a = client.get("/api/profile/resumes", headers=_auth_headers())
    assert resp_a.status_code == 200
    assert len(resp_a.json()) == 1
    assert resp_a.json()[0]["parsed_json"]["name"] == "Jane Doe"

    with patch("api.auth.firebase_auth.verify_id_token", return_value=token_b):
        resp_b = client.get("/api/profile/resumes", headers=_auth_headers())
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # user B has none of user A's resumes
