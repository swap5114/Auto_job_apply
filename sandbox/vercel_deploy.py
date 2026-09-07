"""Vercel deploy — links a GitHub repo to a Vercel project and deploys it.

Picks up where sandbox/github_deploy.py leaves off: given an owner/repo that
already exists on GitHub (with code already pushed), this creates a Vercel
project linked to it and triggers a production deployment via the REST API.

Uses the Vercel REST API directly (no CLI — none is installed on this
machine, and the API turned out to cover everything needed).

Usage:
    python -m sandbox.vercel_deploy --test

IMPORTANT — Deployment Protection: by default, Vercel puts EVERY deployment
(including "production") behind a Vercel-account login wall on this account
(ssoProtection.deploymentType == "all"). A demo link sent to a hiring manager
who isn't logged into your Vercel account would just redirect them to a
login page. deploy_to_vercel() explicitly disables this per-project via
PATCH ssoProtection=None, verified against a real deployment during
development (confirmed 302->vercel.com/sso-api before the fix, 200 OK after).
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
    VERCEL_API_BASE,
    VERCEL_DEPLOY_POLL_TIMEOUT,
    VERCEL_DEPLOY_POLL_INTERVAL,
    VERCEL_HTTP_TIMEOUT,
)

VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")


@dataclass
class VercelDeployResult:
    project_id: str
    project_name: str
    deployment_id: str
    ready_state: str  # "READY", "ERROR", "CANCELED", or a timeout marker
    url: Optional[str] = None  # e.g. "https://demo-xyz.vercel.app", set once READY
    error: Optional[str] = None


def _headers(token: Optional[str] = None) -> dict:
    t = token or VERCEL_TOKEN
    if not t:
        raise RuntimeError("VERCEL_TOKEN is not set in config/.env and no user vercel_token provided")
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _request(method: str, path: str, team_id: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    """Thin wrapper around requests that always scopes calls to the given
    team and raises with the response body on failure.
    """
    url = f"{VERCEL_API_BASE}{path}"
    params = kwargs.pop("params", {}) or {}
    if team_id:
        params["teamId"] = team_id
    resp = requests.request(method, url, headers=_headers(token), params=params, timeout=VERCEL_HTTP_TIMEOUT, **kwargs)
    return resp


def get_default_team_id(token: Optional[str] = None) -> str:
    """Look up the account's default team ID."""
    resp = requests.get(f"{VERCEL_API_BASE}/v2/user", headers=_headers(token), timeout=VERCEL_HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch Vercel user info ({resp.status_code}): {resp.text}")
    team_id = resp.json().get("user", {}).get("defaultTeamId") or ""
    return team_id


def set_project_env_var(
    project_id_or_name: str,
    key: str,
    value: str,
    team_id: Optional[str] = None,
    token: Optional[str] = None,
    target: list[str] = None,
) -> bool:
    """Inject an environment variable (e.g. NEXT_PUBLIC_API_URL) into a Vercel project."""
    target = target or ["production", "preview", "development"]
    body = [
        {
            "key": key,
            "value": value,
            "type": "plain",
            "target": target,
        }
    ]
    resp = _request("POST", f"/v10/projects/{project_id_or_name}/env", team_id, token=token, json=body)
    return resp.status_code in (200, 201)


def _create_or_get_project(project_name: str, owner: str, repo: str, team_id: str) -> str:
    """Create a Vercel project linked to the given GitHub repo.

    If a project with this name already exists (e.g. a retried deploy for
    the same lead/build_id), reuse it rather than failing — this endpoint
    returns 409 on a name collision, which we treat as "already set up."

    Returns the Vercel project ID.
    """
    body = {
        "name": project_name,
        "gitRepository": {"repo": f"{owner}/{repo}", "type": "github"},
    }
    resp = _request("POST", "/v11/projects", team_id, json=body)

    if resp.status_code == 409:
        # Project name taken — look it up instead of failing the whole deploy.
        lookup = _request("GET", f"/v9/projects/{project_name}", team_id)
        if lookup.status_code != 200:
            raise RuntimeError(
                f"Project '{project_name}' already exists but couldn't be fetched "
                f"({lookup.status_code}): {lookup.text}"
            )
        return lookup.json()["id"]

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to create Vercel project ({resp.status_code}): {resp.text}")

    return resp.json()["id"]


def _disable_deployment_protection(project_id: str, team_id: str) -> None:
    """Turn off Vercel Authentication (SSO wall) for this project.

    Without this, every deployment — including "production" — redirects
    unauthenticated visitors to a Vercel login page. That would make a demo
    link useless in an outreach email to someone with no Vercel account.
    """
    resp = _request("PATCH", f"/v9/projects/{project_id}", team_id, json={"ssoProtection": None})
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to disable deployment protection ({resp.status_code}): {resp.text}"
        )


def _trigger_deployment(project_name: str, owner: str, repo: str, branch: str, team_id: str) -> dict:
    """Trigger a production deployment from the linked GitHub repo's branch.

    skipAutoDetectionConfirmation=1 is required — without it, the API
    rejects the request asking for explicit projectSettings even though
    it's perfectly capable of auto-detecting the framework (confirmed via
    direct testing: the request 400s without this param, 200s with it).
    """
    body = {
        "name": project_name,
        "project": project_name,
        "target": "production",
        "gitSource": {"type": "github", "org": owner, "repo": repo, "ref": branch},
    }
    resp = _request(
        "POST", "/v13/deployments", team_id,
        params={"skipAutoDetectionConfirmation": "1"},
        json=body,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to trigger deployment ({resp.status_code}): {resp.text}")
    return resp.json()


def _poll_deployment(deployment_id: str, team_id: str, timeout: int = VERCEL_DEPLOY_POLL_TIMEOUT) -> dict:
    """Poll a deployment until it reaches a terminal readyState or times out."""
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        resp = _request("GET", f"/v13/deployments/{deployment_id}", team_id)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to poll deployment ({resp.status_code}): {resp.text}")
        last = resp.json()
        state = last.get("readyState")
        if state in ("READY", "ERROR", "CANCELED"):
            return last
        time.sleep(VERCEL_DEPLOY_POLL_INTERVAL)
    last["readyState"] = last.get("readyState", "TIMEOUT")
    return last


def deploy_to_vercel(
    owner: str,
    repo: str,
    project_name: Optional[str] = None,
    branch: str = "main",
    team_id: Optional[str] = None,
    vercel_token: Optional[str] = None,
) -> VercelDeployResult:
    """Link a GitHub repo to Vercel and deploy it, waiting for the result."""
    team_id = team_id or get_default_team_id(token=vercel_token)
    project_name = project_name or repo

    project_id = _create_or_get_project(project_name, owner, repo, team_id)
    _disable_deployment_protection(project_id, team_id)

    deployment = _trigger_deployment(project_name, owner, repo, branch, team_id)
    deployment_id = deployment["id"]

    final = _poll_deployment(deployment_id, team_id)
    ready_state = final.get("readyState", "UNKNOWN")

    url = None
    error = None
    if ready_state == "READY":
        raw_url = final.get("url")
        url = f"https://{raw_url}" if raw_url else None
    elif ready_state == "TIMEOUT":
        error = f"Deployment did not finish within {VERCEL_DEPLOY_POLL_TIMEOUT}s (still {final.get('readyState')})"
    else:
        error = final.get("errorMessage") or f"Deployment ended in state {ready_state}"

    return VercelDeployResult(
        project_id=project_id,
        project_name=project_name,
        deployment_id=deployment_id,
        ready_state=ready_state,
        url=url,
        error=error,
    )


# ---------------------------------------------------------------------------
# Test / CLI entrypoint
# ---------------------------------------------------------------------------

def _test():
    """End-to-end test: build a trivial project, push to GitHub, deploy to
    Vercel, and verify the live URL is BOTH reachable AND not gated behind
    a login wall (the exact failure mode discovered during development).

    Run with: python -m sandbox.vercel_deploy --test

    Note: creates real GitHub + Vercel resources you'll want to clean up
    afterward (gh repo delete needs delete_repo scope; Vercel project can be
    removed from the dashboard).
    """
    from sandbox import orchestrator, github_deploy

    print("\n" + "=" * 60)
    print("  VERCEL DEPLOY TEST")
    print("=" * 60)

    demo_project = {
        "title": "Hello Vercel Demo",
        "description": "A single static index.html file, deployed end to end.",
        "tech_stack": ["HTML"],
        "deliverable": "a single index.html file",
    }

    print("\n[1/4] Building via orchestrator...")
    state = orchestrator.start_build(demo_project, company="VercelProbeCo", max_attempts=2)
    assert state.stage == "success", f"Build failed: {state.result or state.error}"

    try:
        project_dir = orchestrator.export_build_output(state)
    finally:
        orchestrator.stop_build(state)
    print(f"      Exported to: {project_dir}")

    print("\n[2/4] Pushing to GitHub...")
    repo_result = github_deploy.deploy_to_github(
        project_dir, demo_project, company="VercelProbeCo", build_id=state.build_id
    )
    print(f"      Repo: {repo_result.repo_url}")

    print("\n[3/4] Deploying to Vercel...")
    vercel_result = deploy_to_vercel(owner=repo_result.owner, repo=repo_result.repo_name)
    print(f"      readyState={vercel_result.ready_state}")
    assert vercel_result.ready_state == "READY", f"Deploy did not succeed: {vercel_result.error}"
    print(f"      URL: {vercel_result.url}")

    print("\n[4/4] Verifying the URL is live AND publicly accessible (no SSO wall)...")
    resp = requests.get(vercel_result.url, timeout=15, allow_redirects=False)
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code} "
        f"(a 302 here would mean deployment protection is still on)"
    )
    print(f"      ✅ HTTP {resp.status_code}, {len(resp.text)} bytes, no auth redirect")

    print("\n" + "=" * 60)
    print("  ✅ TEST PASSED")
    print(f"  ⚠️  Clean up: GitHub repo {repo_result.repo_url}")
    print(f"  ⚠️  Clean up: Vercel project '{vercel_result.project_name}' (via dashboard)")
    print("=" * 60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        print("Usage:")
        print("  python -m sandbox.vercel_deploy --test   # end-to-end build + GitHub push + Vercel deploy")
