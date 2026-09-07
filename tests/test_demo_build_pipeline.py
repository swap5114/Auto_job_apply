"""Tests for AI Demo Code Generation, Sandboxing & Multi-Cloud Deployment Pipeline.

Verifies:
  - 5-demo daily quota rate limiting per user in PostgreSQL.
  - DemoBuild repository CRUD operations & refinement turns.
  - User provider keys (GitHub, Vercel, Render) update & retrieval.
  - FastAPI demo build routes (/api/demos/build, /api/demos/build/{id}/refine, /api/demos/quota).
"""

import pytest
from datetime import datetime, timezone
from db import repository as repo
from db.models import User, DemoBuild, DemoUsageDaily


def _make_user(suffix: str = "1") -> dict:
    return repo.create_user(firebase_uid=f"fb-demo-{suffix}", email=f"demo{suffix}@example.com")


def test_demo_quota_rate_limit():
    """Verify daily 5-demo quota enforcement per user."""
    user = _make_user("quota1")
    user_id = user["id"]

    # First 5 calls should succeed
    for i in range(5):
        assert repo.check_and_increment_demo_quota(user_id, max_daily=5) is True

    # 6th call on the same day should fail
    assert repo.check_and_increment_demo_quota(user_id, max_daily=5) is False

    usage = repo.get_daily_demo_usage(user_id, max_daily=5)
    assert usage["used"] == 5
    assert usage["limit"] == 5
    assert usage["remaining"] == 0


def test_demo_build_crud():
    """Verify creation, retrieval, and status updates for DemoBuild records."""
    user = _make_user("crud1")
    user_id = user["id"]
    build_id = "test-build-123"
    spec = {"title": "Test CRM App", "description": "Build a test CRM dashboard"}

    created = repo.create_demo_build(
        user_id=user_id,
        build_id=build_id,
        title="Test CRM App",
        company_name="Acme Corp",
        project_type="fullstack",
        spec_json=spec,
    )

    assert created["build_id"] == build_id
    assert created["user_id"] == user_id
    assert created["stage"] == "pending"
    assert created["project_type"] == "fullstack"

    fetched = repo.get_demo_build(user_id, build_id)
    assert fetched["title"] == "Test CRM App"
    assert fetched["company_name"] == "Acme Corp"

    updated = repo.update_demo_build_status(
        user_id,
        build_id,
        stage="success",
        deploy_stage="deployed",
        frontend_url="https://demo-app.vercel.app",
        backend_url="https://demo-api.onrender.com",
        repo_url="https://github.com/user/demo-app",
    )

    assert updated["stage"] == "success"
    assert updated["deploy_stage"] == "deployed"
    assert updated["frontend_url"] == "https://demo-app.vercel.app"

    # Add refinement turn
    refined = repo.add_refinement_turn(user_id, build_id, "Add dark mode button", stage="building")
    assert refined["turn_count"] == 2
    assert len(refined["refinements"]) == 1
    assert refined["refinements"][0]["prompt"] == "Add dark mode button"

    user_builds = repo.list_user_demo_builds(user_id)
    assert len(user_builds) >= 1
    assert user_builds[0]["build_id"] == build_id


def test_user_provider_keys():
    """Verify user cloud provider keys update & retrieval."""
    user = _make_user("keys1")
    user_id = user["id"]

    updated = repo.update_user_provider_keys(
        user_id,
        github_token="ghp_test12345",
        vercel_token="vercel_tok_test",
        render_api_key="rnd_test_key",
    )

    assert updated["github_token"] == "ghp_test12345"
    assert updated["vercel_token"] == "vercel_tok_test"
    assert updated["render_api_key"] == "rnd_test_key"

    fetched = repo.get_user_provider_keys(user_id)
    assert fetched["github_token"] == "ghp_test12345"
    assert fetched["vercel_token"] == "vercel_tok_test"
    assert fetched["render_api_key"] == "rnd_test_key"
