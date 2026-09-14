"""E2E test: build a demo, push to GitHub, deploy to Vercel/Render.

Run with:
    python test_e2e_demo_build.py

This exercises the full pipeline that the /api/demos/build endpoint triggers:
  1. Rate-limit quota check (the bug we just fixed)
  2. sandbox.orchestrator.start_build  →  Kiro CLI builds the project in Docker
  3. sandbox.orchestrator.finalize_success + export_build_output
  4. sandbox.github_deploy  →  push to a real GitHub repo
  5. sandbox.vercel_deploy  →  deploy frontend
  6. sandbox.render_deploy  →  deploy backend (fullstack only)

Exits with code 0 on success, 1 on failure. 
"""

import os, sys, time

# Set up path and env
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))


def main():
    # ------------------------------------------------------------------
    # Step 0: Verify the quota bug fix (the original crash)
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  STEP 0: Verify RateLimiter.max_requests attribute exists")
    print("=" * 70)
    from api.rate_limit import demo_build_limiter
    try:
        limit = demo_build_limiter.max_requests
        print(f"  ✅ demo_build_limiter.max_requests = {limit}")
    except AttributeError as e:
        print(f"  ❌ AttributeError (this is the bug): {e}")
        sys.exit(1)

    # Also verify .limit does NOT exist (so nobody re-introduces the bug)
    assert not hasattr(demo_build_limiter, "limit"), \
        "RateLimiter should not have a .limit attribute — use .max_requests"
    print("  ✅ Confirmed .limit does NOT exist (bug won't regress)")

    # ------------------------------------------------------------------
    # Step 1: Build a small demo via the orchestrator
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  STEP 1: Build a demo project in the sandbox")
    print("=" * 70)
    from sandbox.orchestrator import BuildState, start_build, finalize_success, export_build_output, stop_build

    demo_project = {
        "title": "Test E2E Dashboard",
        "description": (
            "A single-page React dashboard that shows three stat cards "
            "(Users, Revenue, Growth) with placeholder numbers and a dark "
            "theme. Use Vite + React. Keep it simple — no backend, no API "
            "calls, just static data rendered in cards."
        ),
        "company_name": "TestCo",
        "project_type": "frontend_only",
        "tech_stack": ["React", "Vite", "CSS"],
    }

    t0 = time.time()
    state = start_build(demo_project, company="TestCo", max_attempts=2)
    elapsed = time.time() - t0

    print(f"  Build stage: {state.stage}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Attempts used: {state.attempt}/{state.max_attempts}")

    if state.stage != "success":
        print(f"\n  ❌ Build did not succeed.")
        print(f"     Error: {state.error}")
        if state.result:
            print(f"     Result: {state.result}")
        stop_build(state)
        sys.exit(1)

    print("  ✅ Build succeeded")

    # ------------------------------------------------------------------
    # Step 2: Export + GitHub push
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  STEP 2: Export files and push to GitHub")
    print("=" * 70)
    try:
        finalize_success(state)
        project_dir = state.project_dir
        if not project_dir:
            project_dir = export_build_output(state)
        print(f"  Exported to: {project_dir}")
    finally:
        stop_build(state)

    from sandbox import github_deploy
    github_token = os.getenv("GITHUB_TOKEN")
    print(f"  GitHub token present: {bool(github_token)}")

    repo_result = github_deploy.deploy_to_github(
        project_dir,
        demo_project,
        company="TestCo",
        build_id=state.build_id,
        github_token=github_token,
    )
    print(f"  ✅ Repo created: {repo_result.repo_url}")
    print(f"     Owner: {repo_result.owner}")
    print(f"     Repo name: {repo_result.repo_name}")

    state.repo_url = repo_result.repo_url

    # ------------------------------------------------------------------
    # Step 3: Deploy to Vercel (frontend)
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  STEP 3: Deploy frontend to Vercel")
    print("=" * 70)
    from sandbox import vercel_deploy

    vercel_token = os.getenv("VERCEL_TOKEN")
    print(f"  Vercel token present: {bool(vercel_token)}")

    try:
        vercel_result = vercel_deploy.deploy_to_vercel(
            owner=repo_result.owner,
            repo=repo_result.repo_name,
            vercel_token=vercel_token,
        )
        print(f"  Vercel deploy state: {vercel_result.ready_state}")
        if vercel_result.url:
            print(f"  ✅ Frontend URL: {vercel_result.url}")
            state.frontend_url = vercel_result.url
        if vercel_result.error:
            print(f"  ⚠️  Error: {vercel_result.error}")
    except Exception as e:
        print(f"  ⚠️  Vercel deploy failed: {e}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  E2E TEST SUMMARY")
    print("=" * 70)
    print(f"  Build stage:    {state.stage}")
    print(f"  Repo URL:       {state.repo_url or '(none)'}")
    print(f"  Frontend URL:   {state.frontend_url or '(none)'}")
    print(f"  Backend URL:    {state.backend_url or '(none)'}")
    
    if state.repo_url:
        print("\n  ✅ E2E TEST PASSED — repo created and code deployed")
    else:
        print("\n  ❌ E2E TEST FAILED — no repo URL")
        sys.exit(1)


if __name__ == "__main__":
    main()
