"""Auto-built demo projects (Option 2): generate -> sandbox-verify -> deploy.

This skill turns the per-lead `demo_project` idea produced by
`skills/research_company.py` into a real, self-contained web app, verifies it
builds cleanly inside a Vercel Sandbox (Firecracker microVM), and deploys it to
a live Vercel URL. The resulting URL is later offered to the human reviewer, who
decides whether the outreach goes out WITH or WITHOUT the live demo link.

Pipeline position (see graph/pipeline.py):
    ... -> tailor_resume -> build_demo -> review (interrupt) -> draft -> send

Permanent constraints honored throughout:
  * Human review before any send (the post-deployment review gate).
  * Every step logs/raises loudly — no silent failures.
  * Zero fabrication — a live demo is only ever referenced when demo_status
    == "deployed". Build failures degrade gracefully to a no-link outreach.
  * Deployed demos are PUBLIC URLs, so generated apps must be self-contained,
    secret-free, and make no runtime external API calls.

CLI:
    python -m skills.build_demo --check       # verify config + sheet schema
    python -m skills.build_demo <lead_id>     # build+deploy one lead's demo
    python -m skills.build_demo --batch       # build+deploy for eligible leads

NOTE: This module is being built incrementally (Task 1 = scaffolding). The core
functions below are typed stubs that raise NotImplementedError until their
respective tasks land.
"""

import base64
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

# Ensure emoji/status log lines never crash on Windows when stdout is redirected
# to a file/pipe (cp1252 default). Headless cron runs would otherwise raise
# UnicodeEncodeError mid-node. Idempotent and harmless elsewhere.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Vercel Sandbox (sync API). Imported at module level so tests can monkeypatch
# `skills.build_demo._vercel_create_sandbox`. Guarded so importing this module
# never hard-fails in an environment without the `vercel` package installed.
try:
    from vercel.sandbox.sync import create_sandbox as _vercel_create_sandbox
except Exception:  # pragma: no cover - only when vercel isn't installed
    _vercel_create_sandbox = None

# Vercel Deployments API (create-from-files). Module-level so tests can patch it.
try:
    from vercel.deployments import create_deployment as _vercel_create_deployment
except Exception:  # pragma: no cover
    _vercel_create_deployment = None

# Sandbox tuning. The generated app is tiny (Vite+React), so a short limit is
# plenty and keeps us well inside the Hobby free tier.
_SANDBOX_WORKDIR = "demo"
_SANDBOX_TIME_LIMIT_S = 300  # 5 minutes; also the Hobby max session length
_MAX_LOG_CHARS = 6000  # cap captured logs so they stay usable in prompts/printouts


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  ⚠️  {name}={raw!r} is not an int; using default {default}")
        return default


@dataclass(frozen=True)
class DemoConfig:
    """Resolved configuration for the demo build/deploy feature."""

    enabled: bool
    codegen_backend: Optional[str]  # None => use llm_client global default
    max_retries: int
    project_prefix: str
    vercel_token: Optional[str]
    vercel_oidc_token: Optional[str]
    max_per_run: int  # cost guardrail: max demos built per feed/batch run

    @property
    def has_vercel_auth(self) -> bool:
        return bool(self.vercel_token or self.vercel_oidc_token)


def get_config() -> DemoConfig:
    """Read demo-feature config from the environment with safe defaults.

    Defaults are conservative: the feature is OFF unless DEMO_BUILD_ENABLED is
    explicitly truthy, so importing/running this module never changes existing
    pipeline behavior on its own.
    """
    backend = (os.getenv("DEMO_CODEGEN_BACKEND") or "").strip().lower() or None
    return DemoConfig(
        enabled=_env_bool("DEMO_BUILD_ENABLED", False),
        codegen_backend=backend,
        max_retries=_env_int("DEMO_MAX_RETRIES", 2),
        project_prefix=(os.getenv("DEMO_PROJECT_PREFIX") or "demo-").strip(),
        vercel_token=os.getenv("VERCEL_TOKEN") or None,
        vercel_oidc_token=os.getenv("VERCEL_OIDC_TOKEN") or None,
        max_per_run=_env_int("DEMO_MAX_PER_RUN", 5),
    )


# ---------------------------------------------------------------------------
# Core functions (implemented across Tasks 2-6)
# ---------------------------------------------------------------------------


DEMO_CODEGEN_SYSTEM_PROMPT = """You generate a COMPLETE, minimal, self-contained single-page web app that demonstrates a specific demo-project idea for a company. The app will be built and deployed to a PUBLIC URL and shown to a hiring manager, so it must look polished but stay tiny.

STACK (do not deviate):
- Vite + React (this is what the deploy target auto-detects and builds).
- Plain CSS. No UI component libraries, no Tailwind, no backend, no database.

HARD RULES — violating any of these is a critical failure:
1. SELF-CONTAINED: no runtime calls to external APIs, network requests, fetch(), websockets, or third-party scripts. All data must be hard-coded / mocked inline in the source.
2. NO SECRETS: never include API keys, tokens, passwords, private keys, connection strings, or environment variables of any kind. The app must need zero env vars to run.
3. NO PII: do not invent real people's personal data. Use the company name and the demo concept only.
4. MUST BUILD with `npm install && npm run build` using ONLY these exact pinned dependencies (do not add others):
   - "react": "18.3.1"
   - "react-dom": "18.3.1"
   devDependencies:
   - "vite": "5.4.10"
   - "@vitejs/plugin-react": "4.3.3"
5. Keep it to a single page that clearly presents the demo concept. Small but real — working interactivity is fine as long as it's purely client-side (React state only).

You MUST output these files, and only these files:
- package.json        (type: module; scripts: dev="vite", build="vite build", preview="vite preview")
- vite.config.js      (uses @vitejs/plugin-react)
- index.html          (root, references /src/main.jsx)
- src/main.jsx        (mounts <App/> into #root)
- src/App.jsx         (the demo UI)
- src/styles.css      (clean, modern, minimal styling)

OUTPUT FORMAT — emit each file EXACTLY like this, with no prose, no markdown, no commentary before/after:
<<<FILE package.json>>>
...file contents...
<<<END>>>
<<<FILE vite.config.js>>>
...file contents...
<<<END>>>
(...and so on for every file...)
"""

# Minimum files a valid Vite React app must contain for us to accept the output.
_REQUIRED_FILES = ("package.json", "index.html")

# File-block delimiter parser. Robust for code (no JSON-escaping of source).
_FILE_BLOCK_RE = re.compile(
    r"<<<FILE\s+(?P<path>[^\n>]+?)\s*>>>\n(?P<body>.*?)\n?<<<END>>>",
    re.DOTALL,
)

# High-confidence real-secret signatures. Deliberately narrow to avoid flagging
# harmless placeholders like "YOUR_API_KEY". If any of these appear in generated
# code, we refuse the output — a public demo must never carry a real credential.
_SECRET_PATTERNS = {
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai_anthropic_key": re.compile(r"\bsk-(?:live|proj|ant)[A-Za-z0-9\-_]{10,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    "github_pat": re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
}


def _strip_outer_fences(text: str) -> str:
    """Remove a single ```lang ... ``` wrapper if the model wrapped everything."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[\w-]*\s*\n", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped


def _parse_file_blocks(raw_text: str) -> Dict[str, str]:
    """Parse `<<<FILE path>>> ... <<<END>>>` blocks into a {path: content} dict.

    Raises ValueError if no blocks are found (loud failure — nothing usable).
    """
    text = _strip_outer_fences(raw_text)
    files: Dict[str, str] = {}
    for match in _FILE_BLOCK_RE.finditer(text):
        path = match.group("path").strip().lstrip("/")
        body = match.group("body")
        if path:
            files[path] = body
    if not files:
        raise ValueError(
            "generate_demo_app: LLM output contained no <<<FILE ...>>> blocks. "
            f"First 300 chars of output:\n{text[:300]}"
        )
    return files


def _scan_for_secrets(files: Dict[str, str]) -> List[str]:
    """Return a list of 'path: secret_type' findings for any high-confidence secrets."""
    findings: List[str] = []
    for path, content in files.items():
        for label, pattern in _SECRET_PATTERNS.items():
            if pattern.search(content or ""):
                findings.append(f"{path}: {label}")
    return findings


def generate_demo_app(demo_project: dict, lead: dict) -> Dict[str, str]:
    """Generate a minimal, self-contained Vite+React app from a demo_project idea.

    Parameters
    ----------
    demo_project : dict
        The `demo_project` sub-object from research_company output
        (title, description, tech_stack, deliverable, why_impressive, ...).
    lead : dict
        The lead record (company, role, jd_text, ...), for context.

    Returns
    -------
    dict[str, str]
        Mapping of relative file path -> file contents. Guaranteed to contain
        at least package.json and index.html, and guaranteed secret-free.

    Raises
    ------
    ValueError
        If the model output is unparseable, missing required files, or contains
        a real secret (public-deploy safety).
    """
    from skills.llm_client import llm_generate

    cfg = get_config()

    company = lead.get("company") or "the company"
    role = lead.get("role") or ""
    jd_text = (lead.get("jd_text") or "")[:2000]  # keep prompt lean/cheap

    title = demo_project.get("title", "") if demo_project else ""
    description = demo_project.get("description", "") if demo_project else ""
    tech_stack = ", ".join(demo_project.get("tech_stack", []) or []) if demo_project else ""
    deliverable = demo_project.get("deliverable", "") if demo_project else ""
    why_impressive = demo_project.get("why_impressive", "") if demo_project else ""

    if not (title or description):
        raise ValueError(
            "generate_demo_app: demo_project has no title/description to build from"
        )

    user_message = f"""Build the single-page demo app described below for {company}.

DEMO PROJECT:
- Title: {title}
- Description: {description}
- Relevant tech signals (for flavor only, still use Vite+React): {tech_stack or "(none)"}
- Intended deliverable: {deliverable or "a live demo link"}
- Why it should impress: {why_impressive or "(n/a)"}

CONTEXT:
- Company: {company}
- Role being targeted: {role or "(unspecified)"}
- Job description excerpt (for domain flavor only — do NOT call any real API):
{jd_text or "(none provided)"}

Produce the complete file set now, in the required <<<FILE ...>>> block format."""

    raw = llm_generate(
        system_prompt=DEMO_CODEGEN_SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=8000,
        backend=cfg.codegen_backend,  # None => llm_client global default
    )

    files = _parse_file_blocks(raw)

    missing = [f for f in _REQUIRED_FILES if f not in files]
    if missing:
        raise ValueError(
            f"generate_demo_app: output missing required files {missing}. "
            f"Got: {sorted(files.keys())}"
        )

    secrets = _scan_for_secrets(files)
    if secrets:
        raise ValueError(
            f"generate_demo_app: refusing output — real secret pattern(s) detected: {secrets}"
        )

    print(f"  🧱 generate_demo_app: produced {len(files)} files for {company} "
          f"({', '.join(sorted(files.keys()))})")
    return files


def write_files_to_dir(files: Dict[str, str], dest_dir: str) -> str:
    """Write a {path: content} mapping to dest_dir, creating subdirs. Returns dest_dir."""
    for rel_path, content in files.items():
        abs_path = os.path.join(dest_dir, rel_path)
        os.makedirs(os.path.dirname(abs_path) or dest_dir, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
    return dest_dir


def _tail(text: str, limit: int = _MAX_LOG_CHARS) -> str:
    """Return the last `limit` chars of text (build errors live at the end)."""
    text = text or ""
    return text if len(text) <= limit else "...[truncated]...\n" + text[-limit:]


def build_in_sandbox(files: Dict[str, str]) -> dict:
    """Verify that generated files `npm install && npm run build` in a Vercel Sandbox.

    Creates a short-lived Firecracker microVM (default `universal` image with
    Node LTS), writes the files into a working dir, runs install then build,
    captures logs, and destroys the sandbox promptly (via the context manager).

    Parameters
    ----------
    files : dict[str, str]
        {relative path: content} — e.g. output of generate_demo_app.

    Returns
    -------
    dict
        {"ok": bool, "logs": str, "image": str}. Never raises for an ordinary
        build failure — a failed install/build returns ok=False with logs. Only
        genuinely unexpected conditions (no auth, SDK/transport errors) also come
        back as ok=False, with the error text in `logs`.

    Auth: uses ambient Vercel credentials from the environment
    (VERCEL_OIDC_TOKEN preferred, else VERCEL_TOKEN + VERCEL_TEAM_ID +
    VERCEL_PROJECT_ID). If none are set, returns ok=False without attempting.
    """
    cfg = get_config()

    if _vercel_create_sandbox is None:
        msg = "build_in_sandbox: `vercel` package not installed (pip install vercel)."
        print(f"  ❌ {msg}")
        return {"ok": False, "logs": msg, "image": ""}

    if not cfg.has_vercel_auth:
        msg = ("build_in_sandbox: no Vercel auth in env "
               "(set VERCEL_OIDC_TOKEN or VERCEL_TOKEN). Skipping sandbox build.")
        print(f"  ⚠️  {msg}")
        return {"ok": False, "logs": msg, "image": ""}

    if not files:
        return {"ok": False, "logs": "build_in_sandbox: no files to build", "image": ""}

    print(f"  🏖️  build_in_sandbox: creating sandbox, writing {len(files)} files...")
    try:
        with _vercel_create_sandbox(execution_time_limit=_SANDBOX_TIME_LIMIT_S) as sandbox:
            image = getattr(sandbox, "image", "") or ""

            # Write every file under the working dir, creating parent dirs.
            for rel_path, content in files.items():
                rel_path = rel_path.lstrip("/")
                target = f"{_SANDBOX_WORKDIR}/{rel_path}"
                parent = target.rsplit("/", 1)[0] if "/" in target else ""
                if parent:
                    try:
                        sandbox.fs.mkdir(parent, recursive=True)
                    except Exception:
                        pass  # already exists / created by a sibling write
                sandbox.fs.write_text(target, content)

            # npm install
            print("  📦 build_in_sandbox: npm install...")
            install = sandbox.run_process(
                "npm", ["install", "--no-audit", "--no-fund"],
                cwd=_SANDBOX_WORKDIR, capture_output=True,
            )
            if install.returncode != 0:
                logs = _tail((install.stdout or "") + "\n" + (install.stderr or ""))
                print("  ❌ build_in_sandbox: npm install FAILED")
                return {"ok": False, "logs": f"[npm install failed]\n{logs}", "image": image}

            # npm run build
            print("  🔨 build_in_sandbox: npm run build...")
            build = sandbox.run_process(
                "npm", ["run", "build"],
                cwd=_SANDBOX_WORKDIR, capture_output=True,
            )
            combined = (build.stdout or "") + "\n" + (build.stderr or "")
            ok = build.returncode == 0
            if ok:
                print("  ✅ build_in_sandbox: build OK")
            else:
                print("  ❌ build_in_sandbox: npm run build FAILED")
            return {
                "ok": ok,
                "logs": _tail(combined if ok else f"[npm run build failed]\n{combined}"),
                "image": image,
            }
    except Exception as e:
        # Unexpected: SDK/transport/auth error, timeout, etc. Loud, but non-fatal
        # to the batch — the orchestrator treats ok=False as a build failure.
        print(f"  ❌ build_in_sandbox: sandbox error: {e}")
        return {"ok": False, "logs": f"sandbox error: {e}", "image": ""}


DEMO_FIX_SYSTEM_PROMPT = """You are fixing a small Vite + React demo app that FAILED to `npm install && npm run build`. You are given the current files and the build error log. Return the COMPLETE corrected file set that will build cleanly.

Keep ALL the original hard rules:
- Vite + React only; plain CSS; no backend/database.
- SELF-CONTAINED: no runtime network calls, no fetch(), no third-party scripts.
- NO SECRETS and NO environment variables of any kind.
- Use ONLY these pinned deps: react 18.3.1, react-dom 18.3.1 (deps); vite 5.4.10, @vitejs/plugin-react 4.3.3 (devDeps). Do not add others.
- The app must be a single page and build to static output.

Fix the actual cause shown in the error log (missing file/import, bad JSX, wrong config, mismatched entry path in index.html, etc.). Prefer the smallest change that makes it build. Re-output EVERY file needed for the app (not just the changed one), so the set is complete on its own.

OUTPUT FORMAT — emit each file EXACTLY like this, no prose, no markdown fences:
<<<FILE path>>>
...contents...
<<<END>>>
"""


def _files_to_blocks(files: Dict[str, str]) -> str:
    """Serialize a {path: content} mapping into the <<<FILE ...>>> block format."""
    parts = []
    for path in sorted(files.keys()):
        parts.append(f"<<<FILE {path}>>>\n{files[path]}\n<<<END>>>")
    return "\n".join(parts)


def fix_build_errors(
    files: Dict[str, str], error_log: str, demo_project: dict
) -> Dict[str, str]:
    """Ask the LLM to patch a failing demo app given the build error log.

    Returns a fresh {path: content} mapping (complete file set), validated the
    same way as generate_demo_app (required files present + secret-free).

    Raises ValueError if the model output is unusable — the caller
    (build_with_retries) treats that as an exhausted attempt.
    """
    from skills.llm_client import llm_generate

    cfg = get_config()
    title = (demo_project or {}).get("title", "the demo")

    user_message = f"""The demo app "{title}" failed to build. Fix it.

BUILD ERROR LOG:
{_tail(error_log, 4000)}

CURRENT FILES:
{_files_to_blocks(files)}

Return the complete corrected file set now, in the required <<<FILE ...>>> block format."""

    raw = llm_generate(
        system_prompt=DEMO_FIX_SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=8000,
        backend=cfg.codegen_backend,
    )

    fixed = _parse_file_blocks(raw)

    missing = [f for f in _REQUIRED_FILES if f not in fixed]
    if missing:
        raise ValueError(f"fix_build_errors: patched output missing required files {missing}")

    secrets = _scan_for_secrets(fixed)
    if secrets:
        raise ValueError(f"fix_build_errors: refusing patched output — secrets detected: {secrets}")

    print(f"  🩹 fix_build_errors: produced patched set of {len(fixed)} files")
    return fixed


def build_with_retries(files: Dict[str, str], demo_project: dict) -> dict:
    """Build the files; on failure, LLM-patch and rebuild up to DEMO_MAX_RETRIES.

    Returns {"ok": bool, "files": dict, "logs": str, "attempts": int} where
    `attempts` counts sandbox build runs (1 initial + up to max_retries retries)
    and `files` is the latest (possibly patched) file set. Bounded — never loops
    forever.
    """
    cfg = get_config()
    max_retries = max(0, cfg.max_retries)

    attempts = 0
    current = files
    last_logs = ""

    # Initial build + up to max_retries fix→rebuild cycles.
    for attempt_index in range(max_retries + 1):
        attempts += 1
        result = build_in_sandbox(current)
        last_logs = result.get("logs", "")

        if result.get("ok"):
            print(f"  ✅ build_with_retries: built OK on attempt {attempts}")
            return {"ok": True, "files": current, "logs": last_logs, "attempts": attempts}

        # Out of retries — stop here.
        if attempt_index >= max_retries:
            break

        print(f"  🔁 build_with_retries: attempt {attempts} failed, asking LLM to patch "
              f"({attempt_index + 1}/{max_retries})...")
        try:
            current = fix_build_errors(current, last_logs, demo_project)
        except Exception as e:
            print(f"  ❌ build_with_retries: fix step failed, giving up: {e}")
            last_logs = f"{last_logs}\n\n[fix_build_errors error] {e}"
            break

    print(f"  ❌ build_with_retries: giving up after {attempts} build attempt(s)")
    return {"ok": False, "files": current, "logs": last_logs, "attempts": attempts}


# Deployment polling knobs.
_DEPLOY_POLL_INTERVAL_S = 3.0
_DEPLOY_POLL_TIMEOUT_S = 180.0
_DEPLOY_TERMINAL_OK = {"READY"}
_DEPLOY_TERMINAL_BAD = {"ERROR", "CANCELED", "DELETED"}


def _sanitize_project_name(prefix: str, company: str) -> str:
    """Build a valid Vercel project name from a prefix + company.

    Vercel project names must be lowercase, <=100 chars, and contain only
    letters, digits and hyphens (no leading/trailing/triple hyphens).
    """
    base = re.sub(r"[^a-z0-9]+", "-", (company or "").lower())
    name = f"{(prefix or '').lower()}{base}"
    name = re.sub(r"-+", "-", name).strip("-")
    return (name[:100].strip("-")) or "demo"


def _get_deployment_state(deployment_id: str, token: str, team_id: Optional[str]) -> dict:
    """GET a deployment's current state. Returns {'state': str, 'url': str}.

    Split out (and module-level) so tests can patch it without real HTTP.
    """
    import requests

    url = f"https://api.vercel.com/v13/deployments/{deployment_id}"
    params = {"teamId": team_id} if team_id else {}
    resp = requests.get(
        url, params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # v13 uses readyState; fall back to status for safety.
    state = (data.get("readyState") or data.get("status") or "").upper()
    return {"state": state, "url": data.get("url", "")}


def deploy_to_vercel(files: Dict[str, str], project_name: str) -> str:
    """Deploy verified files to Vercel and return the live READY https URL.

    Uses the Deployments REST API with inline (base64) files, then polls until
    the deployment reaches READY. Raises loudly on missing auth, ERROR state,
    or timeout — the orchestrator (Task 6) converts that into build_failed.
    """
    cfg = get_config()

    if _vercel_create_deployment is None:
        raise RuntimeError("deploy_to_vercel: `vercel` package not installed")
    # The Deployments REST API needs a personal/team access token (not OIDC).
    if not cfg.vercel_token:
        raise RuntimeError("deploy_to_vercel: VERCEL_TOKEN is required to deploy")
    if not files:
        raise ValueError("deploy_to_vercel: no files to deploy")

    team_id = os.getenv("VERCEL_TEAM_ID") or None

    body_files = []
    for rel_path, content in files.items():
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        body_files.append({"file": rel_path.lstrip("/"), "data": encoded, "encoding": "base64"})

    body = {
        "name": project_name,
        "files": body_files,
        "projectSettings": {"framework": "vite"},
        "target": "production",
    }

    print(f"  🚀 deploy_to_vercel: creating deployment for project '{project_name}' "
          f"({len(body_files)} files)...")
    created = _vercel_create_deployment(
        body=body, token=cfg.vercel_token, team_id=team_id,
    )

    deployment_id = created.get("id") or created.get("uid")
    initial_url = created.get("url", "")
    initial_state = (created.get("readyState") or created.get("status") or "").upper()
    if not deployment_id:
        raise RuntimeError(f"deploy_to_vercel: no deployment id in response: {created}")

    # Poll until READY / ERROR / timeout.
    deadline = time.monotonic() + _DEPLOY_POLL_TIMEOUT_S
    state = initial_state
    live_url = initial_url

    while state not in _DEPLOY_TERMINAL_OK | _DEPLOY_TERMINAL_BAD:
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"deploy_to_vercel: timed out after {_DEPLOY_POLL_TIMEOUT_S:.0f}s "
                f"(last state: {state or 'unknown'})"
            )
        time.sleep(_DEPLOY_POLL_INTERVAL_S)
        snap = _get_deployment_state(deployment_id, cfg.vercel_token, team_id)
        state = snap["state"] or state
        live_url = snap["url"] or live_url
        print(f"     ...deployment state: {state or 'unknown'}")

    if state in _DEPLOY_TERMINAL_BAD:
        raise RuntimeError(f"deploy_to_vercel: deployment ended in state {state}")

    if not live_url:
        raise RuntimeError("deploy_to_vercel: READY but no URL returned")

    full_url = live_url if live_url.startswith("http") else f"https://{live_url}"
    print(f"  ✅ deploy_to_vercel: live at {full_url}")
    return full_url


def _resolve_demo_project(lead: dict) -> Optional[dict]:
    """Get the demo_project idea for a lead.

    Prefers an already-attached `company_research` (as the graph passes it),
    otherwise researches the company on the fly. Returns None if there's nothing
    to build from.
    """
    research = lead.get("company_research")
    if isinstance(research, dict) and research.get("demo_project"):
        return research["demo_project"]

    company = (lead.get("company") or "").strip()
    jd_text = (lead.get("jd_text") or "").strip()
    if not company and not jd_text:
        return None

    try:
        from skills.research_company import research_company

        research = research_company(
            company=company,
            domain=lead.get("domain", ""),
            role=lead.get("role", ""),
            jd_text=jd_text,
        )
        return (research or {}).get("demo_project")
    except Exception as e:
        print(f"  ⚠️  _resolve_demo_project: research failed: {e}")
        return None


def build_and_deploy_demo(lead: dict) -> dict:
    """Orchestrate generate -> build (with retries) -> deploy for one lead.

    Returns {"demo_url": str, "demo_status": str} where demo_status is one of:
      * "deployed"     — live URL in demo_url
      * "build_failed" — couldn't generate/build/deploy (demo_url == "")
      * "skipped"      — no demo_project idea to build from (demo_url == "")

    Never raises for an ordinary failure — a broken build/deploy degrades to
    build_failed so the caller can still route the lead to review WITHOUT a link.
    """
    company = lead.get("company") or lead.get("x_handle") or lead.get("id", "")
    cfg = get_config()

    demo_project = _resolve_demo_project(lead)
    if not demo_project:
        print(f"  ⏭️  build_and_deploy_demo: no demo_project for {company} — skipping")
        return {"demo_url": "", "demo_status": "skipped"}

    print(f"  🏗️  build_and_deploy_demo: {company} — {demo_project.get('title', 'demo')}")
    try:
        files = generate_demo_app(demo_project, lead)
    except Exception as e:
        print(f"  ❌ build_and_deploy_demo: generation failed for {company}: {e}")
        return {"demo_url": "", "demo_status": "build_failed"}

    build = build_with_retries(files, demo_project)
    if not build.get("ok"):
        print(f"  ❌ build_and_deploy_demo: build never went green for {company}")
        return {"demo_url": "", "demo_status": "build_failed"}

    project_name = _sanitize_project_name(cfg.project_prefix, lead.get("company") or demo_project.get("title", ""))
    try:
        url = deploy_to_vercel(build["files"], project_name)
    except Exception as e:
        print(f"  ❌ build_and_deploy_demo: deploy failed for {company}: {e}")
        return {"demo_url": "", "demo_status": "build_failed"}

    print(f"  🎉 build_and_deploy_demo: {company} demo live at {url}")
    return {"demo_url": url, "demo_status": "deployed"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def check() -> None:
    """Print detected config and ensure the live sheet has the demo columns."""
    cfg = get_config()
    print("=" * 60)
    print("build_demo config check")
    print("=" * 60)
    print(f"  DEMO_BUILD_ENABLED   : {cfg.enabled}")
    print(f"  DEMO_CODEGEN_BACKEND : {cfg.codegen_backend or '(llm_client default)'}")
    print(f"  DEMO_MAX_RETRIES     : {cfg.max_retries}")
    print(f"  DEMO_MAX_PER_RUN     : {cfg.max_per_run}")
    print(f"  DEMO_PROJECT_PREFIX  : {cfg.project_prefix!r}")
    print(f"  VERCEL_TOKEN set     : {bool(cfg.vercel_token)}")
    print(f"  VERCEL_OIDC_TOKEN set: {bool(cfg.vercel_oidc_token)}")
    print(f"  Vercel auth usable   : {cfg.has_vercel_auth}")

    if cfg.enabled and not cfg.has_vercel_auth:
        print("  ⚠️  DEMO_BUILD_ENABLED=true but no VERCEL_TOKEN/OIDC token set.")

    print("\nEnsuring sheet schema has demo columns...")
    try:
        from storage.sheet_client import ensure_headers, HEADERS

        ensure_headers()
        has_url = "demo_url" in HEADERS
        has_status = "demo_status" in HEADERS
        print(f"  demo_url in HEADERS   : {has_url}")
        print(f"  demo_status in HEADERS: {has_status}")
        if has_url and has_status:
            print("  ✅ Sheet schema ready.")
    except Exception as e:
        print(f"  ❌ Could not verify/ensure sheet schema: {e}")

    print("=" * 60)


def gen(lead_id: str) -> None:
    """Task 2 demo: research a lead, generate its demo app, write to a temp dir."""
    from storage.sheet_client import get_leads
    from skills.research_company import research_company

    leads = get_leads()
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        print(f"No lead found with id {lead_id}")
        return

    company = lead.get("company") or lead.get("x_handle") or lead_id
    print(f"\n🔍 Researching {company} to get a demo_project idea...")
    research = research_company(
        company=lead.get("company", ""),
        domain=lead.get("domain", ""),
        role=lead.get("role", ""),
        jd_text=lead.get("jd_text", ""),
    )
    demo_project = (research or {}).get("demo_project", {})
    print(f"   Demo idea: {demo_project.get('title', 'N/A')}")

    print("\n🧱 Generating demo app files...")
    files = generate_demo_app(demo_project, lead)

    dest = tempfile.mkdtemp(prefix=f"demo_{lead_id[:8]}_")
    write_files_to_dir(files, dest)

    print(f"\n📁 Wrote {len(files)} files to: {dest}")
    for path in sorted(files.keys()):
        print(f"   - {path}")

    if "package.json" in files:
        print("\n----- package.json -----")
        print(files["package.json"])


def _persist_demo_result(lead_id: str, result: dict) -> None:
    """Write demo_url/demo_status back to the sheet (best-effort, loud on error)."""
    if not lead_id:
        return
    try:
        from storage.sheet_client import update_lead

        update_lead(lead_id, {
            "demo_url": result.get("demo_url", ""),
            "demo_status": result.get("demo_status", ""),
        })
    except Exception as e:
        print(f"  ⚠️  _persist_demo_result: could not persist for {lead_id}: {e}")


def run(lead_id: str) -> None:
    """Build+deploy the demo for a single lead by id, then persist to the sheet."""
    from storage.sheet_client import get_leads

    leads = get_leads()
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        print(f"No lead found with id {lead_id}")
        return

    result = build_and_deploy_demo(lead)
    _persist_demo_result(lead_id, result)
    print(f"\nResult: {result}")


def run_batch(limit: Optional[int] = None) -> None:
    """Build+deploy demos for eligible leads and persist results.

    Eligible = has company + jd_text and no demo built yet (demo_status empty).
    Capped by `limit` (defaults to DEMO_MAX_PER_RUN) to keep cost/volume low.
    """
    from storage.sheet_client import get_leads

    cfg = get_config()
    if not cfg.enabled:
        print("DEMO_BUILD_ENABLED is false — refusing batch build. Set it to true to proceed.")
        return

    if limit is None:
        limit = cfg.max_per_run

    leads = get_leads()
    targets = [
        l for l in leads
        if (l.get("company") or "").strip()
        and (l.get("jd_text") or "").strip()
        and not (l.get("demo_status") or "").strip()
    ]
    print(f"Leads eligible for demo build: {len(targets)} (building up to {limit})")

    built = 0
    for lead in targets[:limit]:
        company = lead.get("company", "")
        print(f"\n=== {company} ({lead['id'][:8]}...) ===")
        result = build_and_deploy_demo(lead)
        _persist_demo_result(lead["id"], result)
        print(f"  -> {result['demo_status']} {result.get('demo_url', '')}")
        built += 1

    print(f"\nbuild_demo run_batch: processed {built} lead(s).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m skills.build_demo --check          # verify config + schema")
        print("  python -m skills.build_demo --gen <lead_id>  # generate demo app to temp dir")
        print("  python -m skills.build_demo <lead_id>        # build+deploy one lead")
        print("  python -m skills.build_demo --batch          # build+deploy eligible leads")
    elif sys.argv[1] == "--check":
        check()
    elif sys.argv[1] == "--gen":
        if len(sys.argv) < 3:
            print("Usage: python -m skills.build_demo --gen <lead_id>")
        else:
            gen(sys.argv[2])
    elif sys.argv[1] == "--batch":
        run_batch()
    else:
        run(sys.argv[1])
