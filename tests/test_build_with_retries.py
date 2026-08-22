"""Task 4 verification: fix-and-retry loop.

Runnable script:
    python tests/test_build_with_retries.py

All tests are pure (no network): build_in_sandbox and fix_build_errors are
mocked to exercise build_with_retries loop control, and the LLM is mocked to
exercise fix_build_errors parsing/validation.
"""

import contextlib
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import skills.build_demo as bd


@contextlib.contextmanager
def _env(**kv):
    saved = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: str(v) for k, v in kv.items()})
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


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


def _build_seq(*oks):
    """Return a fake build_in_sandbox yielding the given ok values in order."""
    calls = {"n": 0}

    def _fake(files):
        i = calls["n"]
        calls["n"] += 1
        ok = oks[i] if i < len(oks) else oks[-1]
        return {"ok": ok, "logs": "ok-log" if ok else f"fail-log-{i}", "image": "img"}

    _fake.calls = calls
    return _fake


def test_recovers_after_one_fix():
    build = _build_seq(False, True)  # fail then succeed
    fix_calls = {"n": 0}

    def fake_fix(files, error_log, demo_project):
        fix_calls["n"] += 1
        return {"package.json": "{}", "index.html": "<html>", "src/App.jsx": "fixed"}

    with _env(DEMO_MAX_RETRIES=2), _patch(build_in_sandbox=build, fix_build_errors=fake_fix):
        result = bd.build_with_retries({"package.json": "{}", "index.html": "<x>"}, {"title": "T"})

    assert result["ok"] is True, result
    assert result["attempts"] == 2, result
    assert fix_calls["n"] == 1, "should have patched exactly once"
    assert result["files"]["src/App.jsx"] == "fixed", "should return the patched files"
    print("✅ test_recovers_after_one_fix passed")


def test_gives_up_after_max_retries():
    build = _build_seq(False)  # always fails
    fix_calls = {"n": 0}

    def fake_fix(files, error_log, demo_project):
        fix_calls["n"] += 1
        return dict(files)  # unchanged patch

    with _env(DEMO_MAX_RETRIES=2), _patch(build_in_sandbox=build, fix_build_errors=fake_fix):
        result = bd.build_with_retries({"package.json": "{}", "index.html": "<x>"}, {"title": "T"})

    assert result["ok"] is False, result
    assert result["attempts"] == 3, f"1 initial + 2 retries = 3 builds, got {result['attempts']}"
    assert fix_calls["n"] == 2, f"should patch exactly max_retries times, got {fix_calls['n']}"
    assert build.calls["n"] == 3, "no infinite loop"
    print("✅ test_gives_up_after_max_retries passed")


def test_retry_count_respected_zero():
    build = _build_seq(False)
    fix_calls = {"n": 0}

    def fake_fix(files, error_log, demo_project):
        fix_calls["n"] += 1
        return dict(files)

    with _env(DEMO_MAX_RETRIES=0), _patch(build_in_sandbox=build, fix_build_errors=fake_fix):
        result = bd.build_with_retries({"package.json": "{}", "index.html": "<x>"}, {"title": "T"})

    assert result["ok"] is False
    assert result["attempts"] == 1, "0 retries => a single build attempt"
    assert fix_calls["n"] == 0, "no fixes when retries are 0"
    print("✅ test_retry_count_respected_zero passed")


def test_fix_exception_breaks_cleanly():
    build = _build_seq(False)

    def exploding_fix(files, error_log, demo_project):
        raise ValueError("model returned junk")

    with _env(DEMO_MAX_RETRIES=3), _patch(build_in_sandbox=build, fix_build_errors=exploding_fix):
        result = bd.build_with_retries({"package.json": "{}", "index.html": "<x>"}, {"title": "T"})

    assert result["ok"] is False
    assert result["attempts"] == 1, "build once, fix raises, then stop"
    assert "fix_build_errors error" in result["logs"]
    print("✅ test_fix_exception_breaks_cleanly passed")


def test_fix_build_errors_parses_llm_output():
    import skills.llm_client as llm

    canned = (
        "<<<FILE package.json>>>\n{\"name\":\"d\",\"dependencies\":{\"react\":\"18.3.1\"}}\n<<<END>>>\n"
        "<<<FILE index.html>>>\n<html><div id=root></div></html>\n<<<END>>>\n"
        "<<<FILE src/App.jsx>>>\nexport default function App(){return null}\n<<<END>>>"
    )
    saved = llm.llm_generate
    llm.llm_generate = lambda **kw: canned
    try:
        fixed = bd.fix_build_errors({"index.html": "<broken"}, "Boom: bad import", {"title": "T"})
        assert set(fixed) == {"package.json", "index.html", "src/App.jsx"}, fixed.keys()
    finally:
        llm.llm_generate = saved

    # Missing required file -> loud failure.
    llm.llm_generate = lambda **kw: "<<<FILE only.txt>>>\nx\n<<<END>>>"
    try:
        bd.fix_build_errors({"index.html": "x"}, "err", {"title": "T"})
        raise AssertionError("expected ValueError for missing required files")
    except ValueError:
        pass
    finally:
        llm.llm_generate = saved

    print("✅ test_fix_build_errors_parses_llm_output passed")


if __name__ == "__main__":
    test_recovers_after_one_fix()
    test_gives_up_after_max_retries()
    test_retry_count_respected_zero()
    test_fix_exception_breaks_cleanly()
    test_fix_build_errors_parses_llm_output()
    print("\nTask 4 checks complete.")
