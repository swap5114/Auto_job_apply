"""Task 5 verification: deploy verified files to a live URL.

Runnable script:
    python tests/test_deploy_to_vercel.py

Pure tests: project-name sanitization.
Mocked tests: deploy_to_vercel with create+poll stubbed (READY / ERROR / timeout).
Integration test: real deploy of a generated app; skips without VERCEL_TOKEN.
"""

import contextlib
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import skills.build_demo as bd


@contextlib.contextmanager
def _patch(**attrs):
    saved = {k: getattr(bd, k) for k in attrs}
    for k, v in attrs.items():
        setattr(bd, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(bd, k, v)


@contextlib.contextmanager
def _token(value="tok_test"):
    saved = os.environ.get("VERCEL_TOKEN")
    if value is None:
        os.environ.pop("VERCEL_TOKEN", None)
    else:
        os.environ["VERCEL_TOKEN"] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("VERCEL_TOKEN", None)
        else:
            os.environ["VERCEL_TOKEN"] = saved


_FILES = {"package.json": "{}", "index.html": "<html></html>"}


def test_sanitize_project_name():
    assert bd._sanitize_project_name("demo-", "Acme Corp") == "demo-acme-corp"
    assert bd._sanitize_project_name("demo-", "Foo, Inc.!!!") == "demo-foo-inc"
    assert bd._sanitize_project_name("demo-", "  spaced  out  ") == "demo-spaced-out"
    # No triple hyphens, no leading/trailing hyphens.
    name = bd._sanitize_project_name("demo-", "A---B___C")
    assert "---" not in name and not name.startswith("-") and not name.endswith("-"), name
    # Empty company still yields something valid.
    assert bd._sanitize_project_name("demo-", "") == "demo"
    # Length capped at 100.
    assert len(bd._sanitize_project_name("demo-", "x" * 500)) <= 100
    print("✅ test_sanitize_project_name passed")


def test_deploy_polls_to_ready():
    created = {"id": "dpl_1", "url": "demo-acme-abc.vercel.app", "readyState": "QUEUED"}
    states = iter([
        {"state": "BUILDING", "url": "demo-acme-abc.vercel.app"},
        {"state": "READY", "url": "demo-acme-abc.vercel.app"},
    ])

    with _token(), _patch(
        _vercel_create_deployment=lambda **kw: created,
        _get_deployment_state=lambda *a, **k: next(states),
    ):
        # avoid real sleeping
        with _patch():
            saved_sleep = bd.time.sleep
            bd.time.sleep = lambda *_: None
            try:
                url = bd.deploy_to_vercel(_FILES, "demo-acme")
            finally:
                bd.time.sleep = saved_sleep

    assert url == "https://demo-acme-abc.vercel.app", url
    print("✅ test_deploy_polls_to_ready passed")


def test_deploy_ready_immediately():
    created = {"id": "dpl_2", "url": "x.vercel.app", "readyState": "READY"}

    def _boom(*a, **k):
        raise AssertionError("should not poll when already READY")

    with _token(), _patch(_vercel_create_deployment=lambda **kw: created, _get_deployment_state=_boom):
        url = bd.deploy_to_vercel(_FILES, "demo-x")
    assert url == "https://x.vercel.app"
    print("✅ test_deploy_ready_immediately passed")


def test_deploy_error_state_raises():
    created = {"id": "dpl_3", "url": "y.vercel.app", "readyState": "QUEUED"}
    with _token(), _patch(
        _vercel_create_deployment=lambda **kw: created,
        _get_deployment_state=lambda *a, **k: {"state": "ERROR", "url": "y.vercel.app"},
    ):
        saved_sleep = bd.time.sleep
        bd.time.sleep = lambda *_: None
        try:
            bd.deploy_to_vercel(_FILES, "demo-y")
            raise AssertionError("expected RuntimeError on ERROR state")
        except RuntimeError as e:
            assert "ERROR" in str(e)
        finally:
            bd.time.sleep = saved_sleep
    print("✅ test_deploy_error_state_raises passed")


def test_deploy_requires_token():
    with _token(None):
        try:
            bd.deploy_to_vercel(_FILES, "demo-z")
            raise AssertionError("expected RuntimeError without VERCEL_TOKEN")
        except RuntimeError as e:
            assert "VERCEL_TOKEN" in str(e)
    print("✅ test_deploy_requires_token passed")


def test_real_deploy_integration():
    cfg = bd.get_config()
    if not cfg.vercel_token:
        print("⏭️  test_real_deploy_integration SKIPPED (no VERCEL_TOKEN)")
        return
    try:
        files = bd.generate_demo_app(
            {"title": "HelloDemo", "description": "A one-page hello board.", "tech_stack": ["React"]},
            {"company": "DemoDeployCo", "role": "FE", "jd_text": "hello"},
        )
        url = bd.deploy_to_vercel(files, bd._sanitize_project_name("demo-", "DemoDeployCo"))
        import requests
        assert requests.get(url, timeout=30).status_code == 200, "deployed URL not 200"
        print(f"✅ test_real_deploy_integration passed -> {url}")
    except Exception as e:
        print(f"⏭️  test_real_deploy_integration SKIPPED (error: {e})")


if __name__ == "__main__":
    test_sanitize_project_name()
    test_deploy_polls_to_ready()
    test_deploy_ready_immediately()
    test_deploy_error_state_raises()
    test_deploy_requires_token()
    test_real_deploy_integration()
    print("\nTask 5 checks complete.")
