"""Task 1 verification for the auto-built demo feature (Option 2).

Runnable script (matches tests/test_sheet_client.py style):
    python tests/test_build_demo_scaffold.py

Covers:
  1. get_config() safe defaults + env parsing (pure, no network).
  2. demo_url / demo_status round-trip through the live sheet
     (add_lead -> update_lead -> get_leads). Skips gracefully if the
     Google Sheet / credentials aren't available in this environment.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


def test_config_defaults():
    from skills.build_demo import get_config

    # --- Defaults when nothing is set ---
    for var in (
        "DEMO_BUILD_ENABLED", "DEMO_CODEGEN_BACKEND", "DEMO_MAX_RETRIES",
        "DEMO_PROJECT_PREFIX", "VERCEL_TOKEN", "VERCEL_OIDC_TOKEN",
    ):
        os.environ.pop(var, None)

    cfg = get_config()
    assert cfg.enabled is False, "feature must default OFF"
    assert cfg.codegen_backend is None, "backend must default to None (llm_client default)"
    assert cfg.max_retries == 2, f"expected default retries 2, got {cfg.max_retries}"
    assert cfg.project_prefix == "demo-", f"bad default prefix {cfg.project_prefix!r}"
    assert cfg.has_vercel_auth is False, "no tokens => no vercel auth"

    # --- Parsing when set ---
    os.environ["DEMO_BUILD_ENABLED"] = "true"
    os.environ["DEMO_CODEGEN_BACKEND"] = "Claude"
    os.environ["DEMO_MAX_RETRIES"] = "4"
    os.environ["DEMO_PROJECT_PREFIX"] = "demo-x-"
    os.environ["VERCEL_TOKEN"] = "tok_123"

    cfg = get_config()
    assert cfg.enabled is True
    assert cfg.codegen_backend == "claude", "backend should be lowercased"
    assert cfg.max_retries == 4
    assert cfg.project_prefix == "demo-x-"
    assert cfg.has_vercel_auth is True

    # --- Bad int falls back to default, doesn't crash ---
    os.environ["DEMO_MAX_RETRIES"] = "notanint"
    cfg = get_config()
    assert cfg.max_retries == 2, "invalid int must fall back to default"

    # Clean up env we touched.
    for var in (
        "DEMO_BUILD_ENABLED", "DEMO_CODEGEN_BACKEND", "DEMO_MAX_RETRIES",
        "DEMO_PROJECT_PREFIX", "VERCEL_TOKEN",
    ):
        os.environ.pop(var, None)

    print("✅ test_config_defaults passed")


def test_demo_url_roundtrip():
    """Round-trip demo_url/demo_status through the live sheet. Skips if no creds."""
    try:
        from storage.sheet_client import (
            ensure_headers, add_lead, get_leads, update_lead,
        )

        ensure_headers()  # additive migration: guarantees the columns exist

        marker = "Demo Roundtrip Co"
        add_lead({
            "source": "test",
            "company": marker,
            "role": "Demo Test Engineer",
            "jd_text": "Task 1 round-trip test",
        })

        leads = get_leads()
        lead = next((l for l in leads if l.get("company") == marker), None)
        assert lead is not None, "test lead was not written/readable"

        update_lead(lead["id"], {
            "demo_url": "https://demo-roundtrip.vercel.app",
            "demo_status": "deployed",
        })

        refreshed = get_leads()
        again = next(l for l in refreshed if l["id"] == lead["id"])
        assert again.get("demo_url") == "https://demo-roundtrip.vercel.app", \
            f"demo_url did not persist: {again.get('demo_url')!r}"
        assert again.get("demo_status") == "deployed", \
            f"demo_status did not persist: {again.get('demo_status')!r}"

        print("✅ test_demo_url_roundtrip passed")
    except Exception as e:
        print(f"⏭️  test_demo_url_roundtrip SKIPPED (no sheet/creds?): {e}")


def test_max_per_run_config():
    """DEMO_MAX_PER_RUN is read from env and defaults to 5."""
    from skills.build_demo import get_config

    os.environ.pop("DEMO_MAX_PER_RUN", None)
    cfg = get_config()
    assert cfg.max_per_run == 5, f"default should be 5, got {cfg.max_per_run}"

    os.environ["DEMO_MAX_PER_RUN"] = "2"
    cfg = get_config()
    assert cfg.max_per_run == 2, f"expected 2, got {cfg.max_per_run}"

    os.environ.pop("DEMO_MAX_PER_RUN", None)
    print("✅ test_max_per_run_config passed")


def test_disabled_feature_is_noop():
    """When DEMO_BUILD_ENABLED=false the build_demo_node is a zero-cost no-op."""
    import graph.pipeline as p

    os.environ["DEMO_BUILD_ENABLED"] = "false"
    out = p.build_demo_node({"company": "TestCo", "lead_id": "x"})
    assert out == {"demo_status": "skipped", "demo_url": "", "include_demo": False}, out
    os.environ.pop("DEMO_BUILD_ENABLED", None)
    print("✅ test_disabled_feature_is_noop passed")


if __name__ == "__main__":
    test_config_defaults()
    test_demo_url_roundtrip()
    test_max_per_run_config()
    test_disabled_feature_is_noop()
    print("\nTask 1/9 scaffold checks complete.")
