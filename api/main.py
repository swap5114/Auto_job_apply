"""FastAPI backend — bridges the frontend dashboard to the existing Python pipeline.

Run with:
    uvicorn api.main:app --reload --port 8000 --reload-dir api --reload-dir graph --reload-dir orchestrator --reload-dir skills --reload-dir storage --reload-dir sandbox

Or from project root:
    python -m uvicorn api.main:app --reload --port 8000 --reload-dir api --reload-dir graph --reload-dir orchestrator --reload-dir skills --reload-dir storage --reload-dir sandbox

IMPORTANT: don't run plain `--reload` with no --reload-dir. With no explicit
dirs, uvicorn/watchfiles watches the *entire* project root recursively. Its
default ignore list only skips dot-prefixed dirs like .venv/.git — it does
NOT skip this project's `venv/`, `sandbox_output/`, or `resumes/` folders.
sandbox/orchestrator.py's export_build_output() dumps hundreds of files into
sandbox_output/<container_id>/ when a demo build finishes, which watchfiles
sees as a mass file-change and triggers a full server restart — wiping the
in-memory `_demo_builds` registry mid-poll. That's what causes "build
succeeded in the UI, then a 404 Build not found" a few seconds later.

Note: sandbox/ itself is in the reload-dir list above (it has real source
files worth reloading on), but this still watches sandbox/ recursively,
which technically includes nothing build-related since builds write to
sandbox_output/ (a sibling dir, not under sandbox/) -- so that's fine.
"""

import os
import sys
import json
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

# Add project root to path so we can import existing modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from db import repository as repo
from api.auth import get_authenticated_user_id
from api.rate_limit import get_client_ip, preview_limiter, resume_upload_limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle.

    If ENABLE_SCHEDULER=true in the environment, the APScheduler-based cron
    trigger (Phase 10b) starts with the API and shuts down cleanly on exit.
    """
    scheduler_started = False
    if os.getenv("ENABLE_SCHEDULER", "false").lower() == "true":
        try:
            from orchestrator.scheduler import start_scheduler
            start_scheduler()
            scheduler_started = True
        except Exception as e:
            print(f"⚠️  Failed to start scheduler: {e}")

    yield

    if scheduler_started:
        try:
            from orchestrator.scheduler import stop_scheduler
            stop_scheduler()
        except Exception as e:
            print(f"⚠️  Failed to stop scheduler cleanly: {e}")


app = FastAPI(
    title="AutoApply Pipeline API",
    description="REST API for the Auto Job Apply pipeline dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server (and, in prod, whatever origins are
# configured via ALLOWED_ORIGINS so a code change isn't needed to add the
# deployed frontend's origin later).
#
# ALLOWED_ORIGINS (config/.env): comma-separated list of origins, e.g.
#   ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com
# Falls back to localhost dev if unset -- this preserves today's behavior
# for anyone who hasn't added the new env var yet.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
if _allowed_origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "https://auto-job-apply-frontend-831721132982.us-central1.run.app",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class LeadResponse(BaseModel):
    id: str
    source: str
    company: str
    role: str
    jd_text: str
    contact_name: str
    contact_email: str
    x_handle: str
    status: str
    resume_version: str
    outreach_draft: str
    sent_at: str
    last_checked: str
    followup_count: str
    listing_url: str
    posted_date: str
    domain: str
    review_decision: str
    # Phase 5 additions. channel is a real list[str] (not the all-strings
    # convention every other field here follows) since it's genuinely a
    # small array -- the frontend needs it as one to render per-channel
    # badges (5.4), not a stringified Python list repr.
    channel: list[str] = []
    cover_note: str = ""
    applied_at: str = ""
    replied_at: str = ""
    failure_reason: str = ""
    job_id: str = ""


class StatsResponse(BaseModel):
    total: int
    new: int
    pending_review: int
    in_review: int
    approved: int
    draft_created: int
    sent: int
    replied: int
    rejected: int


class EditRequest(BaseModel):
    outreach_draft: str


class SaveJobRequest(BaseModel):
    """Which channel to create the lead for. v1 is outreach-only (the apply
    channel was removed), so this is fixed to ["outreach"]."""
    channel: list[str] = ["outreach"]


class DemoProjectResponse(BaseModel):
    title: str
    description: str
    tech_stack: list[str]
    deliverable: str
    time_estimate: str
    why_impressive: str


class ResearchResponse(BaseModel):
    overview: str
    stage: str
    industry: str
    tech_signals: list[str]
    demo_project: Optional[DemoProjectResponse] = None
    talking_points: list[str]
    smart_questions: list[str]
    fit_summary: str


class SettingsResponse(BaseModel):
    role_keywords: list[str]
    tech_stack_keywords: list[str]
    seniority_exclude_keywords: list[str]
    non_tech_exclude_keywords: list[str]
    years_experience_threshold: int
    location_keywords: list[str]


class SettingsUpdateRequest(BaseModel):
    role_keywords: Optional[list[str]] = None
    tech_stack_keywords: Optional[list[str]] = None
    seniority_exclude_keywords: Optional[list[str]] = None
    non_tech_exclude_keywords: Optional[list[str]] = None
    years_experience_threshold: Optional[int] = None
    location_keywords: Optional[list[str]] = None


class PipelineConfigResponse(BaseModel):
    model_backend: str
    followup_days: int
    max_followups: int
    gmail_direct_send: bool


class PipelineConfigUpdateRequest(BaseModel):
    model_backend: Optional[str] = None
    followup_days: Optional[int] = None
    max_followups: Optional[int] = None
    gmail_direct_send: Optional[bool] = None


class DemoProjectBuildRequest(BaseModel):
    """The demo_project spec the frontend already has in memory from a prior
    /research call — the client sends it back so we don't need to persist
    research results server-side just to start a build from them.
    """
    title: str
    description: str = ""
    tech_stack: list[str] = []
    deliverable: str = ""
    time_estimate: str = "2-3 days"
    why_impressive: str = ""


class BuildDemoRequest(BaseModel):
    demo_project: DemoProjectBuildRequest
    max_attempts: Optional[int] = None


class ProvideSecretsRequest(BaseModel):
    secrets: dict[str, str]


class DemoBuildStatusResponse(BaseModel):
    build_id: str
    lead_id: str
    running: bool
    stage: str
    attempt: int
    max_attempts: int
    needs_secrets: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    logs_tail: str = ""
    # Task 8: deploy phase, only meaningful once stage == "success"
    deploy_stage: Optional[str] = None
    deploy_error: Optional[str] = None
    repo_url: Optional[str] = None
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None


class DemoBuildSummary(BaseModel):
    """Lightweight summary for the Builds list page — omits the full log
    transcript so listing many builds stays cheap.
    """
    build_id: str
    lead_id: str
    company: str
    demo_title: str
    running: bool
    stage: str
    deploy_stage: Optional[str] = None
    attempt: int
    max_attempts: int
    started_at: str
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

# --- Short-lived leads cache -------------------------------------------------
# A single dashboard page load fires several read endpoints (stats + leads +
# review filters) in quick succession. This TTL cache collapses those into
# one Postgres read instead of N. Less critical than it was for Sheets (no
# hard read-quota to worry about with Postgres), but still avoids redundant
# round-trips within the same page load.
#
# Keyed by user_id (Phase 3): pre-auth this only ever served the single
# local operator, so a bare {data, ts} dict was safe. Now that requests
# carry a real per-request user_id, the cache MUST be keyed per-user --
# otherwise user A's leads could be served to user B for up to _LEADS_TTL
# seconds after A's request warms the cache.
_LEADS_TTL = 8  # seconds
_leads_cache: dict[str, dict] = {}  # user_id -> {"data": [...], "ts": float}
_leads_cache_lock = threading.Lock()


def _get_all_leads_cached(user_id: str, force: bool = False) -> list[dict]:
    """Return all leads for user_id, served from an in-memory cache when fresh."""
    now = time.monotonic()
    with _leads_cache_lock:
        entry = _leads_cache.get(user_id)
        if not force and entry is not None and (now - entry["ts"]) < _LEADS_TTL:
            return entry["data"]

    data = repo.get_leads(user_id)
    with _leads_cache_lock:
        _leads_cache[user_id] = {"data": data, "ts": time.monotonic()}
    return data


def _invalidate_leads_cache(user_id: Optional[str] = None):
    """Drop cached leads so the next read re-fetches from Postgres.

    With no user_id, clears every tenant's cache entry (used by call sites
    that don't have a specific user_id in scope, e.g. background pipeline
    workers) -- clearing more than necessary is always safe, just costs an
    extra Postgres read on the next request.
    """
    with _leads_cache_lock:
        if user_id is None:
            _leads_cache.clear()
        else:
            _leads_cache.pop(user_id, None)


def _get_search_criteria_path():
    return os.path.join(PROJECT_ROOT, "config", "search_criteria.json")


def _get_env_path():
    return os.path.join(PROJECT_ROOT, "config", ".env")


def _read_env_value(key: str, default: str = "") -> str:
    """Read a value from the .env file."""
    env_path = _get_env_path()
    if not os.path.exists(env_path):
        return default
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


# ---------------------------------------------------------------------------
# Routes: Leads
# ---------------------------------------------------------------------------

def _lead_to_response(lead: dict) -> LeadResponse:
    """Build a LeadResponse from a db.repository lead dict.

    repo.get_leads()/get_lead() return typed values straight from Postgres
    (None for unset text columns, a real int for followup_count, real
    datetime objects for sent_at/last_checked -- not the all-strings shape
    storage/sheet_client.py used to return, since Sheets has no native
    types). LeadResponse's fields are all plain str (kept as-is so the
    existing frontend, which is written against that all-strings shape,
    keeps working unchanged) -- so every field is normalized to a string
    here, with None/missing coerced to "" and datetimes to ISO text.
    """
    def s(value) -> str:
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return LeadResponse(
        id=s(lead.get("id")),
        source=s(lead.get("source")),
        company=s(lead.get("company")),
        role=s(lead.get("role")),
        jd_text=s(lead.get("jd_text")),
        contact_name=s(lead.get("contact_name")),
        contact_email=s(lead.get("contact_email")),
        x_handle=s(lead.get("x_handle")),
        status=s(lead.get("status")),
        resume_version=s(lead.get("resume_version")),
        outreach_draft=s(lead.get("outreach_draft")),
        sent_at=s(lead.get("sent_at")),
        last_checked=s(lead.get("last_checked")),
        followup_count=s(lead.get("followup_count")),
        listing_url=s(lead.get("listing_url")),
        posted_date=s(lead.get("posted_date")),
        domain=s(lead.get("domain")),
        review_decision=s(lead.get("review_decision")),
        channel=lead.get("channel") or [],
        cover_note=s(lead.get("cover_note")),
        applied_at=s(lead.get("applied_at")),
        replied_at=s(lead.get("replied_at")),
        failure_reason=s(lead.get("failure_reason")),
        job_id=s(lead.get("job_id")),
    )


@app.get("/api/leads", response_model=list[LeadResponse])
def list_leads(
    status: Optional[str] = Query(None, description="Filter by status"),
    user_id: str = Depends(get_authenticated_user_id),
):
    """List all leads, optionally filtered by status (served from TTL cache)."""
    leads = _get_all_leads_cached(user_id)
    if status:
        leads = [l for l in leads if str(l.get("status", "")).strip() == status]

    return [_lead_to_response(lead) for lead in leads]


@app.get("/api/leads/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Get a single lead by ID (served from TTL cache)."""
    leads = _get_all_leads_cached(user_id)
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)

    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return _lead_to_response(lead)


@app.get("/api/leads/{lead_id}/resume-pdf")
def get_lead_resume_pdf(lead_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Serve the tailored resume PDF for a lead (Phase 5.4's apply-channel
    review UI needs a real preview/download link, not just the filename
    text the outreach review page already shows). Tenant-scoped: the
    lookup goes through the caller's own leads, same as get_lead, so a
    user can't fetch another tenant's resume PDF by guessing a lead_id.
    """
    leads = _get_all_leads_cached(user_id)
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    resume_version = (lead.get("resume_version") or "").strip()
    if not resume_version:
        raise HTTPException(status_code=404, detail="No tailored resume for this lead yet")

    from skills.tailor_resume import RESUMES_DIR
    pdf_path = os.path.join(RESUMES_DIR, f"{resume_version}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Tailored resume PDF file not found on disk")

    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{resume_version}.pdf")


@app.post("/api/jobs/{job_id}/save", response_model=LeadResponse)
def save_job_as_lead(
    job_id: str,
    body: SaveJobRequest = SaveJobRequest(),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Create a per-user Lead from a shared-catalog Job (Phase 5.3).

    This is the job-to-lead conversion path that didn't exist anywhere in
    the codebase before this phase -- the ATS catalog connectors
    (skills/scrape_job_boards/{greenhouse,lever,ashby}.py) only ever write
    to the shared companies/jobs tables, never to a per-user Lead. This
    route is what a signed-in user acting on one of their matched catalog
    jobs (the anonymous /api/anon/resume feed's matched_jobs, or a future
    signed-in equivalent) actually calls to turn that job into a lead they
    can act on.

    Explicitly sets job_id (the FK back to the catalog row) and
    listing_url = job.apply_url -- the literal deep link the Apply
    channel exists to hand the user. This is the one thing this route
    must never get wrong: listing_url is not optional/best-effort here,
    it is copied straight from the catalog job's own apply_url.
    """
    job = repo.get_job_with_company(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Derive a domain from the catalog job's apply_url (for YC, this is the
    # company's own website) so downstream email discovery can resolve a real
    # founder/CEO via Apollo instead of guessing from the company name.
    apply_url = job.get("apply_url") or ""
    domain = ""
    if apply_url:
        try:
            from urllib.parse import urlparse
            host = urlparse(apply_url if "://" in apply_url else f"https://{apply_url}").netloc
            domain = host.replace("www.", "").strip()
            # Skip ATS/job-board hosts -- those aren't the employer's domain.
            if any(b in domain for b in ("greenhouse.io", "lever.co", "ashbyhq.com", "ycombinator.com")):
                domain = ""
        except Exception:
            domain = ""

    try:
        lead = repo.add_lead(user_id, {
            "job_id": job["id"],
            # v1 is outreach-only; the apply channel was removed, so every
            # saved job becomes an outreach lead regardless of the request.
            "channel": ["outreach"],
            "source": job.get("source"),
            "company": job.get("company_name") or "",
            "role": job.get("title") or "",
            "jd_text": job.get("jd_text") or "",
            "listing_url": apply_url,
            "domain": domain,
            "status": "matched",
        })
    except repo.DuplicateLeadError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except repo.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _invalidate_leads_cache(user_id)
    return _lead_to_response(lead)


@app.post("/api/leads/{lead_id}/approve")
def approve_lead(
    lead_id: str,
    channel: Optional[str] = Query(
        None, description="Which channel's review thread to approve, for leads paused on both"
    ),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Approve a lead.

    Tries to resume the LangGraph review checkpoint first (this is what
    actually drives the pipeline forward into send_node for outreach); if
    the lead isn't currently paused in the graph (e.g. it was added
    directly, never fed through feed_graph), falls back to a plain
    Postgres status update so the dashboard button still works either way.

    channel (Phase 5.2, optional): for a lead paused on both channels'
    threads at once, disambiguates which one this approval targets. Left
    unset, orchestrator.review_cli's own resolution order applies
    (outreach preferred when both are paused) -- existing callers that
    never knew about channels keep working unchanged; the apply review UI
    (5.4) always passes channel="apply" explicitly. The direct-update
    fallback below has no thread to resolve, so it always writes
    "approved"/"approved" regardless of channel -- a lead reaching that
    fallback was never fed into the graph in the first place, so there's
    no channel-specific "ready_to_apply" distinction to make.
    """
    try:
        from orchestrator.review_cli import approve_lead as _approve
        if _approve(lead_id, user_id=user_id, channel=channel):
            _invalidate_leads_cache(user_id)
            return {"status": "approved", "lead_id": lead_id, "via": "graph"}
    except Exception as e:
        print(f"  approve via graph failed ({e}), falling back to direct update")

    try:
        repo.update_lead(user_id, lead_id, {"status": "approved", "review_decision": "approved"})
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    _invalidate_leads_cache(user_id)
    return {"status": "approved", "lead_id": lead_id, "via": "direct"}


@app.post("/api/leads/{lead_id}/reject")
def reject_lead(
    lead_id: str,
    channel: Optional[str] = Query(
        None, description="Which channel's review thread to reject, for leads paused on both"
    ),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Reject a lead (graph resume, or direct Postgres update fallback).

    See approve_lead's docstring for the channel param's contract --
    identical here.
    """
    try:
        from orchestrator.review_cli import reject_lead as _reject
        if _reject(lead_id, user_id=user_id, channel=channel):
            _invalidate_leads_cache(user_id)
            return {"status": "rejected", "lead_id": lead_id, "via": "graph"}
    except Exception as e:
        print(f"  reject via graph failed ({e}), falling back to direct update")

    try:
        repo.update_lead(user_id, lead_id, {"status": "rejected", "review_decision": "rejected"})
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    _invalidate_leads_cache(user_id)
    return {"status": "rejected", "lead_id": lead_id, "via": "direct"}


@app.post("/api/leads/{lead_id}/edit")
def edit_lead(lead_id: str, body: EditRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Edit outreach draft and approve the lead (graph resume, or direct fallback).

    v1 is outreach-only. Kept as a distinct route with its own request body
    (outreach_draft) rather than one
    route branching on a field name, since the two artifacts are shaped
    differently enough that one shared payload would be harder to read,
    not easier (per PHASE_5_PLAN.md 5.3's own guidance on this).
    """
    try:
        from orchestrator.review_cli import edit_lead as _edit
        if _edit(lead_id, body.outreach_draft, user_id=user_id, channel="outreach"):
            _invalidate_leads_cache(user_id)
            return {"status": "approved", "lead_id": lead_id, "draft_updated": True, "via": "graph"}
    except Exception as e:
        print(f"  edit via graph failed ({e}), falling back to direct update")

    try:
        repo.update_lead(user_id, lead_id, {
            "status": "approved",
            "outreach_draft": body.outreach_draft,
            "review_decision": "edited",
        })
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    _invalidate_leads_cache(user_id)
    return {"status": "approved", "lead_id": lead_id, "draft_updated": True, "via": "direct"}


@app.post("/api/leads/{lead_id}/research", response_model=ResearchResponse)
def research_lead(
    lead_id: str,
    force_fresh: bool = Query(False),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Generate structured company research with demo project idea for a lead."""
    leads = _get_all_leads_cached(user_id)
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    try:
        from skills.research_company import research_company

        # Cross-user research cache (shared research_cache table, keyed by
        # the catalog job_id). Company research is a property of the company/
        # job, not the user, so once any user researches a catalog job every
        # other user reuses it instead of spending another LLM call.
        job_id = (lead.get("job_id") or "").strip() or None
        result = None
        if job_id and not force_fresh:
            cached = repo.get_cached_research(job_id)
            if cached and cached.get("result_json"):
                result = cached["result_json"]

        if result is None:
            result = research_company(
                company=str(lead.get("company", "")),
                domain=str(lead.get("domain", "")),
                role=str(lead.get("role", "")),
                jd_text=str(lead.get("jd_text", "")),
            )
            if job_id:
                try:
                    repo.set_cached_research(job_id, result)
                except Exception as e:
                    print(f"  ⚠️  research cache write failed for job {job_id}: {e}")

        # Build demo_project response if present
        demo_project = None
        if result.get("demo_project"):
            dp = result["demo_project"]
            demo_project = DemoProjectResponse(
                title=dp.get("title", ""),
                description=dp.get("description", ""),
                tech_stack=dp.get("tech_stack", []),
                deliverable=dp.get("deliverable", ""),
                time_estimate=dp.get("time_estimate", "2-3 days"),
                why_impressive=dp.get("why_impressive", ""),
            )
        
        return ResearchResponse(
            overview=result.get("overview", ""),
            stage=result.get("stage", "Unknown"),
            industry=result.get("industry", ""),
            tech_signals=result.get("tech_signals", []),
            demo_project=demo_project,
            talking_points=result.get("talking_points", []),
            smart_questions=result.get("smart_questions", []),
            fit_summary=result.get("fit_summary", ""),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Research generation failed: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Routes: Demo Builder (sandbox/orchestrator.py)
# ---------------------------------------------------------------------------
# Follows the same shape as the _pipeline_run_state pattern above (shared
# dict + lock + background daemon thread + polling endpoint), but keyed by
# build_id since multiple demo builds can run concurrently for different
# leads, unlike the single global pipeline run.

# build_id -> {"state": BuildState, "lead_id": str, "lock": threading.Lock()}
# Each build gets its own lock so polling one build's status never blocks on
# another build's in-progress work.
_demo_builds: dict[str, dict] = {}
_demo_builds_registry_lock = threading.Lock()  # protects the _demo_builds dict itself


def _register_build(
    build_id: str, lead_id: str, state, company: str = "", demo_title: str = "",
    demo_project: Optional[dict] = None,
) -> None:
    with _demo_builds_registry_lock:
        _demo_builds[build_id] = {
            "state": state,
            "lead_id": lead_id,
            "lock": threading.Lock(),
            "running": True,
            "company": company,
            "demo_title": demo_title,
            # Kept around so the resume-after-secrets path (which runs much
            # later, in a separate request) can chain into deploy_build()
            # with the same spec the build was originally started with.
            "demo_project": demo_project or {},
            "started_at": _now_iso(),
        }


def _get_build_entry(build_id: str) -> Optional[dict]:
    with _demo_builds_registry_lock:
        return _demo_builds.get(build_id)


def _finish_build_and_deploy(entry: dict, demo_project: dict, company: str) -> None:
    """Shared tail end for both _run_build_bg and _resume_build_bg.

    IMPORTANT ORDERING (this is the bug fix from Task 8 planning): the
    project must be exported from the container BEFORE the container is
    stopped. The previous version called stop_build() immediately on
    success, which destroys the container — by the time a deploy step tried
    to read files from it, there would be nothing left to export. The fix:
    finalize_success() (export) always runs first, stop_build() second,
    and only then does deploy_build() push to GitHub/Vercel/Render — none
    of which need the container anymore since they work off the exported
    directory on the host filesystem.

    A build that ends in needs_secrets deliberately leaves its container
    running (see orchestrator.start_build's docstring) — this function
    no-ops for that case, since there's nothing to finalize or deploy yet.
    """
    from sandbox import orchestrator

    state = entry["state"]

    if state.stage == "success":
        orchestrator.finalize_success(state)  # export BEFORE teardown

    if state.stage in ("success", "failed"):
        orchestrator.stop_build(state)  # container no longer needed either way

    if state.stage == "success" and state.project_dir:
        orchestrator.deploy_build(state, demo_project, company)


def _run_build_bg(build_id: str, demo_project: dict, company: str, max_attempts: int):
    """Background worker: runs the (blocking) build loop, then marks it done.

    Any exception here is caught and stored on the state object rather than
    left to crash a daemon thread silently — otherwise a bug would leave the
    build stuck at "running": True forever from the API's point of view.
    """
    from sandbox import orchestrator

    entry = _get_build_entry(build_id)
    state = entry["state"]
    try:
        orchestrator.start_build(
            demo_project=demo_project,
            company=company,
            max_attempts=max_attempts,
            state=state,  # mutate the SAME object callers are already polling
        )
        _finish_build_and_deploy(entry, demo_project, company)
    except Exception as e:
        state.stage = "failed"
        state.error = f"Unexpected orchestrator error: {e}"
    finally:
        with entry["lock"]:
            entry["running"] = False


def _resume_build_bg(build_id: str, secrets: dict, demo_project: dict, company: str):
    """Background worker for resuming a paused (needs_secrets) build."""
    from sandbox import orchestrator

    entry = _get_build_entry(build_id)
    state = entry["state"]
    with entry["lock"]:
        entry["running"] = True
    try:
        orchestrator.provide_secrets_and_resume(state, secrets)
        _finish_build_and_deploy(entry, demo_project, company)
    except Exception as e:
        state.stage = "failed"
        state.error = f"Unexpected orchestrator error during resume: {e}"
    finally:
        with entry["lock"]:
            entry["running"] = False


@app.post("/api/leads/{lead_id}/build-demo", response_model=DemoBuildStatusResponse)
def build_demo(lead_id: str, body: BuildDemoRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Start building a demo project in a sandbox container (non-blocking).

    Returns immediately with build_id="..." and stage="pending"; poll
    GET /api/leads/{lead_id}/build-demo/{build_id}/status for progress.
    """
    from sandbox.orchestrator import BuildState
    from sandbox.config import DEFAULT_MAX_ATTEMPTS

    leads = _get_all_leads_cached(user_id)
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    max_attempts = body.max_attempts or DEFAULT_MAX_ATTEMPTS
    state = BuildState(build_id=str(uuid.uuid4())[:8], max_attempts=max_attempts)
    company = str(lead.get("company", "")) or str(lead.get("x_handle", ""))
    demo_project_dict = body.demo_project.model_dump()
    _register_build(
        state.build_id, lead_id, state,
        company=company, demo_title=body.demo_project.title, demo_project=demo_project_dict,
    )
    threading.Thread(
        target=_run_build_bg,
        args=(state.build_id, demo_project_dict, company, max_attempts),
        daemon=True,
    ).start()

    return DemoBuildStatusResponse(
        build_id=state.build_id,
        lead_id=lead_id,
        running=True,
        stage=state.stage,
        attempt=state.attempt,
        max_attempts=state.max_attempts,
    )


@app.get("/api/leads/{lead_id}/build-demo/{build_id}/status", response_model=DemoBuildStatusResponse)
def build_demo_status(lead_id: str, build_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Poll the live status of a demo build."""
    entry = _get_build_entry(build_id)
    if not entry or entry["lead_id"] != lead_id:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found for lead {lead_id}")

    state = entry["state"]
    with entry["lock"]:
        running = entry["running"]

    # The transcript can carry several KB of stdout per attempt — expose only
    # a short tail from the most recent attempt for the "live logs" view,
    # rather than shipping the whole transcript on every poll.
    logs_tail = ""
    if state.transcript:
        last = state.transcript[-1]
        logs_tail = (last.get("stdout", "") or "")[-1500:]

    return DemoBuildStatusResponse(
        build_id=state.build_id,
        lead_id=lead_id,
        running=running,
        stage=state.stage,
        attempt=state.attempt,
        max_attempts=state.max_attempts,
        needs_secrets=state.needs_secrets,
        result=state.result,
        error=state.error,
        logs_tail=logs_tail,
        deploy_stage=state.deploy_stage,
        deploy_error=state.deploy_error,
        repo_url=state.repo_url,
        frontend_url=state.frontend_url,
        backend_url=state.backend_url,
    )


@app.post("/api/leads/{lead_id}/build-demo/{build_id}/secrets", response_model=DemoBuildStatusResponse)
def build_demo_provide_secrets(
    lead_id: str, build_id: str, body: ProvideSecretsRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Provide requested secrets and resume a paused build (non-blocking)."""
    entry = _get_build_entry(build_id)
    if not entry or entry["lead_id"] != lead_id:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found for lead {lead_id}")

    state = entry["state"]
    with entry["lock"]:
        already_running = entry["running"]
    if already_running:
        raise HTTPException(status_code=409, detail="Build is already in progress")
    if state.stage != "needs_secrets":
        raise HTTPException(status_code=409, detail=f"Build is in stage '{state.stage}', not waiting on secrets")

    with entry["lock"]:
        entry["running"] = True

    threading.Thread(
        target=_resume_build_bg,
        args=(build_id, body.secrets, entry.get("demo_project", {}), entry.get("company", "")),
        daemon=True,
    ).start()

    return DemoBuildStatusResponse(
        build_id=state.build_id,
        lead_id=lead_id,
        running=True,
        stage=state.stage,
        attempt=state.attempt,
        max_attempts=state.max_attempts,
        needs_secrets=state.needs_secrets,
    )


@app.post("/api/leads/{lead_id}/build-demo/{build_id}/cancel")
def build_demo_cancel(lead_id: str, build_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Stop a build and destroy its sandbox container."""
    from sandbox import orchestrator

    entry = _get_build_entry(build_id)
    if not entry or entry["lead_id"] != lead_id:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found for lead {lead_id}")

    state = entry["state"]
    orchestrator.stop_build(state)
    state.stage = "failed"
    state.result = state.result or {"status": "failed", "summary": "Cancelled by user."}

    with _demo_builds_registry_lock:
        _demo_builds.pop(build_id, None)

    return {"status": "cancelled", "build_id": build_id}


@app.get("/api/builds", response_model=list[DemoBuildSummary])
def list_builds(user_id: str = Depends(get_authenticated_user_id)):
    """List all demo builds from this server session, most recent first.

    Builds live only in memory (see _demo_builds above) — this list resets
    if the API process restarts, same as the pipeline run-state does.
    """
    with _demo_builds_registry_lock:
        entries = list(_demo_builds.items())

    summaries = []
    for build_id, entry in entries:
        state = entry["state"]
        with entry["lock"]:
            running = entry["running"]
        summaries.append(DemoBuildSummary(
            build_id=build_id,
            lead_id=entry["lead_id"],
            company=entry.get("company", ""),
            demo_title=entry.get("demo_title", ""),
            running=running,
            stage=state.stage,
            deploy_stage=state.deploy_stage,
            attempt=state.attempt,
            max_attempts=state.max_attempts,
            started_at=entry.get("started_at", ""),
            frontend_url=state.frontend_url,
            backend_url=state.backend_url,
        ))

    summaries.sort(key=lambda s: s.started_at, reverse=True)
    return summaries


# ---------------------------------------------------------------------------
# Routes: Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats", response_model=StatsResponse)
def get_stats(user_id: str = Depends(get_authenticated_user_id)):
    """Dashboard stats — count leads by status (served from TTL cache)."""
    leads = _get_all_leads_cached(user_id)
    total = len(leads)

    counts = {
        "new": 0,
        "pending_review": 0,
        "in_review": 0,
        "approved": 0,
        "draft_created": 0,
        "sent": 0,
        "replied": 0,
        "rejected": 0,
    }

    for lead in leads:
        status = str(lead.get("status", "")).strip()
        if status in counts:
            counts[status] += 1
        elif not status:
            counts["new"] += 1

    return StatsResponse(total=total, **counts)


# ---------------------------------------------------------------------------
# Routes: Pipeline Actions
# ---------------------------------------------------------------------------

@app.post("/api/pipeline/scrape")
def trigger_scrape(sources: Optional[list[str]] = None, user_id: str = Depends(get_authenticated_user_id)):
    """Trigger scraping from one or more sources.

    Valid sources: arbeitnow, jobicy, x, careers_page, yc
    If no sources specified, runs all available.
    """
    available_sources = ["arbeitnow", "jobicy", "x", "careers_page", "yc"]
    targets = sources or available_sources
    results = {}

    for source in targets:
        try:
            if source == "arbeitnow":
                from skills.scrape_job_boards.arbeitnow import run
                run()
                results[source] = "success"
            elif source == "jobicy":
                from skills.scrape_job_boards.jobicy import run
                run()
                results[source] = "success"
            elif source == "x":
                from skills.scrape_x_leads import run
                run()
                results[source] = "success"
            elif source == "careers_page":
                from skills.scrape_job_boards.careers_page import run
                run()
                results[source] = "success"
            elif source == "yc":
                from skills.scrape_job_boards.yc_startups import run
                run()
                results[source] = "success"
            else:
                results[source] = "unknown_source"
        except Exception as e:
            results[source] = f"error: {str(e)}"

    return {"results": results}


# ---------------------------------------------------------------------------
# On-demand full pipeline run (Phase 10b — dashboard "Run Pipeline" button)
# ---------------------------------------------------------------------------
#
# Phase 4.4: this used to be ONE global `_pipeline_run_state` dict + ONE
# global `_pipeline_lock` (threading.Lock()) shared by every caller --
# meaning two different signed-in users clicking "Run Pipeline" at the same
# time collided on the same dict, and the second caller got a spurious 409
# "Pipeline already running" even though it was a completely different
# person's run. Each run is now a `pipeline_runs` row (db/models.py),
# scoped by user_id -- repo.get_running_pipeline_run(user_id) replaces the
# global lock's "is anything running" check with a per-user query, and
# repo.get_latest_pipeline_run(user_id) replaces the global dict read.
# This also means a run's status survives an API process restart (or a
# second replica) instead of vanishing with the in-memory dict.
#
# NOTE (unchanged from Phase 3): the pipeline's sourcing/tailoring/outreach
# work itself (orchestrator.pipeline_runner.run_sourcing_pipeline) still
# operates against a single user_id per run -- what Phase 4.4 fixes is that
# TWO DIFFERENT USERS' runs no longer collide with each other. Making the
# actual scraping/tailoring logic aware of per-user search criteria, quotas,
# etc. beyond "whose leads table do writes land in" remains out of scope
# here, same as it was for Phase 3.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunPipelineRequest(BaseModel):
    sources: Optional[list[str]] = None
    yc_max_leads: int = 5
    x_max_leads: int = 5
    csv_path: Optional[str] = None


def _run_pipeline_bg(user_id: str, run_id: str, sources, yc_max_leads, x_max_leads, csv_path):
    """Background worker that runs the sourcing pipeline for user_id and
    tracks progress in that run's pipeline_runs row (not a global dict).
    """
    from orchestrator.pipeline_runner import run_sourcing_pipeline

    def on_step(label: str, status: str):
        try:
            repo.append_pipeline_run_step(run_id, label, status)
        except Exception as e:
            print(f"  ⚠️  pipeline run {run_id}: failed to record step '{label}': {e}")

    try:
        summary = run_sourcing_pipeline(
            sources=sources,
            yc_max_leads=yc_max_leads,
            x_max_leads=x_max_leads,
            csv_path=csv_path,
            progress_callback=on_step,
            user_id=user_id,
        )
        repo.update_pipeline_run(run_id, {"status": "completed", "summary": summary})
    except Exception as e:
        repo.update_pipeline_run(run_id, {"status": "failed", "error": str(e)})
    finally:
        # New leads were likely written to Postgres — drop the cache so the
        # next dashboard/leads read reflects them.
        _invalidate_leads_cache(user_id)
        repo.update_pipeline_run(run_id, {"current_step": None, "finished_at": datetime.now(timezone.utc)})


def _pipeline_run_to_response(run: Optional[dict]) -> dict:
    """Shapes a pipeline_runs row (or None) into the response contract
    frontend/src/lib/api.ts's PipelineRunState expects -- unchanged from
    the pre-Phase-4 global-dict shape, so no frontend changes are needed.
    """
    if run is None:
        return {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "current_step": None,
            "steps": [],
            "summary": None,
            "error": None,
        }
    return {
        "running": run["status"] == "running",
        "started_at": run["started_at"].isoformat() if run["started_at"] else None,
        "finished_at": run["finished_at"].isoformat() if run["finished_at"] else None,
        "current_step": run["current_step"],
        "steps": run["steps"] or [],
        "summary": run["summary"],
        "error": run["error"],
    }


@app.post("/api/pipeline/run")
def run_pipeline(body: RunPipelineRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Start the full sourcing+processing pipeline on demand (non-blocking),
    scoped to the calling user_id.

    Runs in a background thread; poll /api/pipeline/run-status for progress.
    Rejects with 409 only if THIS user already has a run in progress --
    a different user's concurrent run never blocks this one (Phase 4.4).
    """
    if repo.get_running_pipeline_run(user_id):
        raise HTTPException(status_code=409, detail="Pipeline already running")

    run = repo.create_pipeline_run(user_id)
    # v1: YC is the only automated source (all other boards parked).
    sources = body.sources or ["yc"]
    yc_max = min(max(1, body.yc_max_leads or 5), 15)
    threading.Thread(
        target=_run_pipeline_bg,
        args=(user_id, run["id"], sources, yc_max, body.x_max_leads, body.csv_path),
        daemon=True,
    ).start()

    return {"status": "started", "sources": sources}


@app.get("/api/pipeline/run-status")
def pipeline_run_status(user_id: str = Depends(get_authenticated_user_id)):
    """Return the live state of the caller's current/last pipeline run."""
    run = repo.get_latest_pipeline_run(user_id)
    return _pipeline_run_to_response(run)


class RunForLeadsRequest(BaseModel):
    lead_ids: list[str] = []


def _run_process_leads_bg(user_id: str, run_id: str, lead_ids: list[str]):
    """Background worker: process a set of saved leads to the review queue."""
    from orchestrator.pipeline_runner import run_pipeline_for_leads

    def on_step(label: str, status: str):
        try:
            repo.append_pipeline_run_step(run_id, label, status)
        except Exception as e:
            print(f"  ⚠️  pipeline run {run_id}: failed to record step '{label}': {e}")

    try:
        summary = run_pipeline_for_leads(user_id=user_id, lead_ids=lead_ids, progress_callback=on_step)
        repo.update_pipeline_run(run_id, {"status": "completed", "summary": summary})
    except Exception as e:
        repo.update_pipeline_run(run_id, {"status": "failed", "error": str(e)})
    finally:
        _invalidate_leads_cache(user_id)
        repo.update_pipeline_run(run_id, {"current_step": None, "finished_at": datetime.now(timezone.utc)})


@app.post("/api/pipeline/run-for-leads")
def run_for_leads(body: RunForLeadsRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Start the outreach pipeline on a specific set of already-saved leads
    (the hero-chat "approve these startups" bridge). Non-blocking; poll
    /api/pipeline/run-status for progress.

    Validates that every lead_id belongs to the caller before enqueuing --
    a lead_id owned by another tenant (or nonexistent) is rejected, never
    silently processed.
    """
    if not body.lead_ids:
        raise HTTPException(status_code=400, detail="No lead_ids provided")

    owned = {str(l.get("id")) for l in repo.get_leads(user_id)}
    unknown = [lid for lid in body.lead_ids if lid not in owned]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Lead(s) not found: {unknown}")

    if repo.get_running_pipeline_run(user_id):
        raise HTTPException(status_code=409, detail="Pipeline already running")

    run = repo.create_pipeline_run(user_id)
    threading.Thread(
        target=_run_process_leads_bg,
        args=(user_id, run["id"], list(body.lead_ids)),
        daemon=True,
    ).start()

    return {"status": "started", "leads": len(body.lead_ids)}


@app.post("/api/leads/{lead_id}/retry")
def retry_lead(lead_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Retry a stuck/failed lead (v1 Task 11). Clears its failure_reason and
    re-runs the processing chain, which is field-driven so it resumes at
    whichever stage failed (e.g. re-attempts email lookup, tailoring, or
    drafting). Tenant-scoped: 404 for a lead the caller doesn't own."""
    lead = next((l for l in _get_all_leads_cached(user_id) if str(l.get("id")) == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    if repo.get_running_pipeline_run(user_id):
        raise HTTPException(status_code=409, detail="Pipeline already running")

    try:
        repo.update_lead(user_id, lead_id, {"failure_reason": None})
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    _invalidate_leads_cache(user_id)

    run = repo.create_pipeline_run(user_id)
    threading.Thread(
        target=_run_process_leads_bg,
        args=(user_id, run["id"], [lead_id]),
        daemon=True,
    ).start()

    return {"status": "retrying", "lead_id": lead_id}


@app.post("/api/pipeline/upload-csv")
async def upload_csv(file: UploadFile = File(...), user_id: str = Depends(get_authenticated_user_id)):
    """Upload a companies CSV and run the company_list scraper + processing.

    The CSV is saved to config/uploaded_companies.csv, then the pipeline runs
    with only the company_list source in the background, scoped to user_id.
    """
    if repo.get_running_pipeline_run(user_id):
        raise HTTPException(status_code=409, detail="Pipeline already running")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")

    save_path = os.path.join(PROJECT_ROOT, "config", "uploaded_companies.csv")
    try:
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save CSV: {e}")

    run = repo.create_pipeline_run(user_id)
    threading.Thread(
        target=_run_pipeline_bg,
        args=(user_id, run["id"], ["company_list"], 15, 5, save_path),
        daemon=True,
    ).start()

    return {"status": "started", "filename": file.filename, "saved_to": save_path}


@app.post("/api/pipeline/find-emails")
def trigger_find_emails(user_id: str = Depends(get_authenticated_user_id)):
    """Run the contact email discovery skill, scoped to the caller."""
    try:
        from skills.find_contact_email import run
        run(user_id=user_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/tailor-resumes")
def trigger_tailor_resumes(user_id: str = Depends(get_authenticated_user_id)):
    """Run the resume tailoring skill for the caller's leads that need it."""
    try:
        from skills.tailor_resume import run
        run(user_id=user_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/draft-outreach")
def trigger_draft_outreach(user_id: str = Depends(get_authenticated_user_id)):
    """Run the outreach drafting skill for the caller's leads."""
    try:
        from skills.draft_outreach import run
        run(user_id=user_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/feed-graph")
def trigger_feed_graph(user_id: str = Depends(get_authenticated_user_id)):
    """Feed the caller's pending leads into the LangGraph review pipeline."""
    try:
        from orchestrator.feed_graph import feed_pending_leads
        count = feed_pending_leads(user_id=user_id)
        return {"status": "success", "leads_fed": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/send")
def trigger_send(user_id: str = Depends(get_authenticated_user_id)):
    """Send (or draft) the caller's approved leads via THEIR connected Gmail.
    Returns a summary. If no Gmail is connected, returns a clear needs_gmail
    status instead of failing."""
    try:
        from skills.send_via_gmail import run
        acct = repo.get_gmail_account(user_id)
        if not acct:
            return {"status": "needs_gmail", "detail": "Connect your Gmail in Settings first."}
        summary = run(user_id=user_id)
        _invalidate_leads_cache(user_id)
        mode = "direct" if acct.get("send_mode") == "direct" else "drafts"
        return {"status": "success", "mode": mode, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/check-followups")
def trigger_check_followups(user_id: str = Depends(get_authenticated_user_id)):
    """Check the caller's sent leads for follow-up needs."""
    try:
        from orchestrator.check_followups import check_and_queue_followups
        count = check_and_queue_followups(user_id=user_id)
        return {"status": "success", "followups_queued": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/catalog-refresh")
def trigger_catalog_refresh(providers: Optional[list[str]] = None, user_id: str = Depends(get_authenticated_user_id)):
    """Sync the shared job catalog (companies/jobs) from Greenhouse, Lever,
    and Ashby. Unlike the other /api/pipeline/* routes, this writes to the
    shared catalog, not per-user leads -- see
    orchestrator.pipeline_runner.run_catalog_refresh's docstring.
    """
    try:
        from orchestrator.pipeline_runner import run_catalog_refresh
        summary = run_catalog_refresh(providers=providers)
        return {"status": "success", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Routes: Gmail connection (per-user OAuth, Task 5)
# ---------------------------------------------------------------------------


class GmailStatusResponse(BaseModel):
    connected: bool
    email: Optional[str] = None
    send_mode: str = "draft"


class GmailSendModeRequest(BaseModel):
    send_mode: str  # "draft" | "direct"


@app.get("/api/gmail/status", response_model=GmailStatusResponse)
def gmail_status(user_id: str = Depends(get_authenticated_user_id)):
    """Whether the caller has connected their Gmail, and their send mode."""
    acct = repo.get_gmail_account(user_id)
    if not acct:
        return GmailStatusResponse(connected=False)
    return GmailStatusResponse(
        connected=True, email=acct.get("email"), send_mode=acct.get("send_mode", "draft")
    )


@app.get("/api/gmail/connect")
def gmail_connect(
    send_mode: str = Query("draft", description="'draft' or 'direct'"),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Return the Google consent URL for the caller to connect their Gmail.

    The caller's identity + chosen send preference ride through OAuth's
    signed `state` param so the (unauthenticated) callback can trust them.
    The frontend redirects the browser to `auth_url`.
    """
    if send_mode not in ("draft", "direct"):
        raise HTTPException(status_code=400, detail="send_mode must be 'draft' or 'direct'")
    from api import gmail_oauth

    try:
        auth_url = gmail_oauth.build_consent_url(user_id, send_mode)
    except gmail_oauth.GmailOAuthConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"auth_url": auth_url}


@app.get("/api/gmail/callback")
def gmail_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None)):
    """OAuth redirect target. Verifies state, exchanges the code for a refresh
    token, persists an ENCRYPTED token, and redirects the browser back to the
    frontend settings page.

    This route is intentionally NOT behind get_authenticated_user_id: it's a
    top-level browser redirect from Google with no Authorization header. The
    user's identity is instead recovered from the signed `state` param.
    """
    from api import gmail_oauth

    frontend = (os.getenv("FRONTEND_URL") or os.getenv("NEXT_PUBLIC_FRONTEND_URL") or "https://auto-job-apply-frontend-831721132982.us-central1.run.app").rstrip("/")


    if error:
        return RedirectResponse(f"{frontend}/settings?gmail=error")
    if not code or not state:
        return RedirectResponse(f"{frontend}/settings?gmail=error")

    try:
        result = gmail_oauth.exchange_code_for_account(code, state)
    except gmail_oauth.GmailOAuthStateError:
        return RedirectResponse(f"{frontend}/settings?gmail=state_error")
    except gmail_oauth.GmailOAuthConfigError:
        return RedirectResponse(f"{frontend}/settings?gmail=config_error")
    except Exception:
        return RedirectResponse(f"{frontend}/settings?gmail=error")

    try:
        encrypted = gmail_oauth.encrypt_token(result["refresh_token"])
        repo.upsert_gmail_account(
            user_id=result["user_id"],
            email=result["email"],
            encrypted_refresh_token=encrypted,
            scopes=result["scopes"],
            send_mode=result["send_mode"],
        )
    except Exception:
        return RedirectResponse(f"{frontend}/settings?gmail=error")

    return RedirectResponse(f"{frontend}/settings?gmail=connected")


@app.put("/api/gmail/send-mode", response_model=GmailStatusResponse)
def gmail_set_send_mode(body: GmailSendModeRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Update the caller's send preference (draft vs direct)."""
    if body.send_mode not in ("draft", "direct"):
        raise HTTPException(status_code=400, detail="send_mode must be 'draft' or 'direct'")
    try:
        acct = repo.update_gmail_send_mode(user_id, body.send_mode)
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail="No connected Gmail account")
    return GmailStatusResponse(connected=True, email=acct.get("email"), send_mode=acct["send_mode"])


@app.post("/api/gmail/disconnect")
def gmail_disconnect(user_id: str = Depends(get_authenticated_user_id)):
    """Disconnect the caller's Gmail (removes the stored encrypted token)."""
    removed = repo.delete_gmail_account(user_id)
    return {"status": "disconnected" if removed else "not_connected"}


# ---------------------------------------------------------------------------
# Routes: Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings/search-criteria", response_model=SettingsResponse)
def get_search_criteria(user_id: str = Depends(get_authenticated_user_id)):
    """Get current search criteria configuration.

    NOTE: this reads config/search_criteria.json -- a single global file,
    not the per-user `search_criteria` table. It's the pipeline's global
    scraping/matching config (role keywords, tech stack, etc used by
    skills/match_jobs.py and the scrapers), distinct from a signed-in
    user's own inferred/editable criteria, which live in the `search_criteria`
    table and are served by /api/profile/search-criteria (Phase 3.7). Both
    exist side by side; this route is just gated behind auth now like every
    other non-anon route, its behavior is otherwise unchanged.
    """
    path = _get_search_criteria_path()
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="search_criteria.json not found")

    with open(path, "r") as f:
        data = json.load(f)

    return SettingsResponse(
        role_keywords=data.get("role_keywords", []),
        tech_stack_keywords=data.get("tech_stack_keywords", []),
        seniority_exclude_keywords=data.get("seniority_exclude_keywords", []),
        non_tech_exclude_keywords=data.get("non_tech_exclude_keywords", []),
        years_experience_threshold=data.get("years_experience_threshold", 1),
        location_keywords=data.get("location_keywords", []),
    )


@app.put("/api/settings/search-criteria")
def update_search_criteria(body: SettingsUpdateRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Update search criteria configuration (global pipeline config file -- see get_search_criteria's note)."""
    path = _get_search_criteria_path()

    # Read existing
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
    else:
        data = {}

    # Merge updates
    if body.role_keywords is not None:
        data["role_keywords"] = body.role_keywords
    if body.tech_stack_keywords is not None:
        data["tech_stack_keywords"] = body.tech_stack_keywords
    if body.seniority_exclude_keywords is not None:
        data["seniority_exclude_keywords"] = body.seniority_exclude_keywords
    if body.non_tech_exclude_keywords is not None:
        data["non_tech_exclude_keywords"] = body.non_tech_exclude_keywords
    if body.years_experience_threshold is not None:
        data["years_experience_threshold"] = body.years_experience_threshold
    if body.location_keywords is not None:
        data["location_keywords"] = body.location_keywords

    # Write back
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return {"status": "updated", "data": data}


@app.post("/api/settings/auto-fill-from-resume")
def auto_fill_search_criteria_from_resume(user_id: str = Depends(get_authenticated_user_id)):
    """Auto-fill search criteria from calling user's active parsed resume."""
    active_resume = repo.get_active_resume(user_id)
    parsed = None
    if active_resume:
        parsed = active_resume.get("parsed") or active_resume
    else:
        user = repo.get_user(user_id)
        if user and user.get("parsed_resume"):
            parsed = user["parsed_resume"]

    if not parsed:
        # Fallback to reading default resume.json if local single user mode
        resume_json_path = os.path.join(PROJECT_ROOT, "config", "resume.json")
        if os.path.exists(resume_json_path):
            try:
                with open(resume_json_path, encoding="utf-8") as f:
                    parsed = json.load(f)
            except Exception:
                pass

    if not parsed:
        raise HTTPException(status_code=404, detail="No active resume found for this user. Please upload a resume first.")

    from skills.infer_criteria import infer_criteria
    inferred = infer_criteria(parsed)

    path = _get_search_criteria_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    if inferred.get("roles"):
        data["role_keywords"] = inferred["roles"]
    if inferred.get("tech_stack"):
        data["tech_stack_keywords"] = inferred["tech_stack"]
    if inferred.get("locations"):
        data["location_keywords"] = inferred["locations"]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {
        "role_keywords": data.get("role_keywords", []),
        "tech_stack_keywords": data.get("tech_stack_keywords", []),
        "seniority_exclude_keywords": data.get("seniority_exclude_keywords", []),
        "non_tech_exclude_keywords": data.get("non_tech_exclude_keywords", []),
        "years_experience_threshold": data.get("years_experience_threshold", 1),
        "location_keywords": data.get("location_keywords", []),
    }


@app.get("/api/settings/pipeline-config", response_model=PipelineConfigResponse)
def get_pipeline_config(user_id: str = Depends(get_authenticated_user_id)):
    """Get pipeline configuration from .env."""
    return PipelineConfigResponse(
        model_backend=_read_env_value("MODEL_BACKEND", "claude"),
        followup_days=int(_read_env_value("FOLLOWUP_DAYS", "5")),
        max_followups=int(_read_env_value("MAX_FOLLOWUPS", "1")),
        gmail_direct_send=_read_env_value("GMAIL_DIRECT_SEND", "false").lower() == "true",
    )


@app.put("/api/settings/pipeline-config")
def update_pipeline_config(body: PipelineConfigUpdateRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Update pipeline configuration in .env."""
    env_path = _get_env_path()

    # Read current .env content
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    # Helper to update or add a key
    def set_value(key: str, value: str):
        nonlocal lines
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}\n")

    if body.model_backend is not None:
        set_value("MODEL_BACKEND", body.model_backend)
    if body.followup_days is not None:
        set_value("FOLLOWUP_DAYS", str(body.followup_days))
    if body.max_followups is not None:
        set_value("MAX_FOLLOWUPS", str(body.max_followups))
    if body.gmail_direct_send is not None:
        set_value("GMAIL_DIRECT_SEND", str(body.gmail_direct_send).lower())

    with open(env_path, "w") as f:
        f.writelines(lines)

    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Routes: Scheduler (Phase 10b)
# ---------------------------------------------------------------------------

@app.get("/api/scheduler/status")
def scheduler_status(user_id: str = Depends(get_authenticated_user_id)):
    """Return whether the scheduler is running and its jobs' next run times."""
    try:
        from orchestrator.scheduler import get_scheduler, get_jobs_status
        sched = get_scheduler()
        running = bool(sched and sched.running)
        return {"running": running, "jobs": get_jobs_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/start")
def scheduler_start(user_id: str = Depends(get_authenticated_user_id)):
    """Start the scheduler (idempotent)."""
    try:
        from orchestrator.scheduler import start_scheduler, get_jobs_status
        start_scheduler()
        return {"status": "started", "jobs": get_jobs_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/stop")
def scheduler_stop(user_id: str = Depends(get_authenticated_user_id)):
    """Stop the scheduler."""
    try:
        from orchestrator.scheduler import stop_scheduler
        stop_scheduler()
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/trigger/{job_id}")
def scheduler_trigger(job_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Manually trigger a scheduled job now (runs in the background).

    Valid job_ids: sourcing, followups, catalog_refresh
    """
    try:
        from orchestrator.scheduler import trigger_job_now
        ok = trigger_job_now(job_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'")
        return {"status": "triggered", "job_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Anonymous pre-signup hook (Phase 2)
# ---------------------------------------------------------------------------
#
# The whole point of this hook is 30 seconds from "paste a resume" to "see
# real, relevant jobs" -- with NO auth gate before either endpoint below.
# That means these are the only genuinely public, unauthenticated surface
# in this API, and the only place abuse controls (rate limiting, upload
# validation) matter yet.
#
# Deliberately stateless server-side: no anonymous "session" row anywhere.
# /api/anon/resume does everything in one response (parse -> infer
# criteria -> match the catalog) and hands back the full parsed_resume +
# inferred_criteria + matched_jobs. The frontend holds that in memory and
# sends parsed_resume straight back in the body of /api/anon/preview when
# a visitor clicks a job -- nothing is looked up by a token server-side.
# This also makes Phase 3's "anon session converts to a saved account on
# sign-in" trivial later: the frontend already has everything it needs to
# POST into a real per-user save endpoint, no session migration required.
#
# Only ONE LLM call happens anywhere in the /api/anon/resume path (the
# resume parse itself, in skills/parse_resume.py) -- criteria inference
# and catalog matching are both pure Python/SQL, which is what lets the
# feed render inside the 30-second budget without waiting on a second
# model round-trip. /api/anon/preview is a second, separate, on-demand
# LLM call (one tailored resume for one clicked job), which is why it
# has its own rate limit tracked independently of the upload endpoint.

MAX_RESUME_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".txt"}


class ParsedResumeResponse(BaseModel):
    """Mirrors config/base_resume.json's shape -- see
    skills/parse_resume.py's RESUME_JSON_SHAPE_DESCRIPTION for the
    authoritative definition this must stay in sync with.
    """
    name: str = ""
    contact: dict = {}
    summary: str = ""
    education: list[dict] = []
    experience: list[dict] = []
    projects: list[dict] = []
    skills: dict = {}
    certifications: list[str] = []


class InferredCriteriaResponse(BaseModel):
    roles: list[str]
    tech_stack: list[str]
    seniority: Optional[str] = None
    locations: list[str]
    remote_pref: Optional[str] = None
    inferred_from_resume: bool


class MatchedJobResponse(BaseModel):
    id: str
    company_name: str
    title: str
    location: Optional[str] = None
    department: Optional[str] = None
    jd_text: Optional[str] = None
    apply_url: Optional[str] = None
    source: str
    # Signed-in-only fields (Phase 6): unused/defaulted for the anonymous
    # /api/anon/resume route above, populated by /api/jobs/matched below.
    # match_score/matched_signals are the same numbers skills/match_jobs.py
    # already computes internally to rank the list -- surfaced here so the
    # UI can show *why* a job matched instead of just an opaque ordering.
    match_score: int = 0
    matched_signals: list[str] = []
    # If the signed-in user already saved this job as a lead, its id/channel
    # so the frontend can render "Saved" instead of a duplicate Save button
    # rather than only finding out on a 409 from POST /api/jobs/{id}/save.
    already_saved_lead_id: Optional[str] = None
    already_saved_channel: list[str] = []


class AnonResumeUploadResponse(BaseModel):
    parsed_resume: ParsedResumeResponse
    inferred_criteria: InferredCriteriaResponse
    matched_jobs: list[MatchedJobResponse]


class AnonPreviewRequest(BaseModel):
    """The frontend sends back exactly what /api/anon/resume gave it --
    no server-side lookup, per this section's stateless design."""
    parsed_resume: dict
    job_id: str


class AnonPreviewResponse(BaseModel):
    job_id: str
    company_name: str
    role: str
    tailored_resume: dict
    keyword_coverage: float


def _build_company_name_map(jobs: list[dict]) -> dict[str, str]:
    """One-time lookup of company_id -> name for a batch of jobs, so we
    don't hit Postgres once per job when building the response."""
    from db.session import get_session
    from db.models import Company
    from sqlalchemy import select

    company_ids = {j["company_id"] for j in jobs if j.get("company_id")}
    if not company_ids:
        return {}

    with get_session() as session:
        rows = session.execute(
            select(Company.id, Company.name).where(Company.id.in_(company_ids))
        ).all()
        return {str(row[0]): row[1] for row in rows}


# ---------------------------------------------------------------------------
# Hero chat onboarding (v1 Task 9): a signed-in user attaches a resume and
# types who they're targeting; we parse -> infer criteria -> blend the target
# text -> match YC startups. The sign-in gate is enforced on the frontend
# (send intercepts an unauthenticated click and runs Google sign-in first),
# so this endpoint itself is authenticated like every other dashboard route.
# ---------------------------------------------------------------------------

_TARGET_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "are", "you", "your", "who",
    "want", "looking", "target", "targeting", "startups", "startup", "companies",
    "company", "roles", "role", "job", "jobs", "work", "working", "would", "like",
    "into", "some", "any", "help", "build", "building", "team", "teams", "using",
    "們", "a", "an", "in", "to", "of", "at", "on", "or",
}


def _blend_target_into_criteria(criteria: dict, target_text: str) -> dict:
    """Fold the user's free-text targeting prompt into the inferred criteria.

    match_jobs scores whole-word tech_stack + role keyword hits in a job's
    title/jd_text, so we add the meaningful tokens from the prompt to BOTH
    lists -- that's what makes "I'm targeting AI infra startups using Rust"
    actually bias the ranking toward those jobs, not just the resume."""
    import re

    tokens = [t for t in re.split(r"[^a-zA-Z0-9+#.]+", (target_text or "").lower()) if t]
    keywords = [t for t in tokens if len(t) >= 3 and t not in _TARGET_STOPWORDS]

    blended = dict(criteria)
    roles = list(blended.get("roles") or [])
    tech = list(blended.get("tech_stack") or [])
    for kw in keywords:
        if kw not in roles:
            roles.append(kw)
        if kw not in tech:
            tech.append(kw)
    blended["roles"] = roles
    blended["tech_stack"] = tech
    return blended


@app.post("/api/chat/match", response_model=AnonResumeUploadResponse)
async def chat_match(
    file: UploadFile = File(...),
    target: str = Form(""),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Hero-chat onboarding: parse the attached resume, infer criteria, blend
    in the free-text target prompt, and return matched YC startups. Persists
    the blended criteria to the user's account so the dashboard's matched-jobs
    feed keeps working afterward."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Allowed: .pdf, .docx, .txt")

    content = await file.read()
    if len(content) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB)")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    from skills.parse_resume import ResumeParseError, UnsupportedFileTypeError, parse_resume_cached

    try:
        parsed_resume, _raw = parse_resume_cached(content, filename, file.content_type or "")
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ResumeParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from skills.infer_criteria import infer_criteria
    from skills.match_jobs import match_jobs, matched_signals, score_job

    criteria = _blend_target_into_criteria(infer_criteria(parsed_resume), target)

    # Persist so /api/jobs/matched + the pipeline see this user's criteria.
    try:
        repo.upsert_search_criteria(user_id, criteria)
    except Exception as e:
        print(f"  ⚠️  chat_match: failed to persist criteria for {user_id}: {e}")

    # v1 is YC-focused: match only YC catalog jobs.
    yc_jobs = [j for j in repo.get_jobs(open_only=True) if j.get("source") == "yc"]
    company_names = _build_company_name_map(yc_jobs)
    matched = match_jobs(yc_jobs, criteria, limit=30)

    existing_by_job_id: dict[str, dict] = {}
    for lead in repo.get_leads(user_id):
        jid = lead.get("job_id")
        if jid:
            existing_by_job_id[str(jid)] = lead

    matched_response = []
    for job in matched:
        jid = str(job["id"])
        existing = existing_by_job_id.get(jid)
        matched_response.append(MatchedJobResponse(
            id=jid,
            company_name=company_names.get(str(job.get("company_id")), "Unknown Company"),
            title=job.get("title") or "",
            location=job.get("location"),
            department=job.get("department"),
            jd_text=job.get("jd_text"),
            apply_url=job.get("apply_url"),
            source=job.get("source") or "",
            match_score=score_job(job, criteria),
            matched_signals=matched_signals(job, criteria),
            already_saved_lead_id=str(existing["id"]) if existing else None,
            already_saved_channel=(existing.get("channel") or []) if existing else [],
        ))

    return AnonResumeUploadResponse(
        parsed_resume=ParsedResumeResponse(**parsed_resume),
        inferred_criteria=InferredCriteriaResponse(**criteria),
        matched_jobs=matched_response,
    )


@app.get("/api/jobs/matched", response_model=list[MatchedJobResponse])
def get_matched_jobs(user_id: str = Depends(get_authenticated_user_id)):
    """Signed-in equivalent of the anonymous /api/anon/resume feed below --
    match the shared catalog against the caller's own SAVED search
    criteria (the `search_criteria` table, populated by the anon-signup
    conversion flow or /api/profile/search-criteria), rather than a
    one-shot inferred set. This is the "wow" moment for a first-time
    signed-in user: real, ranked, save-able jobs, no waiting on a fresh
    resume upload if one was already done pre-signup.

    404s (via an empty list, not an HTTPException -- this is a normal,
    expected state for a brand-new account, not an error) when the user
    has no search criteria saved yet. The frontend distinguishes "no
    criteria yet" from "criteria but zero matches" by calling
    /api/profile/search-criteria separately (already 404s in that case) --
    this route deliberately doesn't duplicate that signal.
    """
    criteria = repo.get_search_criteria(user_id)
    if criteria is None:
        return []

    from skills.match_jobs import match_jobs, matched_signals, score_job

    # open_only=True: never surface a job whose company-side board no
    # longer lists it -- see db.repository.close_unseen_jobs/add_job for
    # how is_open stays accurate.
    all_jobs = repo.get_jobs(open_only=True)  # whole shared catalog -- no user_id, Phase 1's tables
    company_names = _build_company_name_map(all_jobs)
    matched = match_jobs(all_jobs, criteria, limit=50)

    # Look up which of these jobs the user already turned into a lead, so
    # the frontend can render "Saved" instead of risking a duplicate-save
    # 409 on click. One pass over the user's own leads (small, per-user),
    # keyed by job_id -- not per-job queries.
    existing_by_job_id: dict[str, dict] = {}
    for lead in repo.get_leads(user_id):
        job_id = lead.get("job_id")
        if job_id:
            existing_by_job_id[str(job_id)] = lead

    response = []
    for job in matched:
        job_id = str(job["id"])
        existing = existing_by_job_id.get(job_id)
        response.append(MatchedJobResponse(
            id=job_id,
            company_name=company_names.get(str(job.get("company_id")), "Unknown Company"),
            title=job.get("title") or "",
            location=job.get("location"),
            department=job.get("department"),
            jd_text=job.get("jd_text"),
            apply_url=job.get("apply_url"),
            source=job.get("source") or "",
            match_score=score_job(job, criteria),
            matched_signals=matched_signals(job, criteria),
            already_saved_lead_id=str(existing["id"]) if existing else None,
            already_saved_channel=(existing.get("channel") or []) if existing else [],
        ))

    return response


@app.post("/api/anon/resume", response_model=AnonResumeUploadResponse)
async def anon_upload_resume(request: Request, file: UploadFile = File(...)):
    """Anonymous resume upload: parse -> infer criteria -> match the
    shared catalog. One LLM call (the parse); everything else is pure
    Python/SQL, so this responds well within the 30-second budget.
    """
    resume_upload_limiter.check(get_client_ip(request))

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: .pdf, .docx, .txt",
        )

    content = await file.read()
    if len(content) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB)",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    from skills.parse_resume import (
        ResumeParseError,
        UnsupportedFileTypeError,
        parse_resume_cached,
    )

    try:
        parsed_resume, _raw_text = parse_resume_cached(
            content, filename, file.content_type or ""
        )
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ResumeParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from skills.infer_criteria import infer_criteria
    from skills.match_jobs import match_jobs

    inferred_criteria = infer_criteria(parsed_resume)

    # open_only=True: see the /api/jobs/matched route's identical comment.
    all_jobs = repo.get_jobs(open_only=True)  # whole shared catalog -- no user_id, Phase 1's tables
    company_names = _build_company_name_map(all_jobs)
    matched = match_jobs(all_jobs, inferred_criteria, limit=50)

    matched_response = [
        MatchedJobResponse(
            id=str(job["id"]),
            company_name=company_names.get(str(job.get("company_id")), "Unknown Company"),
            title=job.get("title") or "",
            location=job.get("location"),
            department=job.get("department"),
            jd_text=job.get("jd_text"),
            apply_url=job.get("apply_url"),
            source=job.get("source") or "",
        )
        for job in matched
    ]

    return AnonResumeUploadResponse(
        parsed_resume=ParsedResumeResponse(**parsed_resume),
        inferred_criteria=InferredCriteriaResponse(**inferred_criteria),
        matched_jobs=matched_response,
    )


@app.post("/api/anon/preview", response_model=AnonPreviewResponse)
def anon_tailored_preview(request: Request, body: AnonPreviewRequest):
    """Anonymous tailored-resume preview for one clicked job. A second,
    separate LLM call from /api/anon/resume -- rate-limited independently.
    """
    preview_limiter.check(get_client_ip(request))

    from db.session import get_session
    from db.models import Company, Job as JobModel
    from sqlalchemy import select

    # Pull out plain values (not ORM instances) while the session is still
    # open -- job_row/company_name would otherwise be detached the moment
    # the `with` block exits, and any attribute access after that raises
    # (SQLAlchemy can't lazy-refresh a detached instance without a session).
    with get_session() as session:
        row = session.execute(
            select(JobModel.id, JobModel.title, JobModel.jd_text, Company.name)
            .join(Company, JobModel.company_id == Company.id)
            .where(JobModel.id == body.job_id)
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {body.job_id} not found")

    job_id, job_title, job_jd_text, company_name = row

    from skills.tailor_resume import tailor_resume, keyword_coverage

    try:
        tailored = tailor_resume(
            base_resume=body.parsed_resume,
            company=company_name,
            role=job_title,
            jd_text=job_jd_text or "",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {e}")

    coverage = keyword_coverage(job_jd_text or "", tailored)

    return AnonPreviewResponse(
        job_id=str(job_id),
        company_name=company_name,
        role=job_title,
        tailored_resume=tailored,
        keyword_coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Account conversion (Phase 3.4) + Profile (Phase 3.7)
# ---------------------------------------------------------------------------
#
# convert-anon-session is the bridge from Phase 2's anonymous flow into a
# real account: the frontend sends back exactly what /api/anon/resume gave
# it (parsed_resume + inferred_criteria), now that the visitor has signed
# in with Google and we have a real user_id. No session migration needed
# -- the frontend already held everything in memory.
#
# The profile routes are the per-user counterpart to
# /api/settings/search-criteria (which reads/writes a single global
# config/search_criteria.json used by the CLI pipeline/scrapers -- see
# that route's docstring). These read/write the `search_criteria` and
# `resumes` tables, scoped to the authenticated user.


class ConvertAnonSessionRequest(BaseModel):
    """Exactly the shape /api/anon/resume returns -- see ParsedResumeResponse
    and InferredCriteriaResponse above."""
    parsed_resume: dict
    inferred_criteria: dict


class ConvertAnonSessionResponse(BaseModel):
    resume_id: str
    search_criteria_id: str


@app.post("/api/account/convert-anon-session", response_model=ConvertAnonSessionResponse)
def convert_anon_session(
    body: ConvertAnonSessionRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Persist a just-signed-in user's anonymous resume + inferred criteria.

    Idempotency: calling this more than once (e.g. a double-clicked sign-up,
    or a user who signs in again after a prior conversion) creates a NEW
    resume version each time rather than erroring or silently no-opping --
    resumes.is_primary tracks which one is current (the newest becomes
    primary, per repo.add_resume's demote-then-insert logic), consistent
    with the "resume versions" concept Phase 4's profile page builds on.
    search_criteria, by contrast, is upserted in place (repo.upsert_search_criteria
    already treats it as one-row-per-user) -- re-converting just refreshes
    the same criteria row rather than creating duplicates.
    """
    criteria = dict(body.inferred_criteria)
    criteria["inferred_from_resume"] = True

    resume = repo.add_resume(user_id, file_ref=None, parsed_json=body.parsed_resume, is_primary=True)
    saved_criteria = repo.upsert_search_criteria(user_id, criteria)

    return ConvertAnonSessionResponse(
        resume_id=str(resume["id"]),
        search_criteria_id=str(saved_criteria["id"]),
    )


class ProfileSearchCriteriaResponse(BaseModel):
    roles: list[str]
    tech_stack: list[str]
    seniority: Optional[str] = None
    locations: list[str]
    remote_pref: Optional[str] = None
    inferred_from_resume: bool


class ProfileSearchCriteriaUpdateRequest(BaseModel):
    roles: Optional[list[str]] = None
    tech_stack: Optional[list[str]] = None
    seniority: Optional[str] = None
    locations: Optional[list[str]] = None
    remote_pref: Optional[str] = None


class ProfileResumeResponse(BaseModel):
    id: str
    file_ref: Optional[str] = None
    parsed_json: Optional[dict] = None
    is_primary: bool
    created_at: str


@app.get("/api/profile/search-criteria", response_model=ProfileSearchCriteriaResponse)
def get_profile_search_criteria(user_id: str = Depends(get_authenticated_user_id)):
    """The signed-in user's own saved search criteria (per-user `search_criteria`
    table row) -- distinct from /api/settings/search-criteria's global pipeline
    config file. 404s if the user has never had criteria saved (e.g. signed in
    without ever running the anonymous resume hook)."""
    criteria = repo.get_search_criteria(user_id)
    if criteria is None:
        raise HTTPException(status_code=404, detail="No search criteria saved for this account yet")

    return ProfileSearchCriteriaResponse(
        roles=criteria.get("roles") or [],
        tech_stack=criteria.get("tech_stack") or [],
        seniority=criteria.get("seniority"),
        locations=criteria.get("locations") or [],
        remote_pref=criteria.get("remote_pref"),
        inferred_from_resume=bool(criteria.get("inferred_from_resume")),
    )


@app.put("/api/profile/search-criteria", response_model=ProfileSearchCriteriaResponse)
def update_profile_search_criteria(
    body: ProfileSearchCriteriaUpdateRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Edit the signed-in user's own search criteria. A field left as None
    keeps its existing saved value (repo.upsert_search_criteria only
    overwrites keys present in the dict) -- editing is partial, matching
    the existing /api/settings/search-criteria PUT's merge semantics.
    Editing here always sets inferred_from_resume=False, since a manual
    edit is no longer purely LLM-inferred.
    """
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["inferred_from_resume"] = False
    saved = repo.upsert_search_criteria(user_id, updates)

    return ProfileSearchCriteriaResponse(
        roles=saved.get("roles") or [],
        tech_stack=saved.get("tech_stack") or [],
        seniority=saved.get("seniority"),
        locations=saved.get("locations") or [],
        remote_pref=saved.get("remote_pref"),
        inferred_from_resume=bool(saved.get("inferred_from_resume")),
    )


@app.get("/api/profile/resumes", response_model=list[ProfileResumeResponse])
def list_profile_resumes(user_id: str = Depends(get_authenticated_user_id)):
    """The signed-in user's saved resume versions, newest first."""
    resumes = repo.get_resumes(user_id)
    return [
        ProfileResumeResponse(
            id=str(r["id"]),
            file_ref=r.get("file_ref"),
            parsed_json=r.get("parsed_json"),
            is_primary=bool(r.get("is_primary")),
            created_at=r["created_at"].isoformat() if r.get("created_at") else "",
        )
        for r in resumes
    ]


@app.post("/api/profile/upload-resume", response_model=ProfileResumeResponse)
async def profile_upload_resume(
    file: UploadFile = File(...),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Upload a new resume version for the authenticated user, parse it, set it
    as primary resume, and infer updated search criteria.
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: .pdf, .docx, .txt",
        )

    content = await file.read()
    if len(content) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB)",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    from skills.parse_resume import (
        ResumeParseError,
        UnsupportedFileTypeError,
        parse_resume_cached,
    )

    try:
        parsed_resume, _raw_text = parse_resume_cached(
            content, filename, file.content_type or ""
        )
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ResumeParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from skills.infer_criteria import infer_criteria
    inferred = infer_criteria(parsed_resume)
    inferred["inferred_from_resume"] = True

    new_resume = repo.add_resume(user_id, file_ref=filename, parsed_json=parsed_resume, is_primary=True)
    repo.upsert_search_criteria(user_id, inferred)

    created_iso = new_resume["created_at"].isoformat() if hasattr(new_resume.get("created_at"), "isoformat") else str(new_resume.get("created_at") or "")

    return ProfileResumeResponse(
        id=str(new_resume["id"]),
        file_ref=filename,
        parsed_json=parsed_resume,
        is_primary=True,
        created_at=created_iso,
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "autoapply-api"}


# ---------------------------------------------------------------------------
# Health / readiness probes (Phase 0 -- Cloud Run liveness/readiness checks)
# ---------------------------------------------------------------------------
#
# /health is a liveness probe: "is the process up and able to respond at
# all?" It does no I/O, so it can't be dragged down by a slow/dead dependency
# -- exactly what Cloud Run needs to decide whether to restart the container.
#
# /ready is a readiness probe: "can this instance actually serve traffic?"
# It checks the one hard dependency that matters -- the Postgres connection
# -- so Cloud Run (and a load balancer health check) can hold back traffic
# from an instance that's up but can't reach the database (e.g. during a
# Cloud SQL failover or before the Serverless VPC connector is attached).

@app.get("/health")
def liveness():
    """Liveness probe. Always returns 200 if the process can respond at all."""
    return {"status": "ok"}


@app.get("/ready")
def readiness():
    """Readiness probe. Returns 200 only if the database is reachable."""
    from sqlalchemy import text
    from db.session import get_engine

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database not reachable: {e}")

    return {"status": "ready", "db": "ok"}
