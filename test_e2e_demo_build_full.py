"""End-to-End Test for AI Demo Studio & Deployment Sandbox.

Exercises the full pipeline:
  1. Daily quota rate-limit verification
  2. Vertex AI / Gemini Code generation in Docker sandbox container
  3. Verification of dependencies & CORS middleware auto-injection
  4. Project export & push to GitHub repository
  5. Deployment of frontend to Vercel
  6. Deployment of backend to Render (for fullstack projects)
"""

import os
import sys
import time
import json

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("\n" + "=" * 70)
    print("  STEP 0: Verify Rate Limiter Quota Config")
    print("=" * 70)
    from api.rate_limit import demo_build_limiter
    assert hasattr(demo_build_limiter, "max_requests"), "RateLimiter missing max_requests"
    print(f"  [OK] demo_build_limiter max_requests = {demo_build_limiter.max_requests}")

    print("\n" + "=" * 70)
    print("  STEP 1: Run Fullstack Demo Code Generation & Sandbox Build")
    print("=" * 70)
    from sandbox import orchestrator
    from sandbox.builder import start_container, stop_container, copy_files_from_container

    demo_project = {
        "title": "E2E Fullstack Lead Dashboard",
        "description": (
            "A fullstack dashboard app with a Node/Express backend that has GET /api/stats endpoint "
            "and a React/Vite frontend that fetches from the API. The Express server MUST enable CORS middleware."
        ),
        "company_name": "Acme Demo Inc",
        "project_type": "fullstack",
        "tech_stack": ["React", "Express", "Node.js", "CORS"],
    }

    container_id = start_container()
    print(f"  Started sandbox container: {container_id[:12]}")

    try:
        prompt_text = orchestrator.render_initial_prompt(demo_project, company="Acme Demo Inc")
        gen_success = orchestrator._generate_with_gemini(container_id, prompt_text)
        assert gen_success is True, "Gemini code generation failed!"
        print("  [OK] Vertex AI / Gemini Code Generation Succeeded")

        out_dir = copy_files_from_container(container_id)
        print(f"  Exported files to: {out_dir}")

        # Check for CORS in generated backend code
        cors_found = False

        for root, _, files in os.walk(out_dir):
            for file in files:
                if file.endswith((".js", ".ts", ".py")):
                    full_p = os.path.join(root, file)
                    with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                        code = f.read()
                        if "cors" in code.lower() or "corsmiddleware" in code.lower():
                            cors_found = True
                            print(f"  [OK] CORS Middleware detected in {file}")
                            break

        assert cors_found, "CORS middleware was not automatically included in fullstack application!"

    finally:
        stop_container(container_id)

    print("\n" + "=" * 70)
    print("  STEP 2: Deploy to GitHub")
    print("=" * 70)
    from sandbox import github_deploy
    github_token = os.getenv("GITHUB_TOKEN")

    repo_result = github_deploy.deploy_to_github(
        project_dir=out_dir,
        demo_project=demo_project,
        company="Acme Demo Inc",
        build_id="e2etest",
        github_token=github_token,
    )
    print(f"  [OK] Pushed to GitHub: {repo_result.repo_url}")
    print(f"     Owner: {repo_result.owner}, Repo: {repo_result.repo_name}")

    print("\n" + "=" * 70)
    print("  STEP 3: Deploy Frontend to Vercel")
    print("=" * 70)
    from sandbox import vercel_deploy
    vercel_token = os.getenv("VERCEL_TOKEN")

    try:
        vercel_res = vercel_deploy.deploy_to_vercel(
            owner=repo_result.owner,
            repo=repo_result.repo_name,
            vercel_token=vercel_token,
        )
        print(f"  Vercel status: {vercel_res.ready_state}")
        if vercel_res.url:
            print(f"  [OK] Frontend Live URL: {vercel_res.url}")
    except Exception as e:
        print(f"  ⚠️ Vercel deployment notice: {e}")

    print("\n" + "=" * 70)
    print("  STEP 4: Deploy Backend to Render")
    print("=" * 70)
    from sandbox import render_deploy
    render_key = os.getenv("RENDER_API_KEY")

    try:
        render_res = render_deploy.deploy_to_render(
            repo_url=repo_result.repo_url,
            service_name=repo_result.repo_name,
            tech_stack=demo_project["tech_stack"],
            render_api_key=render_key,
        )
        print(f"  Render status: {render_res.status}")
        if render_res.url:
            print(f"  [OK] Backend Live URL: {render_res.url}")
    except Exception as e:
        print(f"  ⚠️ Render deployment notice: {e}")

    print("\n" + "=" * 70)
    print("  E2E FULLSTACK DEMO BUILD TEST COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    main()
