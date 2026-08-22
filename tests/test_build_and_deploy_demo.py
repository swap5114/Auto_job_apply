"""Task 6 verification: build_and_deploy_demo orchestrator.

Runnable script:
    python tests/test_build_and_deploy_demo.py

Pure tests: generate/build/deploy stages are mocked to exercise every branch
(deployed, skipped, generation-fail, build-fail, deploy-fail) and to prove no
exception escapes on failure.
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


def _boom(*a, **k):
    raise AssertionError("this stage should NOT have been called")


_LEAD = {"id": "abc123", "company": "Acme Corp", "role": "FE", "jd_text": "build stuff"}


def test_happy_path_deployed():
    with _patch(
        _resolve_demo_project=lambda lead: {"title": "T"},
        generate_demo_app=lambda dp, lead: {"package.json": "{}", "index.html": "x"},
        build_with_retries=lambda files, dp: {"ok": True, "files": files, "logs": "", "attempts": 1},
        deploy_to_vercel=lambda files, name: "https://live.vercel.app",
    ):
        result = bd.build_and_deploy_demo(_LEAD)
    assert result == {"demo_url": "https://live.vercel.app", "demo_status": "deployed"}, result
    print("✅ test_happy_path_deployed passed")


def test_skipped_when_no_demo_project():
    with _patch(_resolve_demo_project=lambda lead: None, generate_demo_app=_boom):
        result = bd.build_and_deploy_demo(_LEAD)
    assert result == {"demo_url": "", "demo_status": "skipped"}, result
    print("✅ test_skipped_when_no_demo_project passed")


def test_generation_failure_is_build_failed():
    def gen_raises(dp, lead):
        raise RuntimeError("LLM junk")

    with _patch(
        _resolve_demo_project=lambda lead: {"title": "T"},
        generate_demo_app=gen_raises,
        build_with_retries=_boom,
    ):
        result = bd.build_and_deploy_demo(_LEAD)
    assert result == {"demo_url": "", "demo_status": "build_failed"}, result
    print("✅ test_generation_failure_is_build_failed passed")


def test_build_failure_skips_deploy():
    with _patch(
        _resolve_demo_project=lambda lead: {"title": "T"},
        generate_demo_app=lambda dp, lead: {"package.json": "{}", "index.html": "x"},
        build_with_retries=lambda files, dp: {"ok": False, "files": files, "logs": "boom", "attempts": 3},
        deploy_to_vercel=_boom,  # must not be called
    ):
        result = bd.build_and_deploy_demo(_LEAD)
    assert result == {"demo_url": "", "demo_status": "build_failed"}, result
    print("✅ test_build_failure_skips_deploy passed")


def test_deploy_failure_is_build_failed():
    def deploy_raises(files, name):
        raise RuntimeError("vercel 500")

    with _patch(
        _resolve_demo_project=lambda lead: {"title": "T"},
        generate_demo_app=lambda dp, lead: {"package.json": "{}", "index.html": "x"},
        build_with_retries=lambda files, dp: {"ok": True, "files": files, "logs": "", "attempts": 1},
        deploy_to_vercel=deploy_raises,
    ):
        result = bd.build_and_deploy_demo(_LEAD)
    assert result == {"demo_url": "", "demo_status": "build_failed"}, result
    print("✅ test_deploy_failure_is_build_failed passed")


if __name__ == "__main__":
    test_happy_path_deployed()
    test_skipped_when_no_demo_project()
    test_generation_failure_is_build_failed()
    test_build_failure_skips_deploy()
    test_deploy_failure_is_build_failed()
    print("\nTask 6 checks complete.")
