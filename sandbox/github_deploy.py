"""GitHub deploy — pushes an exported demo project to a fresh GitHub repo.

This is the bridge between "build finished inside a sandbox container" and
"there's a real GitHub repo Vercel/Render can deploy from." It operates on
the directory sandbox/builder.py already copied out of the container (via
copy_files_from_container / orchestrator.export_build_output) — everything
here runs on your host machine, not inside Docker.

Uses the `gh` CLI (already authenticated on this machine) rather than the
GitHub REST API directly, since `gh repo create --source=. --push` already
handles repo creation, remote setup, and push in one call.

Usage:
    python -m sandbox.github_deploy --test

Safety:
    Internal convention files (.secrets.env, .build_status.json,
    .needs_secrets.json, _prompt.txt) are stripped from the export directory
    BEFORE `git init` ever runs, and also gitignored as a second line of
    defense. .secrets.env in particular can hold real user-provided API
    keys — it must never reach a repo, especially a public one.
"""

import os
import re
import sys
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from sandbox.config import (
    DEMO_REPO_PREFIX,
    DEMO_REPO_PRIVATE,
    INTERNAL_FILES_TO_STRIP,
    GIT_COMMAND_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass
class DeployRepoResult:
    repo_name: str
    repo_url: str
    owner: str
    branch: str = "main"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Turn a company/project name into a URL/repo-safe slug.

    "MSPilot, Inc." -> "mspilot-inc"
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "project"


def _run(cmd: list[str], cwd: str, timeout: int = GIT_COMMAND_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a host-machine subprocess with list-form args (no shell=True),
    so nothing in a company name, project title, etc. can be interpreted as
    shell syntax. Raises with full stderr on failure rather than swallowing it.
    """
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({' '.join(cmd)}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result


def strip_internal_files(project_dir: str) -> list[str]:
    """Delete our internal convention files from the exported project dir.

    Returns the list of files actually removed (useful for logging/tests —
    confirms the safety check did something rather than silently no-op'ing
    because paths were wrong).
    """
    removed = []
    for name in INTERNAL_FILES_TO_STRIP:
        path = os.path.join(project_dir, name)
        if os.path.exists(path):
            os.remove(path)
            removed.append(name)
    return removed


# Heavy/generated directories that should never be committed — deploy
# platforms (Vercel/Render) run their own install step, so committing
# node_modules etc. only bloats the repo and slows down pushes.
_GITIGNORE_DIRS = [
    "node_modules/", "__pycache__/", ".venv/", "venv/", "dist/", "build/",
    ".next/", ".cache/", ".pytest_cache/", "*.pyc",
]


def write_gitignore(project_dir: str) -> None:
    """Write (or append to) a .gitignore covering both generated build
    artifacts and our internal state files, as a second line of defense
    beyond strip_internal_files() actually deleting them.
    """
    gitignore_path = os.path.join(project_dir, ".gitignore")
    existing = ""
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            existing = f.read()

    lines_to_add = [l for l in (_GITIGNORE_DIRS + INTERNAL_FILES_TO_STRIP) if l not in existing]
    if not lines_to_add:
        return

    with open(gitignore_path, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n# --- added by sandbox/github_deploy.py ---\n")
        f.write("\n".join(lines_to_add) + "\n")


def write_readme(project_dir: str, demo_project: dict, company: str = "") -> None:
    """Write a README so the repo makes sense to anyone (including the
    hiring manager) who clicks through from the outreach email. Does not
    overwrite an existing README Kiro may have already written — appends
    a context header instead, since Kiro's own README (if any) likely
    describes the project's usage in more detail than we know here.
    """
    readme_path = os.path.join(project_dir, "README.md")
    title = demo_project.get("title", "Demo Project")
    description = demo_project.get("description", "")
    tech_stack = ", ".join(demo_project.get("tech_stack", []))

    header = f"""# {title}

{description}

**Tech stack:** {tech_stack or "n/a"}

*This demo was built to accompany an outreach message{f" to {company}" if company else ""} — generated and verified with [Kiro CLI](https://kiro.dev/cli/) inside an isolated sandbox.*

---

"""
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            existing = f.read()
        # Don't duplicate the header if this repo dir was already deployed once
        if title not in existing.splitlines()[0:1]:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(header + existing)
    else:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(header)


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def deploy_to_github(
    project_dir: str,
    demo_project: dict,
    company: str = "",
    build_id: str = "",
    private: Optional[bool] = None,
) -> DeployRepoResult:
    """Push an exported demo project directory to a brand-new GitHub repo.

    Args:
        project_dir: Local path to the exported project (from
            orchestrator.export_build_output()).
        demo_project: The same spec used to build it — used for the repo
            name and README.
        company: Company name, folded into the repo name and README.
        build_id: The build's short ID, appended to the repo name to avoid
            collisions if the same company gets demoed twice.
        private: Override DEMO_REPO_PRIVATE for this call.

    Returns:
        DeployRepoResult with the repo's URL, owner, and name.

    Safety: strips internal convention files (.secrets.env, etc.) BEFORE
    `git init`, so they can never end up in git history even if .gitignore
    were somehow wrong or bypassed.
    """
    if not os.path.isdir(project_dir):
        raise ValueError(f"project_dir does not exist: {project_dir}")

    removed = strip_internal_files(project_dir)
    if removed:
        print(f"  Stripped internal files before git init: {removed}")

    write_gitignore(project_dir)
    write_readme(project_dir, demo_project, company)

    # Repo name: <prefix><company-slug>-<build_id>, e.g. "demo-mspilot-c02a129c"
    company_slug = _slugify(company or demo_project.get("title", "project"))
    repo_name = f"{DEMO_REPO_PREFIX}{company_slug}"
    if build_id:
        repo_name = f"{repo_name}-{build_id}"

    is_private = DEMO_REPO_PRIVATE if private is None else private

    # A previous failed attempt (network blip, etc.) may have left a .git dir
    # from a partial run. We fully control repo creation ourselves — start
    # clean rather than trying to reconcile a possibly-broken prior state.
    git_dir = os.path.join(project_dir, ".git")
    if os.path.isdir(git_dir):
        shutil.rmtree(git_dir)

    _run(["git", "init", "-q"], cwd=project_dir)
    _run(["git", "-c", "user.name=autoapply-bot", "-c", "user.email=autoapply-bot@localhost",
          "add", "-A"], cwd=project_dir)
    _run(["git", "-c", "user.name=autoapply-bot", "-c", "user.email=autoapply-bot@localhost",
          "commit", "-q", "-m", f"Initial commit — {demo_project.get('title', 'demo project')}"],
         cwd=project_dir)
    _run(["git", "branch", "-M", "main"], cwd=project_dir)

    visibility_flag = "--private" if is_private else "--public"
    description = demo_project.get("description", "")[:350]  # GitHub caps repo descriptions

    create_result = _run(
        ["gh", "repo", "create", repo_name, visibility_flag,
         "--source=.", "--push", "--description", description],
        cwd=project_dir,
        timeout=GIT_COMMAND_TIMEOUT,
    )

    # `gh repo create` prints "https://github.com/<owner>/<repo>" on its
    # first output line — parse that rather than making a second API call.
    repo_url = ""
    for line in create_result.stdout.splitlines():
        if line.strip().startswith("https://github.com/"):
            repo_url = line.strip()
            break

    if not repo_url:
        # Fall back to asking gh directly if the output format ever changes.
        view_result = _run(["gh", "repo", "view", repo_name, "--json", "url", "-q", ".url"], cwd=project_dir)
        repo_url = view_result.stdout.strip()

    owner = repo_url.rstrip("/").split("/")[-2] if repo_url else ""

    print(f"  ✅ Pushed to {repo_url}")
    return DeployRepoResult(repo_name=repo_name, repo_url=repo_url, owner=owner)


# ---------------------------------------------------------------------------
# Test / CLI entrypoint
# ---------------------------------------------------------------------------

def _test():
    """End-to-end test: build a trivial project via the orchestrator, export
    it, deploy it to a real (throwaway) GitHub repo, and verify the internal
    files never made it into git history.

    Run with: python -m sandbox.github_deploy --test

    Note: this creates a REAL public repo on your GitHub account. You'll
    need to delete it manually afterward (gh doesn't have delete_repo scope
    authorized on this machine yet — see `gh auth refresh -s delete_repo`).
    """
    from sandbox import orchestrator

    print("\n" + "=" * 60)
    print("  GITHUB DEPLOY TEST")
    print("=" * 60)

    demo_project = {
        "title": "Hello Demo Page",
        "description": "A single static index.html file, built and verified inside a sandbox.",
        "tech_stack": ["HTML"],
        "deliverable": "a single index.html file",
    }

    print("\n[1/4] Building a small test project via the orchestrator...")
    state = orchestrator.start_build(demo_project, company="ProbeCo", max_attempts=2)
    assert state.stage == "success", f"Build did not succeed: {state.result or state.error}"
    print(f"      ✅ Build succeeded (build_id={state.build_id})")

    try:
        print("\n[2/4] Exporting project files...")
        project_dir = orchestrator.export_build_output(state)
        print(f"      Exported to: {project_dir}")
    finally:
        orchestrator.stop_build(state)

    print("\n[3/4] Deploying to GitHub...")
    result = deploy_to_github(project_dir, demo_project, company="ProbeCo", build_id=state.build_id)
    print(f"      Repo: {result.repo_url}")

    print("\n[4/4] Verifying internal files never reached git history...")
    log_result = _run(["git", "log", "--all", "--name-only", "--pretty=format:"], cwd=project_dir)
    committed_files = set(f for f in log_result.stdout.splitlines() if f.strip())
    leaked = committed_files & set(INTERNAL_FILES_TO_STRIP)
    assert not leaked, f"Internal files leaked into git history: {leaked}"
    print(f"      ✅ No internal files in git history (committed {len(committed_files)} files total).")

    print("\n" + "=" * 60)
    print("  ✅ TEST PASSED")
    print(f"  ⚠️  Remember to delete the test repo: {result.repo_url}")
    print("=" * 60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        print("Usage:")
        print("  python -m sandbox.github_deploy --test   # end-to-end build + push to a real repo")
