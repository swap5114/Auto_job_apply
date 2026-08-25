"""Tests for db/current_user.py -- the single-user bootstrap standing in for
Firebase Auth until Phase 3."""

import db.current_user as cu


def test_get_current_user_id_creates_and_returns_same_id():
    cu.reset_cache()
    first = cu.get_current_user_id()
    second = cu.get_current_user_id()
    assert first == second


def test_get_current_user_id_is_idempotent_across_cache_resets():
    """Resolving again after a cache reset must land on the SAME underlying
    user row (via get_or_create_user's firebase_uid lookup), not create a
    second one -- this is what makes restarting the process safe."""
    cu.reset_cache()
    first = cu.get_current_user_id()

    cu.reset_cache()
    second = cu.get_current_user_id()

    assert first == second
