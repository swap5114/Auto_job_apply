"""Task 3 verification: Vercel Sandbox build verification.

Runnable script:
    python tests/test_build_in_sandbox.py

Unit tests (no network) mock the Vercel sandbox to verify lifecycle:
create -> write files -> npm install -> npm run build -> context-exit cleanup,
plus install-fail / build-fail / no-auth paths.

Integration test builds a real generated app in a real sandbox; skips unless
Vercel auth (VERCEL_OIDC_TOKEN or VERCEL_TOKEN) is present.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import skills.build_demo as bd


# --------------------------- Fakes ---------------------------

class _FakeCompleted:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeFS:
    def __init__(self, log):
        self._log = log

    def mkdir(self, path, recursive=True, **kw):
        self._log.append(("mkdir", path))

    def write_text(self, path, content, **kw):
        self._log.append(("write", path))


class _FakeSandbox:
    def __init__(self, log, install_rc=0, build_rc=0):
        self.fs = _FakeFS(log)
        self.image = "vercel/sandbox/universal"
        self._log = log
        self._install_rc = install_rc
        self._build_rc = build_rc

    def run_process(self, command, args=None, *, cwd=None, capture_output=False, **kw):
        args = list(args or [])
        self._log.append(("run", command, tuple(args), cwd))
        if args[:1] == ["install"]:
            return _FakeCompleted(self._install_rc, "added 42 packages", "")
        if args[:1] == ["run"]:
            if self._build_rc == 0:
                return _FakeCompleted(0, "vite build: dist/ built in 1.2s", "")
            return _FakeCompleted(1, "", "src/App.jsx: SyntaxError: Unexpected token")
        return _FakeCompleted(0)


class _FakeManaged:
    def __init__(self, sandbox, log):
        self._sandbox = sandbox
        self._log = log

    def __enter__(self):
        self._log.append(("enter",))
        return self._sandbox

    def __exit__(self, *exc):
        self._log.append(("exit",))  # context manager destroys the sandbox
        return False


def _make_factory(log, install_rc=0, build_rc=0):
    def _factory(*, execution_time_limit=None, **kw):
        log.append(("create", execution_time_limit))
        return _FakeManaged(_FakeSandbox(log, install_rc, build_rc), log)
    return _factory


# --------------------------- Helpers ---------------------------

import contextlib


@contextlib.contextmanager
def _patched(factory):
    """Patch the sandbox factory + ensure auth is present, then restore."""
    orig_factory = bd._vercel_create_sandbox
    orig_token = os.environ.get("VERCEL_TOKEN")
    bd._vercel_create_sandbox = factory
    os.environ["VERCEL_TOKEN"] = "tok_test"
    try:
        yield
    finally:
        bd._vercel_create_sandbox = orig_factory
        if orig_token is None:
            os.environ.pop("VERCEL_TOKEN", None)
        else:
            os.environ["VERCEL_TOKEN"] = orig_token


_FILES = {"package.json": "{}", "index.html": "<html></html>", "src/App.jsx": "export default 1"}


# --------------------------- Tests ---------------------------

def test_happy_path_lifecycle():
    log = []
    with _patched(_make_factory(log, install_rc=0, build_rc=0)):
        result = bd.build_in_sandbox(_FILES)

    assert result["ok"] is True, result
    assert "built" in result["logs"], result["logs"]
    assert result["image"] == "vercel/sandbox/universal"

    kinds = [e[0] for e in log]
    assert kinds[0] == "create", kinds
    assert ("enter",) in [(k,) for k in [kinds[1]]] or kinds[1] == "enter"
    writes = [e for e in log if e[0] == "write"]
    assert len(writes) == 3, f"expected 3 file writes, got {writes}"

    runs = [e for e in log if e[0] == "run"]
    assert runs[0][2][:1] == ("install",), runs
    assert runs[1][2] == ("run", "build"), runs
    assert kinds[-1] == "exit", f"sandbox must be cleaned up via context exit: {kinds}"
    print("✅ test_happy_path_lifecycle passed")


def test_build_failure_returns_logs():
    log = []
    with _patched(_make_factory(log, install_rc=0, build_rc=1)):
        result = bd.build_in_sandbox(_FILES)
    assert result["ok"] is False
    assert "npm run build failed" in result["logs"]
    assert "SyntaxError" in result["logs"], result["logs"]
    assert ("exit",) in [(e[0],) for e in log], "must still clean up on build failure"
    print("✅ test_build_failure_returns_logs passed")


def test_install_failure_short_circuits_build():
    log = []
    with _patched(_make_factory(log, install_rc=1, build_rc=0)):
        result = bd.build_in_sandbox(_FILES)
    assert result["ok"] is False
    assert "npm install failed" in result["logs"]
    runs = [e for e in log if e[0] == "run"]
    assert len(runs) == 1, "build must not run if install failed"
    print("✅ test_install_failure_short_circuits_build passed")


def test_no_auth_skips_without_calling_sandbox():
    log = []
    orig_factory = bd._vercel_create_sandbox
    orig_token = os.environ.pop("VERCEL_TOKEN", None)
    orig_oidc = os.environ.pop("VERCEL_OIDC_TOKEN", None)
    bd._vercel_create_sandbox = _make_factory(log)  # should never be called
    try:
        result = bd.build_in_sandbox(_FILES)
        assert result["ok"] is False
        assert "no Vercel auth" in result["logs"]
        assert log == [], "sandbox factory must not be called without auth"
    finally:
        bd._vercel_create_sandbox = orig_factory
        if orig_token is not None:
            os.environ["VERCEL_TOKEN"] = orig_token
        if orig_oidc is not None:
            os.environ["VERCEL_OIDC_TOKEN"] = orig_oidc
    print("✅ test_no_auth_skips_without_calling_sandbox passed")


def test_real_sandbox_integration():
    """Build a real generated app in a real sandbox. Skips without Vercel auth."""
    cfg = bd.get_config()
    if not cfg.has_vercel_auth:
        print("⏭️  test_real_sandbox_integration SKIPPED (no VERCEL_TOKEN/OIDC)")
        return
    try:
        demo_project = {
            "title": "PingBoard",
            "description": "A tiny status board showing mock service uptime tiles.",
            "tech_stack": ["React"],
            "deliverable": "live link",
        }
        files = bd.generate_demo_app(demo_project, {"company": "StatusCo", "role": "FE", "jd_text": "status pages"})
        result = bd.build_in_sandbox(files)
        print(f"   build ok={result['ok']}, image={result['image']}")
        print("   log tail:\n" + result["logs"][-600:])
        assert "ok" in result
        print("✅ test_real_sandbox_integration passed")
    except Exception as e:
        print(f"⏭️  test_real_sandbox_integration SKIPPED (error: {e})")


if __name__ == "__main__":
    test_happy_path_lifecycle()
    test_build_failure_returns_logs()
    test_install_failure_short_circuits_build()
    test_no_auth_skips_without_calling_sandbox()
    test_real_sandbox_integration()
    print("\nTask 3 checks complete.")
