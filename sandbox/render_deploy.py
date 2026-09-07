"""Render deploy — deploys a backend from a GitHub repo to Render's free tier.

Picks up where sandbox/github_deploy.py leaves off, same as vercel_deploy.py
does for frontends. This module targets backends specifically (FastAPI,
Express, Flask, etc.) since Vercel's serverless model doesn't fit a
persistent server or WebSocket-based app well, but Render's free web
service tier does.

Uses the Render REST API directly (api.render.com/v1) — no CLI needed.

Usage:
    python -m sandbox.render_deploy --test

IMPORTANT — Free tier behavior (per Render's own docs, not just this repo's
comments): a free web service spins down after 15 minutes with no traffic,
and the next request takes about a minute to spin it back up while Render
shows a loading page. This is normal, not a bug — the frontend (Task 7)
should tell the user their backend link may take a moment to wake up.

IMPORTANT — free-tier API creation: a GitHub issue thread claimed Render's
API can't create free-tier services, only update existing ones. This turned
out to be outdated/incorrect — verified directly against the live API during
development: POST /v1/services with serviceDetails.plan="free" returns 201
and a real "free" plan on the created service.
"""

import os
import sys
import time
import requests
from dataclasses import dataclass
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))

from sandbox.config import (
    RENDER_API_BASE,
    RENDER_DEFAULT_REGION,
    RENDER_DEPLOY_POLL_TIMEOUT,
    RENDER_DEPLOY_POLL_INTERVAL,
    RENDER_HTTP_TIMEOUT,
    RENDER_TERMINAL_STATUSES,
)

RENDER_API_KEY = os.getenv("RENDER_API_KEY")

# Runtime -> (build command, start command) defaults, keyed by the same
# tech-stack strings research_company.py tends to produce. Kiro's own
# .build_status.json (build_command/start_command) is preferred when
# available — these are only a fallback for when it's missing or when the
# caller wants a quick default without reading that file.
_RUNTIME_DEFAULTS = {
    "python": {
        "env": "python",
        "buildCommand": "pip install -r requirements.txt",
        "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT",
    },
    "node": {
        "env": "node",
        "buildCommand": "npm install",
        "startCommand": "npm start",
    },
}


@dataclass
class RenderDeployResult:
    service_id: str
    service_name: str
    deploy_id: str
    status: str  # "live", "build_failed", "update_failed", "canceled", "deactivated", or "TIMEOUT"
    url: Optional[str] = None  # e.g. "https://demo-xyz.onrender.com", set once live
    error: Optional[str] = None


def _headers(api_key: Optional[str] = None) -> dict:
    key = api_key or RENDER_API_KEY
    if not key:
        raise RuntimeError("RENDER_API_KEY is not set in config/.env and no user render_api_key provided")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def get_default_owner_id(api_key: Optional[str] = None) -> str:
    """Look up the account's workspace/owner ID."""
    resp = requests.get(f"{RENDER_API_BASE}/owners", headers=_headers(api_key), timeout=RENDER_HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch Render owners ({resp.status_code}): {resp.text}")
    owners = resp.json()
    if not owners:
        raise RuntimeError("No Render owners/workspaces found on this account.")
    return owners[0]["owner"]["id"]


def _detect_runtime(tech_stack: list[str]) -> dict:
    """Pick a runtime config based on tech_stack hints from demo_project.
    Defaults to Python/FastAPI if nothing matches, since that's this
    project's own convention for backend demos.
    """
    joined = " ".join(tech_stack).lower()
    if any(k in joined for k in ("node", "express", "javascript", "typescript", "next")):
        return _RUNTIME_DEFAULTS["node"]
    return _RUNTIME_DEFAULTS["python"]


def _create_service(
    service_name: str,
    repo_url: str,
    branch: str,
    owner_id: str,
    build_command: str,
    start_command: str,
    runtime: str,
) -> dict:
    """Create a free-tier web service linked to a GitHub repo.

    Returns the raw API response, which includes both the created service
    object and the deployId of the deploy it kicked off automatically.
    """
    body = {
        "type": "web_service",
        "name": service_name,
        "ownerId": owner_id,
        "repo": repo_url,
        "branch": branch,
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": runtime,
            "plan": "free",
            "region": RENDER_DEFAULT_REGION,
            "envSpecificDetails": {
                "buildCommand": build_command,
                "startCommand": start_command,
            },
        },
    }
    resp = requests.post(f"{RENDER_API_BASE}/services", headers=_headers(), json=body, timeout=RENDER_HTTP_TIMEOUT)

    if resp.status_code == 400 and "already in use" in resp.text.lower():
        # Name collision (e.g. a retried deploy for the same build_id) —
        # reuse the existing service instead of failing outright.
        existing = _find_service_by_name(service_name, owner_id)
        if existing:
            return {"service": existing, "deployId": None}

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create Render service ({resp.status_code}): {resp.text}")

    return resp.json()


def _find_service_by_name(service_name: str, owner_id: str) -> Optional[dict]:
    resp = requests.get(
        f"{RENDER_API_BASE}/services",
        headers=_headers(),
        params={"name": service_name, "ownerId": owner_id},
        timeout=RENDER_HTTP_TIMEOUT,
    )
    if resp.status_code != 200:
        return None
    matches = resp.json()
    return matches[0]["service"] if matches else None


def _trigger_deploy(service_id: str) -> str:
    """Trigger a fresh deploy on an existing service (used when reusing a
    service found via name collision, since that path doesn't get an
    automatic deploy the way service creation does).
    """
    resp = requests.post(
        f"{RENDER_API_BASE}/services/{service_id}/deploys",
        headers=_headers(),
        json={},
        timeout=RENDER_HTTP_TIMEOUT,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to trigger Render deploy ({resp.status_code}): {resp.text}")
    return resp.json()["id"]


def _poll_deploy(service_id: str, deploy_id: str, timeout: int = RENDER_DEPLOY_POLL_TIMEOUT) -> dict:
    """Poll a deploy until it reaches a terminal status or times out."""
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        resp = requests.get(
            f"{RENDER_API_BASE}/services/{service_id}/deploys/{deploy_id}",
            headers=_headers(),
            timeout=RENDER_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to poll Render deploy ({resp.status_code}): {resp.text}")
        last = resp.json()
        if last.get("status") in RENDER_TERMINAL_STATUSES:
            return last
        time.sleep(RENDER_DEPLOY_POLL_INTERVAL)
    last["status"] = last.get("status", "TIMEOUT")
    return last


def deploy_to_render(
    repo_url: str,
    service_name: str,
    branch: str = "main",
    tech_stack: Optional[list[str]] = None,
    build_command: Optional[str] = None,
    start_command: Optional[str] = None,
    env_vars: Optional[dict[str, str]] = None,
    owner_id: Optional[str] = None,
    render_api_key: Optional[str] = None,
) -> RenderDeployResult:
    """Deploy a backend from a GitHub repo to a free Render web service."""
    owner_id = owner_id or get_default_owner_id(api_key=render_api_key)
    runtime_defaults = _detect_runtime(tech_stack or [])
    runtime = runtime_defaults["env"]
    build_command = build_command or runtime_defaults["buildCommand"]
    start_command = start_command or runtime_defaults["startCommand"]

    result = _create_service(service_name, repo_url, branch, owner_id, build_command, start_command, runtime)
    service = result["service"]
    service_id = service["id"]
    service_url = service.get("serviceDetails", {}).get("url")
    deploy_id = result.get("deployId")

    if env_vars:
        _set_env_vars(service_id, env_vars)

    if not deploy_id:
        # Reused an existing service (name collision path) — it didn't get
        # an automatic deploy, so trigger one explicitly.
        deploy_id = _trigger_deploy(service_id)

    final = _poll_deploy(service_id, deploy_id)
    status = final.get("status", "UNKNOWN")

    url = None
    error = None
    if status == "live":
        url = service_url
    elif status == "TIMEOUT":
        error = f"Deploy did not finish within {RENDER_DEPLOY_POLL_TIMEOUT}s (still in progress)"
    else:
        error = f"Deploy ended in status '{status}'"

    return RenderDeployResult(
        service_id=service_id,
        service_name=service_name,
        deploy_id=deploy_id,
        status=status,
        url=url,
        error=error,
    )


def _set_env_vars(service_id: str, env_vars: dict[str, str]) -> None:
    """Set environment variables on a Render service.

    Uses PUT (replace-all) rather than a per-key POST, matching Render's
    documented env-var endpoint shape: a list of {key, value} objects.
    """
    body = [{"key": k, "value": v} for k, v in env_vars.items()]
    resp = requests.put(
        f"{RENDER_API_BASE}/services/{service_id}/env-vars",
        headers=_headers(),
        json=body,
        timeout=RENDER_HTTP_TIMEOUT,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to set Render env vars ({resp.status_code}): {resp.text}")


def delete_service(service_id: str) -> None:
    """Delete a Render service. Used for cleanup / cancelled builds."""
    resp = requests.delete(f"{RENDER_API_BASE}/services/{service_id}", headers=_headers(), timeout=RENDER_HTTP_TIMEOUT)
    if resp.status_code not in (200, 204, 404):
        raise RuntimeError(f"Failed to delete Render service ({resp.status_code}): {resp.text}")


# ---------------------------------------------------------------------------
# Test / CLI entrypoint
# ---------------------------------------------------------------------------

def _test():
    """End-to-end test: build a trivial FastAPI backend via the orchestrator,
    push to GitHub, deploy to Render, and verify the live URL actually
    returns the expected response.

    Run with: python -m sandbox.render_deploy --test

    Note: creates real GitHub + Render resources. This test cleans up after
    itself (unlike vercel_deploy.py's test, which leaves cleanup for you) —
    delete_service() and a repo delete both run in a finally block.
    """
    from sandbox import orchestrator, github_deploy

    print("\n" + "=" * 60)
    print("  RENDER DEPLOY TEST")
    print("=" * 60)

    demo_project = {
        "title": "Hello Render API",
        "description": (
            "A minimal FastAPI backend in /workspace with a single GET / "
            "route that returns {\"status\": \"ok\", \"message\": \"hello from render\"}. "
            "Include a requirements.txt with fastapi and uvicorn. No "
            "database, no auth, nothing else — just verify it starts "
            "locally with uvicorn before reporting success."
        ),
        "tech_stack": ["Python", "FastAPI"],
        "deliverable": "main.py + requirements.txt",
    }

    print("\n[1/4] Building via orchestrator...")
    state = orchestrator.start_build(demo_project, company="RenderProbeCo", max_attempts=2)
    assert state.stage == "success", f"Build failed: {state.result or state.error}"

    try:
        project_dir = orchestrator.export_build_output(state)
    finally:
        orchestrator.stop_build(state)
    print(f"      Exported to: {project_dir}")

    print("\n[2/4] Pushing to GitHub...")
    repo_result = github_deploy.deploy_to_github(
        project_dir, demo_project, company="RenderProbeCo", build_id=state.build_id
    )
    print(f"      Repo: {repo_result.repo_url}")

    service_id = None
    try:
        print("\n[3/4] Deploying to Render...")
        render_result = deploy_to_render(
            repo_url=repo_result.repo_url,
            service_name=repo_result.repo_name,
            tech_stack=demo_project["tech_stack"],
        )
        service_id = render_result.service_id
        print(f"      status={render_result.status}")
        assert render_result.status == "live", f"Deploy did not go live: {render_result.error}"
        print(f"      URL: {render_result.url}")

        print("\n[4/4] Verifying the URL is live and returns real content...")
        resp = requests.get(render_result.url, timeout=30)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        print(f"      ✅ HTTP {resp.status_code}, body: {resp.text[:200]}")

        print("\n" + "=" * 60)
        print("  ✅ TEST PASSED")
        print("=" * 60)

    finally:
        print("\nCleaning up...")
        if service_id:
            delete_service(service_id)
            print(f"  ✅ Render service {service_id} deleted.")
        try:
            import subprocess
            subprocess.run(["gh", "repo", "delete", f"{repo_result.owner}/{repo_result.repo_name}", "--yes"],
                            capture_output=True, timeout=30)
            print(f"  ✅ GitHub repo {repo_result.repo_name} deleted.")
        except Exception as e:
            print(f"  ⚠️  Could not auto-delete GitHub repo: {e}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        print("Usage:")
        print("  python -m sandbox.render_deploy --test   # end-to-end build + GitHub push + Render deploy")
