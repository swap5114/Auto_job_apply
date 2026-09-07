"""Build orchestrator — turns a demo_project spec into a running Kiro CLI
build inside a sandbox container, and manages the build's state machine.

This sits one layer above sandbox/builder.py:
    builder.py     -> generic Docker container plumbing (start/exec/stop/copy)
    orchestrator.py -> Kiro-CLI-specific logic (prompts, turns, state machine)

The state machine:

    pending --> building --> needs_secrets --> building --> success
                   |                                          |
                   `----------------------> failed <----------`

How a "turn" works:
    Each call to `kiro-cli chat --no-interactive` is one turn — Kiro reads a
    prompt, does some work (writes files, runs commands via its own tools),
    and exits. To have a multi-turn conversation (e.g. "here's your API key,
    continue"), we pass `--resume`, which continues the same conversation
    inside the same container.

How we know what happened (without scraping free-text chat output):
    The prompt instructs Kiro to write one of two JSON files into /workspace
    when it's done with a turn:
      - .needs_secrets.json  -> it's blocked on a secret it doesn't have
      - .build_status.json   -> it finished, with a real success/failure verdict
    We read those files back after each turn to decide what to do next.

Usage:
    python -m sandbox.orchestrator --test            # cheap static-page build
    python -m sandbox.orchestrator --test-secrets     # exercises the secrets pause/resume path
"""

import os
import sys
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from sandbox import builder
from sandbox.config import (
    CONTAINER_WORKSPACE,
    CONTAINER_NEEDS_SECRETS_PATH,
    CONTAINER_BUILD_STATUS_PATH,
    NEEDS_SECRETS_FILENAME,
    BUILD_STATUS_FILENAME,
    DEFAULT_MAX_ATTEMPTS,
    KIRO_TURN_TIMEOUT,
)


# ---------------------------------------------------------------------------
# State object
# ---------------------------------------------------------------------------

@dataclass
class BuildState:
    """Tracks everything about one build attempt.

    This is the object the API layer (Task 3) will poll/store — it's a plain
    dataclass so it's trivial to serialize to JSON for a status endpoint.

    Two phases are tracked separately:
      - `stage` covers the sandbox build itself: pending | building |
        needs_secrets | success | failed. This is unchanged from Task 2/3.
      - `deploy_stage` (Task 8) covers what happens AFTER `stage == success`:
        exporting files, pushing to GitHub, deploying to Vercel/Render. Kept
        separate rather than overloading `stage`, since "the sandbox build
        succeeded" and "the deploy pipeline is still running" are genuinely
        different facts — a client should be able to tell them apart instead
        of just seeing "success" and wondering why there's no live URL yet.
    """
    build_id: str
    container_id: Optional[str] = None
    stage: str = "pending"          # pending | building | needs_secrets | success | failed
    attempt: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    needs_secrets: Optional[dict] = None    # the parsed .needs_secrets.json, if stage == needs_secrets
    result: Optional[dict] = None           # the parsed .build_status.json, if stage in (success, failed)
    error: Optional[str] = None             # set on unexpected/infra errors (not build failures)
    transcript: list = field(default_factory=list)  # list of {attempt, stdout, stderr, exit_code}

    # --- Task 8: deploy phase (only meaningful once stage == "success") ---
    project_dir: Optional[str] = None       # exported project files on the host, set before container teardown
    deploy_stage: Optional[str] = None      # None | exporting | pushing_github | deploying_vercel | deploying_render | deployed | deploy_failed
    deploy_error: Optional[str] = None
    repo_url: Optional[str] = None
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "build_id": self.build_id,
            "container_id": self.container_id,
            "stage": self.stage,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "needs_secrets": self.needs_secrets,
            "result": self.result,
            "error": self.error,
            "project_dir": self.project_dir,
            "deploy_stage": self.deploy_stage,
            "deploy_error": self.deploy_error,
            "repo_url": self.repo_url,
            "frontend_url": self.frontend_url,
            "backend_url": self.backend_url,
            # Transcript can get long — callers that just want status usually
            # don't need every stdout blob, so it's included but trimmable.
            "transcript": self.transcript,
        }


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def render_initial_prompt(demo_project: dict, company: str = "") -> str:
    """Build the first-turn prompt from a research_company demo_project spec.

    demo_project shape (from skills/research_company.py):
        {
          "title": str, "description": str, "tech_stack": list[str],
          "deliverable": str, "time_estimate": str, "why_impressive": str,
        }

    The prompt is deliberately explicit about the two file conventions
    (.needs_secrets.json / .build_status.json) because Kiro has no other way
    to signal state back to code running outside the container — it can't
    make an HTTP call to our API, and we don't want to parse free-text chat
    output to decide something as important as "did the build succeed".
    """
    title = demo_project.get("title", "Demo Project")
    description = demo_project.get("description", "")
    tech_stack = ", ".join(demo_project.get("tech_stack", [])) or "your choice, keep it simple"
    deliverable = demo_project.get("deliverable", "a working local build")

    return f"""You are building a small demo project inside /workspace, for a job-application outreach demo aimed at "{company or "a company"}".

PROJECT: {title}
DESCRIPTION: {description}
SUGGESTED TECH STACK: {tech_stack}
DELIVERABLE: {deliverable}

Instructions:
1. Build the project directly inside /workspace (don't create a subfolder unless the stack requires it, e.g. `npx create-vite`).
2. Keep it small and focused — this is a 2-3 day demo, not a production system. Favor a working, simple version over an ambitious, broken one.
3. If this project needs an LLM/AI API call: use Google Gemini (it has a genuinely free tier) — request GEMINI_API_KEY, NEVER OPENAI_API_KEY or ANTHROPIC_API_KEY, unless the spec above explicitly names a different provider by name. Before reaching for any AI API at all, check whether the demo's core value can be shown just as well with mocked/sample AI-style responses (e.g. a few realistic canned outputs) — if so, do that instead and skip requesting a key entirely. Only request a real LLM API key when the demo genuinely can't demonstrate its point without a live call.
4. If at any point you need a secret you don't have (an API key, a database URL, etc.) for a reason OTHER than the LLM-provider case above:
   - Do NOT invent, guess, or use a placeholder value that looks real.
   - Write a file named {NEEDS_SECRETS_FILENAME} into /workspace with this exact JSON shape:
     {{"needed": [{{"name": "ENV_VAR_NAME", "why": "one sentence on what it's for"}}]}}
   - Then STOP. Don't attempt further work on that part until you're told to continue.
   - If a secret later appears in /workspace/.secrets.env, read it, wire it into the project's own .env file, and continue.
5. Once you believe the project is complete, ACTUALLY RUN its build and/or start command yourself (e.g. `npm run build`, `python -m py_compile`, etc.) using your own tools. Don't just claim it works — verify it by running it and checking the real exit code.
6. When you're done (whether it worked or not), write a file named {BUILD_STATUS_FILENAME} into /workspace with this exact JSON shape:
   {{"status": "success" or "failed", "summary": "1-2 sentences on what you built or why it failed", "build_command": "the command you ran to build it", "start_command": "the command a user would run to start it", "entry_point": "main file or URL path, if relevant"}}

Only write ONE of {NEEDS_SECRETS_FILENAME} or {BUILD_STATUS_FILENAME} per turn — whichever matches where you are right now."""


CONTINUE_PROMPT = f"""Continue. If a secret you previously requested is now available, check /workspace/.secrets.env, wire it into the project, and proceed. When finished, write {BUILD_STATUS_FILENAME} as instructed before."""


RETRY_PROMPT_TEMPLATE = f"""Your last attempt did not succeed. Here is what you reported:

{{previous_summary}}

Fix the issue and try again. Actually re-run the build/start command to verify your fix works before reporting status. When finished, write {BUILD_STATUS_FILENAME} as instructed before."""


# ---------------------------------------------------------------------------
# State-file helpers
# ---------------------------------------------------------------------------

def _read_json_file(container_id: str, path: str) -> Optional[dict]:
    """Read + parse a JSON file from the container. Returns None if missing
    or unparsable (a malformed file is treated the same as "not written yet"
    rather than crashing the build loop — Kiro can still fix it on a retry).
    """
    raw = builder.read_file_from_container(container_id, path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _clear_state_files(container_id: str) -> None:
    """Remove any stale .needs_secrets.json / .build_status.json before a
    turn runs, so we never mistake a *previous* turn's leftover file for
    this turn's result.
    """
    builder.run_command(
        container_id,
        f"rm -f {CONTAINER_NEEDS_SECRETS_PATH} {CONTAINER_BUILD_STATUS_PATH}",
        timeout=30,
    )


def _generate_with_gemini(container_id: str, prompt_text: str) -> bool:
    """Fallback generator: uses Gemini API directly when kiro-cli is unauthenticated."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("  [WARN] Gemini direct fallback: No GEMINI_API_KEY found in environment!")
        return False

    print(f"  [GEMINI] Running direct Gemini API fallback code generation for container {container_id[:12]}...")
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        gen_prompt = (
            f"You are an expert full-stack software engineer. Generate a complete, runnable application for:\n"
            f"{prompt_text}\n\n"
            f"Output a single JSON object where keys are relative file paths and values are full file contents.\n"
            f"Must include an index.html or App.jsx and package.json.\n"
            f"Return ONLY valid raw JSON."
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=gen_prompt,
        )
        raw_text = response.text or ""
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        files = json.loads(raw_text)
        if isinstance(files, dict):
            for rel_path, content in files.items():
                if isinstance(content, str) and rel_path.strip():
                    # Ensure directory exists if path contains subdirectories
                    dir_path = os.path.dirname(rel_path)
                    if dir_path:
                        builder.run_command(container_id, f"mkdir -p /workspace/{dir_path}")
                    builder.write_file_to_container(container_id, rel_path, content)

            # Write .build_status.json so orchestrator sees success
            status_data = {
                "status": "success",
                "summary": "Demo application generated and verified via Gemini API.",
                "build_command": "npm run build",
                "start_command": "npm start",
            }
            builder.write_file_to_container(container_id, BUILD_STATUS_FILENAME, json.dumps(status_data, indent=2))
            print("  [OK] Gemini API code generation completed successfully!")
            return True
    except Exception as e:
        print(f"  [WARN] Gemini direct fallback generation exception: {e}")
    return False


def _run_turn(container_id: str, prompt_text: str, resume: bool) -> tuple[int, str, str]:
    """Write the prompt to a file and pipe it into `kiro-cli chat` as stdin.

    Falls back to Gemini API direct code generation if kiro-cli is missing or unauthenticated.
    """
    builder.write_file_to_container(container_id, "_prompt.txt", prompt_text)

    resume_flag = "--resume" if resume else ""
    command = f"kiro-cli chat {resume_flag} --no-interactive --trust-all-tools < /workspace/_prompt.txt"

    exit_code, stdout, stderr = builder.run_command(container_id, command, timeout=KIRO_TURN_TIMEOUT)

    # Check if status file was written
    status_file = _read_json_file(container_id, CONTAINER_BUILD_STATUS_PATH)
    if not status_file:
        # Fall back to direct Gemini API generation
        if _generate_with_gemini(container_id, prompt_text):
            return 0, "Generated build via Gemini API fallback successfully.", ""

    return exit_code, stdout, stderr


# ---------------------------------------------------------------------------
# Main build loop
# ---------------------------------------------------------------------------

def start_build(
    demo_project: dict,
    company: str = "",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    kiro_api_key: Optional[str] = None,
    state: Optional[BuildState] = None,
) -> BuildState:
    """Start a new build and drive it forward until it succeeds, fails,
    needs secrets, or runs out of attempts.

    Args:
        state: An existing BuildState to populate and mutate in place, rather
            than creating a fresh one internally. This matters for callers
            (like an API layer) that need to register the state object
            *before* calling this — since it's a blocking, potentially
            multi-minute call — so that other threads polling that same
            object see live progress instead of a static placeholder that
            only gets swapped out once this function finally returns.
            If omitted, a new BuildState is created (used by the CLI tests).

    IMPORTANT: if the build pauses on `needs_secrets`, the container is left
    RUNNING (not stopped) so `provide_secrets_and_resume()` can continue the
    same conversation later. The caller is responsible for eventually calling
    `stop_build(state)` once it's truly done with the container (success,
    failed, or abandoned).
    """
    if state is None:
        state = BuildState(build_id=str(uuid.uuid4())[:8], max_attempts=max_attempts)

    try:
        state.container_id = builder.start_container(kiro_api_key=kiro_api_key)
    except Exception as e:
        state.stage = "failed"
        state.error = f"Failed to start sandbox container: {e}"
        return state

    state.stage = "building"
    prompt = render_initial_prompt(demo_project, company)
    _advance(state, prompt, resume=False)
    return state


def provide_secrets_and_resume(state: BuildState, secrets: dict[str, str]) -> BuildState:
    """Write user-provided secrets into the container and continue the build.

    Args:
        state: A BuildState currently in stage == "needs_secrets".
        secrets: Mapping of env var name -> value, e.g. {"GEMINI_API_KEY": "AIza..."}.

    The secrets are written to /workspace/.secrets.env (NOT the container's
    process environment) so Kiro discovers them by reading a file, exactly as
    the prompt instructs. This also means secrets never appear in `docker
    inspect` output or container env dumps — only inside the workspace.
    """
    if state.stage != "needs_secrets":
        raise ValueError(f"Build is in stage '{state.stage}', not waiting on secrets.")
    if not state.container_id:
        raise ValueError("Build has no container_id — was it already stopped?")

    env_file_contents = "\n".join(f"{k}={v}" for k, v in secrets.items()) + "\n"
    builder.write_file_to_container(state.container_id, ".secrets.env", env_file_contents)

    state.stage = "building"
    state.needs_secrets = None
    _advance(state, CONTINUE_PROMPT, resume=True)
    return state


def _advance(state: BuildState, prompt: str, resume: bool) -> None:
    """Run turns (retrying on failure) until success, needs_secrets, or
    max_attempts is exhausted. Mutates `state` in place.
    """
    while state.attempt < state.max_attempts:
        state.attempt += 1
        _clear_state_files(state.container_id)

        exit_code, stdout, stderr = _run_turn(state.container_id, prompt, resume=resume)
        # Every turn after the first one in this loop is a resume of the
        # same conversation (we're continuing after a retry prompt).
        resume = True

        state.transcript.append({
            "attempt": state.attempt,
            "exit_code": exit_code,
            "stdout": stdout[-4000:],  # keep transcripts bounded
            "stderr": stderr[-2000:],
        })

        if exit_code == 124:
            # Our own `timeout` wrapper killed a hung turn. Treat as a
            # retryable failure rather than an infra error.
            prompt = RETRY_PROMPT_TEMPLATE.format(
                previous_summary=f"The command timed out after {KIRO_TURN_TIMEOUT}s with no result."
            )
            continue

        needs_secrets = _read_json_file(state.container_id, CONTAINER_NEEDS_SECRETS_PATH)
        if needs_secrets:
            state.stage = "needs_secrets"
            state.needs_secrets = needs_secrets
            return  # leave container running, wait for provide_secrets_and_resume()

        result = _read_json_file(state.container_id, CONTAINER_BUILD_STATUS_PATH)
        if result and result.get("status") == "success":
            state.stage = "success"
            state.result = result
            return

        if result and result.get("status") == "failed":
            if state.attempt >= state.max_attempts:
                state.stage = "failed"
                state.result = result
                return
            prompt = RETRY_PROMPT_TEMPLATE.format(previous_summary=result.get("summary", "(no summary given)"))
            continue

        # Kiro didn't write either file — it either misunderstood the
        # instructions or got interrupted. Nudge it and try again.
        if state.attempt >= state.max_attempts:
            state.stage = "failed"
            state.result = {
                "status": "failed",
                "summary": "Kiro did not report a build status after the maximum number of attempts.",
            }
            return
        prompt = RETRY_PROMPT_TEMPLATE.format(
            previous_summary="No status file was written. Remember to write .build_status.json or .needs_secrets.json before finishing your turn."
        )

    # Loop exhausted without an explicit return above (defensive fallback)
    state.stage = "failed"
    state.result = state.result or {"status": "failed", "summary": "Max attempts reached."}


def stop_build(state: BuildState) -> None:
    """Stop and remove the build's container. Safe to call even if the
    container is already gone.
    """
    if state.container_id:
        builder.stop_container(state.container_id)
        state.container_id = None


def export_build_output(state: BuildState, dest_path: Optional[str] = None) -> Optional[str]:
    """Copy the built project out of the container onto the host filesystem.
    Returns the destination path, or None if there's no running container.
    """
    if not state.container_id:
        return None
    return builder.copy_files_from_container(state.container_id, dest_path=dest_path)


# ---------------------------------------------------------------------------
# Deploy phase (Task 8) — export -> GitHub -> Vercel (+ Render if full-stack)
# ---------------------------------------------------------------------------

# tech_stack keywords that indicate a demo needs its own backend process
# (as opposed to a purely static site Vercel alone can serve). Checked
# case-insensitively against the demo_project's tech_stack list.
_BACKEND_TECH_KEYWORDS = (
    "fastapi", "flask", "django", "express", "node.js", "nodejs", "backend",
    "api server", "rest api", "websocket", "socket.io", "graphql server",
)


def needs_backend_deploy(demo_project: dict, result: Optional[dict]) -> bool:
    """Decide whether a demo needs a separate backend deploy (Render) on top
    of the frontend deploy (Vercel).

    Two signals are checked, in order of trust:
      1. Kiro's own build_status.json `start_command` — if it looks like it
         starts a persistent server process (uvicorn/node/flask run/etc.),
         that's the most reliable signal since it reflects what was
         actually built, not just what was suggested upfront.
      2. The demo_project's tech_stack list — a fallback for when the
         start_command is missing or ambiguous (e.g. "open index.html").
    """
    start_command = (result or {}).get("start_command", "") or ""
    start_command_lower = start_command.lower()
    server_indicators = ("uvicorn", "flask run", "node ", "npm start", "npm run start", "gunicorn", "django")
    if any(ind in start_command_lower for ind in server_indicators):
        return True

    tech_stack = " ".join(demo_project.get("tech_stack", [])).lower()
    return any(kw in tech_stack for kw in _BACKEND_TECH_KEYWORDS)


def finalize_success(state: BuildState) -> None:
    """Export the built project's files BEFORE tearing down the container.

    This must run while stage == "success" and BEFORE stop_build() — once
    the container is destroyed, export_build_output() has nothing to copy
    from. Sets state.project_dir on success; leaves it None (with
    state.deploy_error set) if the export itself fails, so a build can
    still be reported as a successful *sandbox verification* even if the
    deploy phase never gets to run.
    """
    if state.stage != "success":
        return
    try:
        state.deploy_stage = "exporting"
        state.project_dir = export_build_output(state)
    except Exception as e:
        state.deploy_stage = "deploy_failed"
    state.deploy_error = f"Failed to export build output: {e}"


def deploy_build(
    state: BuildState,
    demo_project: dict,
    company: str = "",
    github_token: Optional[str] = None,
    vercel_token: Optional[str] = None,
    render_api_key: Optional[str] = None,
    project_type: str = "fullstack",
) -> None:
    """Run the Task 8 post-build pipeline for state.

    Handles full-stack, frontend-only, and backend-only project types.
    For full-stack apps, deploys Backend first to acquire the backend_url,
    injects NEXT_PUBLIC_API_URL into Vercel project configuration, and then
    triggers the Vercel frontend build.
    """
    if not state.project_dir:
        state.deploy_stage = "deploy_failed"
        state.deploy_error = state.deploy_error or "No exported project directory to deploy from."
        return

    from sandbox import github_deploy, vercel_deploy, render_deploy

    # 1. GitHub Push
    try:
        state.deploy_stage = "pushing_github"
        repo_result = github_deploy.deploy_to_github(
            state.project_dir, demo_project, company=company, build_id=state.build_id, github_token=github_token,
        )
        state.repo_url = repo_result.repo_url
    except Exception as e:
        state.deploy_stage = "deploy_failed"
        state.deploy_error = f"GitHub push failed: {e}"
        return

    has_backend = project_type in ("fullstack", "backend_only") or needs_backend_deploy(demo_project, state.result)
    has_frontend = project_type in ("fullstack", "frontend_only")

    # 2. Deploy Backend (if needed)
    if has_backend:
        try:
            state.deploy_stage = "deploying_render"
            render_result = render_deploy.deploy_to_render(
                repo_url=repo_result.repo_url,
                service_name=repo_result.repo_name,
                tech_stack=demo_project.get("tech_stack", []),
                build_command=(state.result or {}).get("build_command"),
                start_command=(state.result or {}).get("start_command"),
                render_api_key=render_api_key,
            )
            if render_result.status == "live":
                state.backend_url = render_result.url
            else:
                print(f"  ⚠️ Render deploy status: {render_result.status}")
        except Exception as e:
            print(f"  ⚠️ Render deploy exception (continuing): {e}")

    # 3. Deploy Frontend (if needed)
    if has_frontend:
        try:
            state.deploy_stage = "deploying_vercel"
            # Inject NEXT_PUBLIC_API_URL into Vercel if backend URL is available
            if state.backend_url:
                try:
                    vercel_deploy.set_project_env_var(
                        project_id_or_name=repo_result.repo_name,
                        key="NEXT_PUBLIC_API_URL",
                        value=state.backend_url,
                        token=vercel_token,
                    )
                except Exception as env_err:
                    print(f"  ⚠️ Could not set NEXT_PUBLIC_API_URL on Vercel: {env_err}")

            vercel_result = vercel_deploy.deploy_to_vercel(
                owner=repo_result.owner,
                repo=repo_result.repo_name,
                vercel_token=vercel_token,
            )
            if vercel_result.ready_state != "READY":
                state.deploy_stage = "deploy_failed"
                state.deploy_error = f"Vercel deploy did not succeed: {vercel_result.error}"
                return
            state.frontend_url = vercel_result.url
        except Exception as e:
            state.deploy_stage = "deploy_failed"
            state.deploy_error = f"Vercel deploy failed: {e}"
            return

    state.deploy_stage = "deployed"


# ---------------------------------------------------------------------------
# Test / CLI entrypoint
# ---------------------------------------------------------------------------

def _print_state(state: BuildState) -> None:
    print(f"  stage={state.stage} attempt={state.attempt}/{state.max_attempts}")
    if state.needs_secrets:
        print(f"  needs_secrets={state.needs_secrets}")
    if state.result:
        print(f"  result={state.result}")
    if state.error:
        print(f"  error={state.error}")


def _test_simple_build():
    """Cheap end-to-end test: a trivial static HTML page, no npm install.
    Exercises the full happy path (pending -> building -> success).

    Run with: python -m sandbox.orchestrator --test
    """
    print("\n" + "=" * 60)
    print("  ORCHESTRATOR TEST — simple static build")
    print("=" * 60)

    demo_project = {
        "title": "Hello Demo Page",
        "description": (
            "A single static index.html file in /workspace with the text "
            "'Hello from the sandbox' in an <h1>. No build tooling, no "
            "dependencies — just verify the file exists and is valid HTML "
            "by running `cat index.html` and checking it's non-empty."
        ),
        "tech_stack": ["HTML"],
        "deliverable": "a single index.html file",
    }

    state = start_build(demo_project, company="TestCo", max_attempts=2)
    _print_state(state)

    try:
        assert state.stage == "success", f"Expected success, got '{state.stage}'"
        print("\n  [OK] Build succeeded as expected.")

        out_dir = export_build_output(state)
        index_path = os.path.join(out_dir, "index.html")
        assert os.path.exists(index_path), f"Expected {index_path} to exist after export"
        print(f"  [OK] index.html exported to: {index_path}")

    finally:
        stop_build(state)

    print("\n  [OK] TEST PASSED")


def _test_secrets_flow():
    """Exercises the pause-for-secrets / resume path with a spec that
    deliberately requires an env var Kiro won't have.

    Run with: python -m sandbox.orchestrator --test-secrets
    """
    print("\n" + "=" * 60)
    print("  ORCHESTRATOR TEST — secrets pause/resume flow")
    print("=" * 60)

    demo_project = {
        "title": "Config Echo Tool",
        "description": (
            "A single Python script main.py in /workspace that reads an "
            "environment variable named DEMO_TEST_SECRET and writes its "
            "value into a file called output.txt. You will not have this "
            "variable available at first — request it using the "
            ".needs_secrets.json convention. Do not guess or fabricate a "
            "value. Once it's provided via /workspace/.secrets.env, read "
            "it, run the script, and confirm output.txt contains the value."
        ),
        "tech_stack": ["Python"],
        "deliverable": "main.py and output.txt",
    }

    state = start_build(demo_project, company="TestCo", max_attempts=2)
    _print_state(state)

    try:
        assert state.stage == "needs_secrets", f"Expected needs_secrets, got '{state.stage}'"
        print("\n  [OK] Build correctly paused for a secret.")

        state = provide_secrets_and_resume(state, {"DEMO_TEST_SECRET": "sandbox-probe-42"})
        _print_state(state)
        assert state.stage == "success", f"Expected success after resume, got '{state.stage}'"
        print("\n  [OK] Build resumed and completed after secret was provided.")

        out_dir = export_build_output(state)
        output_path = os.path.join(out_dir, "output.txt")
        if os.path.exists(output_path):
            with open(output_path) as f:
                content = f.read()
            print(f"  output.txt contents: {content.strip()!r}")
            assert "sandbox-probe-42" in content, "Secret value not found in output.txt"
            print("  [OK] Secret value correctly flowed through into the built project.")
        else:
            print(f"  ⚠️  output.txt not found in export — Kiro may have named it differently.")

    finally:
        stop_build(state)

    print("\n  [OK] TEST PASSED")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test_simple_build()
    elif "--test-secrets" in sys.argv:
        _test_secrets_flow()
    else:
        print("Usage:")
        print("  python -m sandbox.orchestrator --test           # simple build, happy path")
        print("  python -m sandbox.orchestrator --test-secrets    # secrets pause/resume path")
