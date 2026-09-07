"""Unit tests for GitHub and Vercel 1-click OAuth integration."""

import os
import pytest
from api.provider_oauth import (
    sign_provider_state,
    verify_provider_state,
    get_github_auth_url,
    get_vercel_auth_url,
    ProviderOAuthStateError,
    ProviderOAuthConfigError,
)


def test_provider_state_signing_and_verification():
    user_id = "test-user-uuid-1234"
    state = sign_provider_state(user_id, "github")
    assert state is not None

    verified_user_id = verify_provider_state(state, expected_provider="github")
    assert verified_user_id == user_id


def test_provider_state_mismatch_raises_error():
    user_id = "test-user-uuid-1234"
    state = sign_provider_state(user_id, "github")

    with pytest.raises(ProviderOAuthStateError) as exc_info:
        verify_provider_state(state, expected_provider="vercel")
    assert "mismatch" in str(exc_info.value)


def test_github_auth_url_construction(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh_client_123")
    url = get_github_auth_url("user-abc")

    assert "https://github.com/login/oauth/authorize" in url
    assert "client_id=gh_client_123" in url
    assert "scope=repo+workflow" in url or "scope=repo%20workflow" in url
    assert "state=" in url


def test_vercel_auth_url_construction(monkeypatch):
    monkeypatch.setenv("VERCEL_CLIENT_ID", "vc_client_456")
    url = get_vercel_auth_url("user-xyz")

    assert "https://vercel.com/oauth/authorize" in url
    assert "client_id=vc_client_456" in url
    assert "state=" in url


def test_missing_client_id_raises_config_error(monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    with pytest.raises(ProviderOAuthConfigError):
        get_github_auth_url("user-123")
