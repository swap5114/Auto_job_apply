"""Task 7 verification: graph integration + repositioned review.

Runnable script:
    python tests/test_pipeline_build_demo.py

Pure tests (no network): build_demo_node gating, review decision mapping,
and the compiled main-graph wiring (build_demo before review; review -> draft -> send).
"""

import contextlib
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import graph.pipeline as p
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
def _patch(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


_STATE = {"lead_id": "id1", "company": "Acme", "role": "FE", "jd_text": "build",
          "company_research": {"demo_project": {"title": "T"}}}


def test_build_demo_node_disabled_is_noop():
    def _boom(lead):
        raise AssertionError("build_and_deploy_demo must NOT be called when disabled")

    with _env(DEMO_BUILD_ENABLED="false"), _patch(bd, build_and_deploy_demo=_boom):
        out = p.build_demo_node(_STATE)
    assert out == {"demo_status": "skipped", "demo_url": "", "include_demo": False}, out
    print("✅ test_build_demo_node_disabled_is_noop passed")


def test_build_demo_node_enabled_calls_orchestrator():
    calls = {"n": 0}

    def fake_bd(lead):
        calls["n"] += 1
        assert lead["company"] == "Acme"
        assert lead["company_research"]["demo_project"]["title"] == "T"
        return {"demo_url": "https://x.vercel.app", "demo_status": "deployed"}

    with _env(DEMO_BUILD_ENABLED="true"), _patch(bd, build_and_deploy_demo=fake_bd):
        out = p.build_demo_node(_STATE)
    assert calls["n"] == 1
    assert out == {"demo_status": "deployed", "demo_url": "https://x.vercel.app", "include_demo": False}, out
    print("✅ test_build_demo_node_enabled_calls_orchestrator passed")


def test_build_demo_node_exception_guard():
    def kaboom(lead):
        raise RuntimeError("unexpected")

    with _env(DEMO_BUILD_ENABLED="true"), _patch(bd, build_and_deploy_demo=kaboom):
        out = p.build_demo_node(_STATE)
    assert out == {"demo_status": "build_failed", "demo_url": "", "include_demo": False}, out
    print("✅ test_build_demo_node_exception_guard passed")


def test_review_decision_mapping():
    f = p._interpret_review_decision

    # approve + deployed => send WITH link
    assert f("approved", True) == {"review_decision": "approved", "status": "approved", "include_demo": True}
    # approve + NOT deployed => send, but no link (zero fabrication)
    assert f("approved", False) == {"review_decision": "approved", "status": "approved", "include_demo": False}
    # explicit skip-demo => send WITHOUT link even if deployed
    assert f("reject_demo", True)["status"] == "approved"
    assert f("reject_demo", True)["include_demo"] is False
    # abort/reject => do NOT send
    r = f("rejected", True)
    assert r["status"] == "rejected" and r["include_demo"] is False
    # dict form with manual draft override
    d = f({"action": "approved", "outreach_draft": "hi there"}, True)
    assert d["status"] == "approved" and d["outreach_draft"] == "hi there"
    print("✅ test_review_decision_mapping passed")


def test_main_graph_wiring():
    g = p.build_pipeline_graph()  # no checkpointer needed for structure
    drawn = g.get_graph()
    nodes = set(drawn.nodes.keys())
    for n in ("find_email", "research_company", "tailor_resume", "build_demo", "review", "draft", "send"):
        assert n in nodes, f"missing node {n} in {nodes}"

    edges = {(e.source, e.target) for e in drawn.edges}
    assert ("tailor_resume", "build_demo") in edges, edges
    assert ("build_demo", "review") in edges, edges
    # review routes to draft (conditional) and draft -> send
    assert ("draft", "send") in edges, edges
    assert any(src == "review" and tgt == "draft" for (src, tgt) in edges), edges
    # draft must NOT feed back into review in the main graph
    assert ("draft", "review") not in edges, edges
    print("✅ test_main_graph_wiring passed")


if __name__ == "__main__":
    test_build_demo_node_disabled_is_noop()
    test_build_demo_node_enabled_calls_orchestrator()
    test_build_demo_node_exception_guard()
    test_review_decision_mapping()
    test_main_graph_wiring()
    print("\nTask 7 checks complete.")
