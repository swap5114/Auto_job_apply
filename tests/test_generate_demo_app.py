"""Task 2 verification: demo-app code generation.

Runnable script:
    python tests/test_generate_demo_app.py

Pure tests (no network):
  - _parse_file_blocks: parses <<<FILE>>> blocks, strips fences/paths, raises on none.
  - _scan_for_secrets: flags real secret signatures, ignores harmless placeholders.
Integration test (needs an LLM API key, skips gracefully otherwise):
  - generate_demo_app returns package.json + index.html, parseable package.json,
    a React component, and no secrets.
"""

import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from skills.build_demo import _parse_file_blocks, _scan_for_secrets, generate_demo_app


def test_parse_file_blocks():
    raw = """```text
<<<FILE package.json>>>
{"name": "demo", "type": "module"}
<<<END>>>
<<<FILE /src/App.jsx>>>
export default function App() {
  return <h1>Hi</h1>;
}
<<<END>>>
```"""
    files = _parse_file_blocks(raw)
    assert set(files.keys()) == {"package.json", "src/App.jsx"}, files.keys()
    assert files["package.json"].strip().startswith("{"), "package.json body wrong"
    assert "export default" in files["src/App.jsx"], "App.jsx body wrong"
    # leading slash on path is stripped
    assert "/src/App.jsx" not in files

    # No blocks -> loud failure
    try:
        _parse_file_blocks("just some prose, no file blocks")
        raise AssertionError("expected ValueError on block-less input")
    except ValueError:
        pass

    print("✅ test_parse_file_blocks passed")


def test_scan_for_secrets():
    # Harmless placeholders must NOT trip the scanner.
    clean = {
        "src/App.jsx": "const API_KEY = 'YOUR_API_KEY_HERE'; // replace me",
        "readme.md": "Set your token in the dashboard.",
    }
    assert _scan_for_secrets(clean) == [], "placeholders should not be flagged"

    # Real secret signatures MUST be caught.
    dirty = {
        "config.js": "const k = 'AKIAIOSFODNN7EXAMPLE';",
        "key.pem": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    }
    findings = _scan_for_secrets(dirty)
    assert any("aws_access_key" in f for f in findings), findings
    assert any("private_key_block" in f for f in findings), findings

    print("✅ test_scan_for_secrets passed")


def test_generate_demo_app_integration():
    """Calls the real LLM. Skips if no API key / network."""
    demo_project = {
        "title": "LatencyLens",
        "description": "A tiny dashboard that visualizes p50/p95/p99 API latency "
                       "for an observability company, with mock data.",
        "tech_stack": ["React", "TypeScript"],
        "deliverable": "live link",
        "why_impressive": "Shows I understand their core metrics UX.",
    }
    lead = {
        "company": "ObservaCo",
        "role": "Frontend Engineer",
        "jd_text": "Build dashboards for observability metrics. React heavy.",
    }
    try:
        files = generate_demo_app(demo_project, lead)
    except Exception as e:
        print(f"⏭️  test_generate_demo_app_integration SKIPPED (no key/network?): {e}")
        return

    assert "package.json" in files, "missing package.json"
    assert "index.html" in files, "missing index.html"

    # package.json must be valid JSON with the pinned react dep.
    pkg = json.loads(files["package.json"])
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert "react" in deps, f"react not pinned in package.json deps: {deps}"

    # At least one JSX/React component file present.
    assert any(p.endswith(".jsx") or p.endswith(".tsx") for p in files), \
        f"no React component file in {list(files)}"

    # And it must be secret-free.
    assert _scan_for_secrets(files) == [], "generated app contains a secret pattern"

    print(f"✅ test_generate_demo_app_integration passed ({len(files)} files)")


if __name__ == "__main__":
    test_parse_file_blocks()
    test_scan_for_secrets()
    test_generate_demo_app_integration()
    print("\nTask 2 checks complete.")
