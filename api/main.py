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
import logging
from collections import deque

logger = logging.getLogger("uvicorn.error")
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
            print(f"[WARNING] Failed to start scheduler: {e}")

    yield

    if scheduler_started:
        try:
            from orchestrator.scheduler import stop_scheduler
            stop_scheduler()
        except Exception as e:
            print(f"[WARNING] Failed to stop scheduler cleanly: {e}")


app = FastAPI(
    title="Outra Pipeline API",
    description="REST API for the Outra pipeline dashboard",
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
        "https://outra.online",
        "https://www.outra.online",
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
    # ATS keyword-coverage % for the tailored resume (0-100), or None if the
    # resume hasn't been tailored yet. Surfaced so the UI can show a real
    # resume-readiness signal instead of inferring from resume_version.
    keyword_coverage: Optional[float] = None
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


class OutreachQuotaResponse(BaseModel):
    plan: str
    used: int
    limit: int
    remaining: int
    reset: Optional[str] = None  # null for lifetime credits (no reset); ISO ts otherwise


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


class StandaloneDemoBuildRequest(BaseModel):
    title: str
    description: str
    company_name: Optional[str] = None
    project_type: Optional[str] = "fullstack"
    max_attempts: Optional[int] = None


class RefineDemoRequest(BaseModel):
    prompt: str


class ProvideSecretsRequest(BaseModel):
    secrets: dict[str, str]


class DemoBuildStatusResponse(BaseModel):
    build_id: str
    lead_id: Optional[str] = "standalone"
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
    """Summary for the Builds list page."""
    build_id: str
    lead_id: Optional[str] = "standalone"
    company: Optional[str] = ""
    company_name: Optional[str] = ""
    demo_title: Optional[str] = ""
    title: Optional[str] = ""
    project_type: Optional[str] = "fullstack"
    running: bool
    stage: str
    deploy_stage: Optional[str] = None
    attempt: int
    max_attempts: int
    started_at: Optional[str] = ""
    repo_url: Optional[str] = None
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
        keyword_coverage=lead.get("keyword_coverage"),
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

    # Serve from the artifact store (GCS in prod, local resumes/ in dev) so the
    # PDF resolves regardless of which instance rendered it.
    from storage import artifact_store as store
    from fastapi.responses import Response

    pdf_bytes = store.get_bytes(f"{resume_version}.pdf")
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="Tailored resume PDF not found")

    # Serve with a clean, human-readable filename (name + company) instead of
    # the internal ID-bearing store key. The store key (resume_version) stays
    # untouched — it's only used to fetch the bytes above, never shown.
    download_name = _clean_resume_filename(user_id, lead)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{download_name}.pdf"'},
    )


def _clean_resume_filename(user_id: str, lead: dict) -> str:
    """Build a readable resume download filename as `{Name}_{Company}`.

    The candidate's name comes from the tailored-resume JSON (falling back to
    the user record), and the company from the lead. Sanitized to
    filesystem-safe characters (mirrors download_resume_pdf), falling back to
    a sensible default when a part is missing.
    """
    def _safe(value: str | None) -> str:
        return "".join(
            c for c in str(value or "") if c.isalnum() or c in (" ", "-", "_")
        ).strip().replace(" ", "_")

    # Name: prefer the tailored resume's own name, then the user record.
    name = ""
    resume_version = (lead.get("resume_version") or "").strip()
    if resume_version:
        try:
            from storage import artifact_store as store
            json_bytes = store.get_bytes(f"{resume_version}.json")
            if json_bytes:
                resume_json = json.loads(json_bytes.decode("utf-8"))
                name = (resume_json or {}).get("name") or ""
        except Exception:
            name = ""
    if not name:
        try:
            user = repo.get_user(user_id)
            name = (user or {}).get("name") or ""
        except Exception:
            name = ""

    company = lead.get("company") or lead.get("x_handle") or ""

    name_part = _safe(name)
    company_part = _safe(company)
    parts = [p for p in (name_part, company_part) if p]
    return "_".join(parts) or "resume"


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
    # M-2: distinguish "lead isn't paused in the graph" (a legitimate
    # reason to fall back to a direct status update) from "the graph resume
    # actually errored" (a real failure we must NOT silently paper over as
    # success). _approve returns False for the former and raises for the
    # latter; only the False path falls through to the direct update.
    try:
        from orchestrator.review_cli import approve_lead as _approve
        if _approve(lead_id, user_id=user_id, channel=channel):
            _invalidate_leads_cache(user_id)
            return {"status": "approved", "lead_id": lead_id, "via": "graph"}
    except Exception as e:
        logger.exception(f"approve_lead: graph resume errored for lead {lead_id} (user {user_id})")
        raise HTTPException(status_code=500, detail=f"Approve failed during graph resume: {e}")

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
        logger.exception(f"reject_lead: graph resume errored for lead {lead_id} (user {user_id})")
        raise HTTPException(status_code=500, detail=f"Reject failed during graph resume: {e}")

    try:
        repo.update_lead(user_id, lead_id, {"status": "rejected", "review_decision": "rejected"})
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    _invalidate_leads_cache(user_id)
    return {"status": "rejected", "lead_id": lead_id, "via": "direct"}


@app.delete("/api/leads/{lead_id}")
def delete_lead(lead_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Remove a lead from the user's pipeline entirely.

    Used by the dashboard's "remove from pipeline" action on a saved match:
    saving a matched catalog job creates a per-user Lead, and this is the
    inverse -- it deletes that Lead so the match flips back to an unsaved
    state the user can re-save. Scoped to user_id; returns 404 if the lead
    doesn't exist or belongs to another tenant.
    """
    deleted = repo.delete_lead(user_id, lead_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    _invalidate_leads_cache(user_id)
    return {"status": "removed", "lead_id": lead_id}


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
        logger.exception(f"edit_lead: graph resume errored for lead {lead_id} (user {user_id})")
        raise HTTPException(status_code=500, detail=f"Edit failed during graph resume: {e}")

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
    demo_project: Optional[dict] = None, user_id: str = "",
) -> None:
    with _demo_builds_registry_lock:
        _demo_builds[build_id] = {
            "state": state,
            "lead_id": lead_id,
            "user_id": user_id,
            "lock": threading.Lock(),
            "running": True,
            "company": company,
            "demo_title": demo_title,
            # Kept around so the resume-after-secrets path (which runs much
            # later, in a separate request) can chain into deploy_build()
            # with the same spec the build was originally started with.
            "demo_project": demo_project or {},
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    if user_id:
        try:
            repo.create_demo_build(
                user_id=user_id,
                build_id=build_id,
                title=demo_title or "Untitled Demo",
                company_name=company,
                project_type=(demo_project or {}).get("project_type", "fullstack"),
                spec_json=demo_project or {},
            )
        except Exception as e:
            print(f"  [WARN] Failed to persist demo build row to DB: {e}")


def _get_build_entry(build_id: str) -> Optional[dict]:
    with _demo_builds_registry_lock:
        return _demo_builds.get(build_id)


def _finish_build_and_deploy(
    entry: dict,
    demo_project: dict,
    company: str,
    user_id: Optional[str] = None,
    github_token: Optional[str] = None,
    vercel_token: Optional[str] = None,
    render_api_key: Optional[str] = None,
) -> None:
    """Shared tail end for both _run_build_bg and _resume_build_bg.
    
    Deploys to the user's connected GitHub repository, Vercel, and Render accounts.
    """
    from sandbox import orchestrator

    state = entry["state"]

    if state.stage == "success":
        orchestrator.finalize_success(state)  # export BEFORE teardown

    if state.stage in ("success", "failed"):
        orchestrator.stop_build(state)  # container no longer needed either way

    if state.stage == "success" and state.project_dir:
        # Load user's connected provider keys from database
        user_id_val = user_id or entry.get("user_id")
        if user_id_val:
            try:
                user_keys = repo.get_user_provider_keys(user_id_val)
                github_token = github_token or user_keys.get("github_token")
                vercel_token = vercel_token or user_keys.get("vercel_token")
                render_api_key = render_api_key or user_keys.get("render_api_key")
            except Exception as e:
                print(f"  [WARN] Could not retrieve user provider keys: {e}")

        # Fall back to server environment variables if not set
        github_token = github_token or os.getenv("GITHUB_TOKEN")
        vercel_token = vercel_token or os.getenv("VERCEL_TOKEN")
        render_api_key = render_api_key or os.getenv("RENDER_API_KEY")

        orchestrator.deploy_build(
            state,
            demo_project,
            company,
            github_token=github_token,
            vercel_token=vercel_token,
            render_api_key=render_api_key,
            project_type=demo_project.get("project_type", "fullstack"),
        )

        # Update persistent DB record with deployed URLs
        if user_id_val:
            try:
                repo.update_demo_build_status(
                    user_id=user_id_val,
                    build_id=state.build_id,
                    stage=state.stage,
                    deploy_stage=state.deploy_stage,
                    repo_url=state.repo_url,
                    frontend_url=state.frontend_url,
                    backend_url=state.backend_url,
                )
            except Exception as e:
                print(f"  [WARN] Failed to update DemoBuild in DB: {e}")


def _run_build_bg(
    build_id: str,
    demo_project: dict,
    company: str,
    max_attempts: int,
    user_id: str = "",
    github_token: Optional[str] = None,
    vercel_token: Optional[str] = None,
    render_api_key: Optional[str] = None,
):
    """Background worker: runs the (blocking) build loop, then marks it done."""
    from sandbox import orchestrator, gcp_job_executor

    entry = _get_build_entry(build_id)
    state = entry["state"]
    try:
        if gcp_job_executor.is_gcp_sandbox_enabled():
            gcp_job_executor.launch_gcp_cloud_run_job(
                build_id=build_id,
                demo_project=demo_project,
                company=company,
                github_token=github_token,
                max_attempts=max_attempts,
            )
            state.stage = "building"
        else:
            orchestrator.start_build(
                demo_project=demo_project,
                company=company,
                max_attempts=max_attempts,
                state=state,  # mutate the SAME object callers are already polling
            )
            _finish_build_and_deploy(
                entry,
                demo_project,
                company,
                user_id=user_id,
                github_token=github_token,
                vercel_token=vercel_token,
                render_api_key=render_api_key,
            )
    except Exception as e:
        state.stage = "failed"
        if state.deploy_stage and state.deploy_stage not in ("deployed", "deploy_failed"):
            state.deploy_stage = "deploy_failed"
        state.error = f"Unexpected orchestrator error: {e}"
        state.deploy_error = state.deploy_error or str(e)
        if user_id:
            try:
                repo.update_demo_build_status(
                    user_id=user_id,
                    build_id=build_id,
                    stage="failed",
                    deploy_stage="deploy_failed",
                )
            except Exception:
                pass
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
    Capped at 5 demo builds per user per 24 hours.
    """
    from sandbox.orchestrator import BuildState
    from sandbox.config import DEFAULT_MAX_ATTEMPTS
    from api.rate_limit import demo_build_limiter

    # Enforce 5 demos/day quota per user
    demo_build_limiter.check(f"user_demo:{user_id}")

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
        user_id=user_id,
    )
    threading.Thread(
        target=_run_build_bg,
        args=(state.build_id, demo_project_dict, company, max_attempts, user_id),
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
            repo_url=state.repo_url,
            frontend_url=state.frontend_url,
            backend_url=state.backend_url,
        ))

    summaries.sort(key=lambda s: (s.started_at or ""), reverse=True)
    return summaries


@app.get("/api/demos", response_model=list[DemoBuildSummary])
def list_demos(user_id: str = Depends(get_authenticated_user_id)):
    """List all demo builds for the Demo Studio page."""
    from sandbox.config import DEFAULT_MAX_ATTEMPTS

    with _demo_builds_registry_lock:
        entries = list(_demo_builds.items())

    summaries = []
    seen_ids = set()
    for build_id, entry in entries:
        entry_user = entry.get("user_id")
        if entry_user and entry_user != user_id:
            continue
        seen_ids.add(build_id)
        state = entry["state"]
        with entry["lock"]:
            running = entry["running"]
        company_val = entry.get("company", "") or entry.get("company_name", "")
        title_val = entry.get("demo_title", "") or entry.get("title", "")
        summaries.append(DemoBuildSummary(
            build_id=build_id,
            lead_id=entry.get("lead_id", "standalone"),
            company=company_val,
            company_name=company_val,
            demo_title=title_val,
            title=title_val,
            project_type=entry.get("project_type", "fullstack"),
            running=running,
            stage=state.stage,
            deploy_stage=state.deploy_stage,
            attempt=state.attempt,
            max_attempts=state.max_attempts,
            started_at=entry.get("started_at", ""),
            repo_url=state.repo_url,
            frontend_url=state.frontend_url,
            backend_url=state.backend_url,
        ))

    # Merge persisted historical demo builds from Postgres
    try:
        db_builds = repo.list_user_demo_builds(user_id)
        for row in db_builds:
            bid = row.get("build_id")
            if bid and bid not in seen_ids:
                seen_ids.add(bid)
                summaries.append(DemoBuildSummary(
                    build_id=bid,
                    lead_id="standalone",
                    company=row.get("company_name", ""),
                    company_name=row.get("company_name", ""),
                    demo_title=row.get("title", ""),
                    title=row.get("title", ""),
                    project_type=row.get("project_type", "fullstack"),
                    running=False,
                    stage=row.get("stage", "success"),
                    deploy_stage=row.get("deploy_stage", "deployed"),
                    attempt=1,
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                    started_at=str(row.get("created_at") or ""),
                    repo_url=row.get("repo_url"),
                    frontend_url=row.get("frontend_url"),
                    backend_url=row.get("backend_url"),
                ))
    except Exception as e:
        print(f"  [WARN] Failed to load persisted user demo builds: {e}")

    summaries.sort(key=lambda s: (s.started_at or ""), reverse=True)
    return summaries


@app.get("/api/demos/quota")
def get_demos_quota(user_id: str = Depends(get_authenticated_user_id)):
    """Get the current user's daily demo quota usage."""
    from api.rate_limit import demo_build_limiter
    now = time.monotonic()
    key = f"user_demo:{user_id}"
    with demo_build_limiter._lock:
        hits = demo_build_limiter._hits.get(key, deque())
        while hits and hits[0] <= now - demo_build_limiter.window_seconds:
            hits.popleft()
        used = len(hits)
        limit = demo_build_limiter.max_requests

    return {
        "user_id": user_id,
        "date": datetime.now(timezone.utc).date().isoformat(),
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used)
    }


@app.post("/api/demos/build", response_model=DemoBuildStatusResponse)
def build_standalone_demo(body: StandaloneDemoBuildRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Start a standalone demo build from the AI Demo Studio page."""
    from sandbox.orchestrator import BuildState
    from sandbox.config import DEFAULT_MAX_ATTEMPTS
    from api.rate_limit import demo_build_limiter

    demo_build_limiter.check(f"user_demo:{user_id}")

    max_attempts = body.max_attempts or DEFAULT_MAX_ATTEMPTS
    state = BuildState(build_id=str(uuid.uuid4())[:8], max_attempts=max_attempts)
    demo_project_dict = {
        "title": body.title,
        "description": body.description,
        "company_name": body.company_name or "",
        "project_type": body.project_type or "fullstack",
    }

    _register_build(
        state.build_id, "standalone", state,
        company=body.company_name or "", demo_title=body.title, demo_project=demo_project_dict,
        user_id=user_id,
    )
    threading.Thread(
        target=_run_build_bg,
        args=(state.build_id, demo_project_dict, body.company_name or "", max_attempts, user_id),
        daemon=True,
    ).start()

    return DemoBuildStatusResponse(
        build_id=state.build_id,
        lead_id="standalone",
        running=True,
        stage=state.stage,
        attempt=state.attempt,
        max_attempts=state.max_attempts,
    )


@app.post("/api/demos/{build_id}/refine", response_model=DemoBuildStatusResponse)
def refine_demo(build_id: str, body: RefineDemoRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Request AI refinements/updates for an existing demo build."""
    entry = _get_build_entry(build_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    state = entry["state"]
    demo_project = entry.get("demo_project", {})
    company = entry.get("company", "")

    demo_project["description"] = f"{demo_project.get('description', '')}\n\nRefinement Request: {body.prompt}"

    with entry["lock"]:
        entry["running"] = True

    user_id_val = entry.get("user_id", user_id)
    threading.Thread(
        target=_run_build_bg,
        args=(build_id, demo_project, company, state.max_attempts, user_id_val),
        daemon=True,
    ).start()

    return DemoBuildStatusResponse(
        build_id=build_id,
        lead_id=entry.get("lead_id", "standalone"),
        running=True,
        stage="building",
        attempt=state.attempt,
        max_attempts=state.max_attempts,
        repo_url=state.repo_url,
        frontend_url=state.frontend_url,
        backend_url=state.backend_url,
    )


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


@app.get("/api/outreach/quota", response_model=OutreachQuotaResponse)
def get_outreach_quota_route(user_id: str = Depends(get_authenticated_user_id)):
    """The caller's LIFETIME credit balance — the single source of truth for
    the "credits left" card. 1 credit = 1 completed-pipeline lead (reached
    sent/draft_created). `used` counts those leads for the lifetime of the
    account; `limit` is the plan's lifetime allowance (free=25); `reset` is
    null because credits never reset."""
    q = repo.get_outreach_quota(user_id)
    return OutreachQuotaResponse(**q)


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
            repo.append_pipeline_run_step(run_id, label, status, user_id=user_id)
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
        repo.update_pipeline_run(run_id, {"status": "completed", "summary": summary}, user_id=user_id)
    except Exception as e:
        repo.update_pipeline_run(run_id, {"status": "failed", "error": str(e)}, user_id=user_id)
    finally:
        # New leads were likely written to Postgres — drop the cache so the
        # next dashboard/leads read reflects them.
        _invalidate_leads_cache(user_id)
        repo.update_pipeline_run(run_id, {"current_step": None, "finished_at": datetime.now(timezone.utc)}, user_id=user_id)


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


def _require_sufficient_credits(user_id: str, requested_leads: int) -> None:
    """Reject a pipeline start when the user lacks enough credits for the
    number of leads it will attempt.

    1 credit = 1 lead that completes to a real outreach (tailored resume +
    draft/sent). We gate the run up front against the user's remaining
    balance (the backend source of truth from get_outreach_quota) so a run can
    never process more leads than the user can pay for. Raises HTTP 402 with a
    clear {needed, remaining} message when the balance is insufficient.
    """
    needed = max(1, int(requested_leads or 0))
    quota = repo.get_outreach_quota(user_id)
    remaining = int(quota.get("remaining", 0))
    if remaining < needed:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Not enough credits: this run needs {needed} "
                f"credit{'s' if needed != 1 else ''} but you have {remaining} left. "
                "Reduce the number of leads or upgrade your plan."
            ),
        )


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

    # v1: YC is the only automated source (all other boards parked).
    sources = body.sources or ["yc"]
    yc_max = min(max(1, body.yc_max_leads or 5), 15)

    # Pre-flight credit check: each lead that completes to a real outreach
    # (tailored resume + draft/sent) burns 1 credit, so require enough credits
    # for the number of leads this run will attempt before starting.
    _require_sufficient_credits(user_id, yc_max)

    run = repo.create_pipeline_run(user_id)
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
            repo.append_pipeline_run_step(run_id, label, status, user_id=user_id)
        except Exception as e:
            print(f"  ⚠️  pipeline run {run_id}: failed to record step '{label}': {e}")

    try:
        summary = run_pipeline_for_leads(user_id=user_id, lead_ids=lead_ids, progress_callback=on_step)
        repo.update_pipeline_run(run_id, {"status": "completed", "summary": summary}, user_id=user_id)
    except Exception as e:
        repo.update_pipeline_run(run_id, {"status": "failed", "error": str(e)}, user_id=user_id)
    finally:
        _invalidate_leads_cache(user_id)
        repo.update_pipeline_run(run_id, {"current_step": None, "finished_at": datetime.now(timezone.utc)}, user_id=user_id)


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

    # Pre-flight credit check: 1 credit per lead that completes to outreach.
    _require_sufficient_credits(user_id, len(body.lead_ids))

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
# Routes: Internal scheduled triggers (Cloud Scheduler cron jobs)
# ---------------------------------------------------------------------------

def _verify_internal_request(request: Request) -> None:
    """Guard for /api/internal/* Cloud Scheduler endpoints (C-3).

    These endpoints trigger backend work (catalog refresh, per-tenant
    follow-up sweeps) and are NOT behind Firebase auth, since Cloud
    Scheduler can't mint a user token. Historically they relied solely on
    Cloud Run ingress IAM; this adds a defense-in-depth shared-secret
    header check.

    Behavior: if INTERNAL_TASK_SECRET is set (prod), the request MUST carry
    a matching `X-Internal-Secret` header or it's rejected 401. If the
    secret is NOT set (local dev), the check is skipped so `docker compose`
    / local cron keeps working — matching the codebase's existing
    env-flag-gated posture. Configure the secret in prod AND pass it from
    the Cloud Scheduler job (--headers=X-Internal-Secret=...).
    """
    import hmac

    secret = os.getenv("INTERNAL_TASK_SECRET", "")
    if not secret:
        return  # not configured (local dev) -> skip, same as USE_CLOUD_TASKS spirit
    provided = request.headers.get("x-internal-secret", "")
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Missing or invalid internal task secret")


@app.post("/api/internal/catalog-refresh")
def internal_catalog_refresh(request: Request, providers: Optional[list[str]] = None):
    """Sync the shared job catalog (companies/jobs) from YC and ATS boards.
    Triggered daily by Google Cloud Scheduler (catalog-refresh-job).

    Catalog is a shared, cross-tenant resource (companies/jobs have no
    user_id), so this legitimately runs once, not per user.
    """
    _verify_internal_request(request)
    try:
        from orchestrator.pipeline_runner import run_catalog_refresh
        summary = run_catalog_refresh(providers=providers or ["yc"])
        return {"status": "success", "summary": summary}
    except Exception as e:
        print(f"  ❌ internal_catalog_refresh error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/internal/check-followups")
def internal_check_followups(request: Request):
    """Triggered daily by Google Cloud Scheduler (followups-check-job) to
    monitor outreach threads for EVERY tenant (C-2).

    Unlike the catalog refresh, follow-ups are per-user data, so this
    sweeps all users and runs each scoped to their own user_id — the old
    no-arg run_followup_pipeline() silently checked only the single
    db.current_user operator, so real tenants' sent leads were never
    followed up in production.
    """
    _verify_internal_request(request)
    try:
        from orchestrator.pipeline_runner import run_followup_pipeline

        user_ids = repo.get_all_user_ids()
        results = []
        ok = 0
        failed = 0
        for user_id in user_ids:
            try:
                summary = run_followup_pipeline(user_id=user_id)
                results.append({"user_id": user_id, "ok": True, "summary": summary})
                ok += 1
            except Exception as e:
                print(f"  ❌ internal_check_followups error for user {user_id}: {e}")
                results.append({"user_id": user_id, "ok": False, "error": str(e)})
                failed += 1
        return {
            "status": "success",
            "users_swept": len(user_ids),
            "ok": ok,
            "failed": failed,
            "results": results,
        }
    except Exception as e:
        print(f"  ❌ internal_check_followups error: {e}")
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
        print(f"[GMAIL CALLBACK] ERROR from Google: {error}", flush=True)
        return RedirectResponse(f"{frontend}/settings?gmail=error")
    if not code or not state:
        print(f"[GMAIL CALLBACK] Missing code={bool(code)} state={bool(state)}", flush=True)
        return RedirectResponse(f"{frontend}/settings?gmail=error")

    try:
        result = gmail_oauth.exchange_code_for_account(code, state)
    except gmail_oauth.GmailOAuthStateError as e:
        print(f"[GMAIL CALLBACK] State error: {e}", flush=True)
        return RedirectResponse(f"{frontend}/settings?gmail=state_error")
    except gmail_oauth.GmailOAuthConfigError as e:
        print(f"[GMAIL CALLBACK] Config error: {e}", flush=True)
        return RedirectResponse(f"{frontend}/settings?gmail=config_error")
    except Exception as e:
        import traceback
        print(f"[GMAIL CALLBACK] Exchange FAILED: {e}", flush=True)
        traceback.print_exc()
        return RedirectResponse(f"{frontend}/settings?gmail=error")

    print(f"[GMAIL CALLBACK] Exchange OK: user={result['user_id']} email={result['email']}", flush=True)

    try:
        encrypted = gmail_oauth.encrypt_token(result["refresh_token"])
        repo.upsert_gmail_account(
            user_id=result["user_id"],
            email=result["email"],
            encrypted_refresh_token=encrypted,
            scopes=result["scopes"],
            send_mode=result["send_mode"],
        )
    except Exception as e:
        import traceback
        print(f"[GMAIL CALLBACK] Upsert FAILED: {e}", flush=True)
        traceback.print_exc()
        return RedirectResponse(f"{frontend}/settings?gmail=error")

    print(f"[GMAIL CALLBACK] SUCCESS — redirecting to {frontend}/settings?gmail=connected", flush=True)
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
    # C-1: per-user now. Read the caller's own saved criteria; if they have
    # none yet, fall back to the shared config/search_criteria.json as the
    # DEFAULT seed (read-only) so a brand-new user still gets sensible
    # starting keywords -- but their edits go to their own row, never the
    # shared file.
    settings = repo.get_user_settings(user_id) or {}
    data = settings.get("search_criteria") or {}

    if not data:
        path = _get_search_criteria_path()
        if os.path.exists(path):
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
    """Update the CALLER's search criteria (C-1: per-user now).

    Writes to the caller's own user_settings.search_criteria JSONB instead
    of the shared config/search_criteria.json, so one tenant's keyword
    edits can never leak into another tenant's scraping/matching config.
    """
    updates: dict = {}
    if body.role_keywords is not None:
        updates["role_keywords"] = body.role_keywords
    if body.tech_stack_keywords is not None:
        updates["tech_stack_keywords"] = body.tech_stack_keywords
    if body.seniority_exclude_keywords is not None:
        updates["seniority_exclude_keywords"] = body.seniority_exclude_keywords
    if body.non_tech_exclude_keywords is not None:
        updates["non_tech_exclude_keywords"] = body.non_tech_exclude_keywords
    if body.years_experience_threshold is not None:
        updates["years_experience_threshold"] = body.years_experience_threshold
    if body.location_keywords is not None:
        updates["location_keywords"] = body.location_keywords

    row = repo.update_user_settings(user_id, search_criteria=updates) if updates else (repo.get_user_settings(user_id) or {})
    return {"status": "updated", "data": row.get("search_criteria", {}) if isinstance(row, dict) else {}}


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
    """Get the CALLER's pipeline configuration (C-1: per-user now).

    followup_days / max_followups / gmail_direct_send are read from the
    user's own user_settings row, falling back to the process-level
    env default when the user hasn't set them. model_backend stays an
    operator/infra-level value (which LLM backend the deployment uses is a
    cost/ops decision, not a per-tenant preference) so it's still read from
    the environment and is NOT writable per-user.
    """
    settings = repo.get_user_settings(user_id) or {}
    pc = settings.get("pipeline_config") or {}

    def _int_default(env_key: str, fallback: int) -> int:
        try:
            return int(_read_env_value(env_key, str(fallback)))
        except (ValueError, TypeError):
            return fallback

    return PipelineConfigResponse(
        model_backend=_read_env_value("MODEL_BACKEND", "vertex"),
        followup_days=int(pc.get("followup_days", _int_default("FOLLOWUP_DAYS", 5))),
        max_followups=int(pc.get("max_followups", _int_default("MAX_FOLLOWUPS", 1))),
        gmail_direct_send=bool(
            pc["gmail_direct_send"] if "gmail_direct_send" in pc
            else _read_env_value("GMAIL_DIRECT_SEND", "false").lower() == "true"
        ),
    )


@app.put("/api/settings/pipeline-config")
def update_pipeline_config(body: PipelineConfigUpdateRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Update the CALLER's pipeline configuration (C-1: per-user now).

    Writes to the caller's own user_settings row instead of the shared
    config/.env, so one tenant's change can never affect another's.
    model_backend is intentionally ignored here (operator/infra-level, set
    via deployment env, not per-tenant) -- accepting it silently in the
    request body but not persisting it keeps the existing UI contract
    without reintroducing a global write.
    """
    updates: dict = {}
    if body.followup_days is not None:
        updates["followup_days"] = int(body.followup_days)
    if body.max_followups is not None:
        updates["max_followups"] = int(body.max_followups)
    if body.gmail_direct_send is not None:
        updates["gmail_direct_send"] = bool(body.gmail_direct_send)

    if updates:
        repo.update_user_settings(user_id, pipeline_config=updates)

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

# Max characters of job-description text we feed the tailoring LLM. Real JDs
# are well under this (~1-3k words); beyond it the extra text is almost always
# boilerplate (benefits, legal, EEO) that dilutes the signal and pushes the
# model toward hallucination/keyword-stuffing. We hard-clip at this length and
# tell the caller. ~12k chars ≈ 3k tokens, comfortably within budget.
MAX_JD_CHARS = 12000

# Catalog sources surfaced in the user-facing match feeds (signed-in
# /api/jobs/matched + anonymous /api/anon/resume). Only YC is live right
# now; the other scraped sources (greenhouse/lever/ashby/jobicy/…) are
# parked -- their rows still live in the catalog and the scrapers still
# run, but they're filtered out of matches until we un-park them by adding
# their source keys here.
MATCH_SOURCES = ["yc"]


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


class JobSearchResult(BaseModel):
    """One search hit for the Matches search bar.

    `origin` distinguishes the two tiers:
      - "catalog": already in our synced YC catalog (has a real job `id`, so
        it saves through the normal /api/jobs/{id}/save path).
      - "live_yc": found in the live YC directory but not in our catalog
        (e.g. not currently hiring). It has no job `id` yet -- saving it goes
        through /api/jobs/search/save, which materializes a catalog row first.
    `is_hiring` lets the UI flag cold-outreach candidates ("not actively
    hiring — send a cold intro").
    """
    origin: str  # "catalog" | "live_yc"
    id: Optional[str] = None  # catalog job id (None for live_yc until saved)
    company_name: str
    title: str
    apply_url: Optional[str] = None
    source: str = "yc"
    is_hiring: bool = True
    # yc directory identity, needed to save a live_yc result:
    slug: Optional[str] = None
    website: Optional[str] = None
    jd_text: Optional[str] = None
    already_saved_lead_id: Optional[str] = None


class JobSearchResponse(BaseModel):
    query: str
    results: list[JobSearchResult]


class SaveColdCompanyRequest(BaseModel):
    """Save a live-YC company (not in our catalog) as a cold-outreach lead."""
    slug: str
    company_name: str
    website: Optional[str] = None
    jd_text: Optional[str] = None
    apply_url: Optional[str] = None


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

    # v1 is YC-focused: match only YC catalog jobs (MATCH_SOURCES). Filtered
    # at the DB level so the other sources stay parked, same as the other
    # match feeds (/api/jobs/matched, /api/anon/resume).
    yc_jobs = repo.get_jobs(open_only=True, sources=MATCH_SOURCES)
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
    # sources=MATCH_SOURCES: only YC for now -- the other catalog sources
    # (greenhouse/lever/ashby/…) are parked, so we don't surface them here.
    all_jobs = repo.get_jobs(open_only=True, sources=MATCH_SOURCES)  # shared catalog, YC-only
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


@app.get("/api/jobs/search", response_model=JobSearchResponse)
def search_jobs(
    q: str = Query(..., min_length=1, description="Company name to search for"),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Search YC companies by name for the Matches search bar (two tiers):

      1) Local catalog first -- instant search over the YC companies/jobs we
         already sync (MATCH_SOURCES). These are actively-hiring roles.
      2) Live YC fallback -- if a company isn't in our catalog (not currently
         hiring, or an older batch we don't sync), we look it up in the full
         YC directory (all.json) so the user can still cold-mail it. These
         come back with origin="live_yc" and is_hiring reflecting the
         directory, and are saved via /api/jobs/search/save.

    Local hits always rank above live hits, and we suppress live duplicates of
    companies already present in the catalog.
    """
    query = (q or "").strip()
    if not query:
        return JobSearchResponse(query=query, results=[])

    # Which of the user's leads are already saved, keyed by job_id, so a
    # catalog result can render as "Saved" instead of risking a 409.
    existing_by_job_id: dict[str, dict] = {}
    for lead in repo.get_leads(user_id):
        jid = lead.get("job_id")
        if jid:
            existing_by_job_id[str(jid)] = lead

    results: list[JobSearchResult] = []
    seen_company_names: set[str] = set()

    # Tier 1 — local catalog (YC only).
    catalog_hits = repo.search_jobs_by_company(
        query, open_only=True, sources=MATCH_SOURCES, limit=20
    )
    for job in catalog_hits:
        name = job.get("company_name") or "Unknown Company"
        seen_company_names.add(name.strip().lower())
        existing = existing_by_job_id.get(str(job.get("id")))
        results.append(JobSearchResult(
            origin="catalog",
            id=str(job.get("id")),
            company_name=name,
            title=job.get("title") or "",
            apply_url=job.get("apply_url"),
            source=job.get("source") or "yc",
            is_hiring=True,
            jd_text=job.get("jd_text"),
            already_saved_lead_id=str(existing["id"]) if existing else None,
        ))

    # Tier 2 — live YC directory fallback (cold-mail candidates). Only bother
    # if the local catalog gave us little/nothing, and skip companies we
    # already surfaced from the catalog.
    if len(results) < 10:
        try:
            from skills.scrape_job_boards.yc_startups import search_companies
            live = search_companies(query, limit=10)
        except Exception as e:
            logger.warning(f"search_jobs: live YC lookup failed for '{query}': {e}")
            live = []
        for c in live:
            name = (c.get("company") or "").strip()
            if not name or name.lower() in seen_company_names:
                continue
            seen_company_names.add(name.lower())
            results.append(JobSearchResult(
                origin="live_yc",
                id=None,
                company_name=name,
                title=c.get("role") or f"Engineering @ {name}",
                apply_url=c.get("listing_url"),
                source="yc",
                is_hiring=bool(c.get("is_hiring")),
                slug=c.get("slug"),
                website=c.get("website"),
                jd_text=c.get("jd_text"),
            ))

    return JobSearchResponse(query=query, results=results)


@app.post("/api/jobs/search/save", response_model=LeadResponse)
def save_cold_company(
    body: SaveColdCompanyRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Save a live-YC company (found via /api/jobs/search but not in our
    catalog) as a per-user cold-outreach lead.

    We first materialize the company + a placeholder job in the shared
    catalog (same shape as the daily YC catalog sync: Company ats_type="yc",
    Job source="yc", external_id=slug), so the row is deduped/reusable and
    downstream email discovery can resolve the company domain. Then we create
    the lead against that catalog job via the normal save path.
    """
    slug = (body.slug or "").strip()
    name = (body.company_name or "").strip()
    if not slug or not name:
        raise HTTPException(status_code=400, detail="slug and company_name are required")

    # Materialize the catalog company + job (idempotent on re-save).
    company = repo.get_or_create_company(name=name, ats_type="yc", ats_token=slug)
    website = (body.website or "").strip()
    apply_url = (body.apply_url or website or f"https://www.ycombinator.com/companies/{slug}").strip()
    job = repo.add_job(
        company["id"],
        source="yc",
        external_id=slug,
        title=f"Engineering @ {name}",
        location="Remote/Unspecified",
        department="Engineering",
        jd_text=body.jd_text or "",
        apply_url=apply_url,
        posted_at=None,
    )
    # add_job returns None if the job already existed -- fetch it either way.
    if job is None:
        job = next(
            (j for j in repo.get_jobs(company_id=company["id"]) if j.get("external_id") == slug),
            None,
        )
    if job is None:
        raise HTTPException(status_code=500, detail="Failed to materialize catalog job for company")

    # Derive a real domain from the website (skip ATS/YC hosts), mirroring
    # the /api/jobs/{id}/save path so email discovery has something to work with.
    domain = ""
    if website:
        try:
            from urllib.parse import urlparse
            host = urlparse(website if "://" in website else f"https://{website}").netloc
            domain = host.replace("www.", "").strip()
            if any(b in domain for b in ("greenhouse.io", "lever.co", "ashbyhq.com", "ycombinator.com")):
                domain = ""
        except Exception:
            domain = ""

    try:
        lead = repo.add_lead(user_id, {
            "job_id": job["id"],
            "channel": ["outreach"],
            "source": "yc",
            "company": name,
            "role": f"Engineering @ {name}",
            "jd_text": body.jd_text or "",
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

    # open_only=True + sources=MATCH_SOURCES: see the /api/jobs/matched
    # route's identical comment -- YC-only, other sources parked.
    all_jobs = repo.get_jobs(open_only=True, sources=MATCH_SOURCES)  # shared catalog, YC-only
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
    # True when parsing degraded (LLM truncation/failure fell back to the
    # heuristic). The frontend surfaces a "we couldn't fully read your resume,
    # please re-upload" prompt instead of silently trusting a gutted parse.
    parse_incomplete: bool = False
    parse_warning: Optional[str] = None


class BaseResumeResponse(BaseModel):
    """The user's current base (primary) resume, for the Resume page's editor."""
    resume_id: Optional[str] = None
    parsed_json: Optional[dict] = None
    has_resume: bool = False


class RephraseRequest(BaseModel):
    """Live rephrase of the base resume against a JD / freeform instruction.
    Preview only — nothing is persisted."""
    jd_text: str
    company: Optional[str] = None
    role: Optional[str] = None
    template: Optional[str] = "jake"  # standard | jake


class RephraseResponse(BaseModel):
    base_json: dict
    tailored_json: dict
    keyword_coverage: float
    ats_below_floor: bool
    model_used: str
    escalated: bool
    template: str
    # Positional change-map for live highlighting (see diff_resumes).
    diff: dict
    # True when the pasted JD exceeded max_jd_chars and was clipped.
    jd_truncated: bool = False
    max_jd_chars: int = MAX_JD_CHARS


class TailoredResumeResponse(BaseModel):
    id: str
    lead_id: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    keyword_coverage: Optional[float] = None
    template: str = "jake"
    model_used: Optional[str] = None
    source: str
    created_at: str
    tailored_json: Optional[dict] = None


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


class SaveResumeVersionRequest(BaseModel):
    """Save an edited/tailored resume JSON as a new named version (NOT the
    primary — the base resume stays the tailoring source of truth). The name
    is what shows in the Resume-page selector dropdown."""
    parsed_json: dict
    name: Optional[str] = None
    is_primary: bool = False


@app.post("/api/profile/resumes", response_model=ProfileResumeResponse)
def save_profile_resume(
    body: SaveResumeVersionRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Persist a resume JSON the user tailored/edited on the Resume page as a
    saved version they can re-select later from the dropdown. Stored as a
    non-primary version by default so it never silently replaces the base
    resume the pipeline tailors from.
    """
    if not body.parsed_json:
        raise HTTPException(status_code=400, detail="parsed_json is required")

    name = (body.name or "").strip() or (body.parsed_json.get("name") or "Saved resume")
    saved = repo.add_resume(
        user_id,
        file_ref=name,
        parsed_json=body.parsed_json,
        is_primary=bool(body.is_primary),
    )
    return ProfileResumeResponse(
        id=str(saved["id"]),
        file_ref=saved.get("file_ref"),
        parsed_json=saved.get("parsed_json"),
        is_primary=bool(saved.get("is_primary")),
        created_at=saved["created_at"].isoformat() if saved.get("created_at") else "",
    )


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

    # Separate the internal parse-quality markers from the resume content we
    # actually store, so a degraded parse is surfaced to the user rather than
    # silently saved as their clean primary resume.
    parse_incomplete = bool(parsed_resume.pop("_parse_incomplete", False))
    parse_warning = parsed_resume.pop("_parse_error", None) if parse_incomplete else None

    from skills.infer_criteria import infer_criteria
    inferred = infer_criteria(parsed_resume)
    inferred["inferred_from_resume"] = True

    new_resume = repo.add_resume(user_id, file_ref=filename, parsed_json=parsed_resume, is_primary=True)
    # Only refresh search criteria from a resume we actually parsed well —
    # criteria inferred from a gutted resume would be wrong.
    if not parse_incomplete:
        repo.upsert_search_criteria(user_id, inferred)

    created_iso = new_resume["created_at"].isoformat() if hasattr(new_resume.get("created_at"), "isoformat") else str(new_resume.get("created_at") or "")

    return ProfileResumeResponse(
        id=str(new_resume["id"]),
        file_ref=filename,
        parsed_json=parsed_resume,
        is_primary=True,
        created_at=created_iso,
        parse_incomplete=parse_incomplete,
        parse_warning=(
            "We couldn't fully read this resume automatically — some sections "
            "may be missing. Please review it, or try re-uploading as a PDF or "
            ".docx." if parse_incomplete else None
        ),
    )


# ---------------------------------------------------------------------------
# Resume page (base resume + live JD rephrase + tailored history)
# ---------------------------------------------------------------------------


@app.get("/api/resume/base", response_model=BaseResumeResponse)
def get_base_resume(user_id: str = Depends(get_authenticated_user_id)):
    """The authenticated user's current base (primary) resume, for the Resume
    page's right-hand editor. Tenant-scoped via repo.get_primary_resume."""
    primary = repo.get_primary_resume(user_id)
    if not primary or not primary.get("parsed_json"):
        return BaseResumeResponse(has_resume=False)
    return BaseResumeResponse(
        resume_id=str(primary["id"]),
        parsed_json=primary.get("parsed_json"),
        has_resume=True,
    )


@app.post("/api/resume/rephrase", response_model=RephraseResponse)
def rephrase_resume(body: RephraseRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Live-rephrase the user's OWN base resume against a JD / instruction and
    return the tailored JSON — a PREVIEW only, nothing is persisted. Same
    tailoring engine (ATS-floor retry + anti-fabrication) as the pipeline, so
    the Resume page shows exactly what outreach would attach.

    Raises 400 if the user has no base resume on file (we never rephrase a
    shared/other resume — same isolation guarantee as the pipeline).
    """
    from skills.tailor_resume import (
        load_base_resume, tailor_resume_verbose, diff_resumes,
        MIN_ATS_SCORE, NoResumeError, TEMPLATES, DEFAULT_TEMPLATE,
    )

    jd = (body.jd_text or "").strip()
    if not jd:
        raise HTTPException(status_code=400, detail="jd_text is required")

    # Guard the LLM against overlong JDs: extra boilerplate past MAX_JD_CHARS
    # dilutes the real signal and invites keyword-stuffing/hallucination. Clip
    # and flag rather than fail, so the user still gets a tailored result.
    jd_truncated = len(jd) > MAX_JD_CHARS
    if jd_truncated:
        jd = jd[:MAX_JD_CHARS]

    try:
        base_resume = load_base_resume(user_id)
    except NoResumeError:
        raise HTTPException(
            status_code=400,
            detail="No base resume on file. Upload a resume first.",
        )

    template = body.template if body.template in TEMPLATES else DEFAULT_TEMPLATE
    company = (body.company or "").strip() or "the company"
    role = (body.role or "").strip() or "this role"

    # Single call to the configured tailoring model (chosen offline via the
    # model benchmark) — fast and responsive, no runtime comparison.
    result = tailor_resume_verbose(base_resume, company, role, jd)
    tailored = result["tailored"]
    coverage = result["keyword_coverage"]

    return RephraseResponse(
        base_json=base_resume,
        tailored_json=tailored,
        keyword_coverage=coverage,
        ats_below_floor=coverage < MIN_ATS_SCORE,
        model_used=result["model_used"],
        escalated=result["escalated"],
        template=template,
        diff=diff_resumes(base_resume, tailored),
        jd_truncated=jd_truncated,
        max_jd_chars=MAX_JD_CHARS,
    )


class ResumeDownloadRequest(BaseModel):
    """Render a resume to PDF. If resume_json is omitted, the user's current
    base resume is used. template selects the visual layout (standard | jake)."""
    resume_json: Optional[dict] = None
    template: Optional[str] = "jake"
    filename: Optional[str] = None


@app.post("/api/resume/download")
def download_resume_pdf(body: ResumeDownloadRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Render a resume (the on-screen edited version, or the user's base if
    none is sent) to a PDF and stream it back. Template-aware so the download
    matches the preview the user is looking at.
    """
    from fastapi.responses import Response
    from skills.tailor_resume import (
        load_base_resume, resume_to_pdf_bytes, NoResumeError, TEMPLATES, DEFAULT_TEMPLATE,
    )

    resume = body.resume_json
    if not resume:
        try:
            resume = load_base_resume(user_id)
        except NoResumeError:
            raise HTTPException(status_code=400, detail="No base resume on file. Upload a resume first.")

    template = body.template if body.template in TEMPLATES else DEFAULT_TEMPLATE
    try:
        pdf_bytes = resume_to_pdf_bytes(resume, template=template)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render PDF: {e}")

    name = (body.filename or (resume.get("name") if isinstance(resume, dict) else None) or "resume")
    safe = "".join(c for c in str(name) if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_") or "resume"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'},
    )


@app.get("/api/resume/tailored", response_model=list[TailoredResumeResponse])
def list_tailored_resumes(user_id: str = Depends(get_authenticated_user_id)):
    """History of every tailored resume version we've built for this user —
    each with the company it was built for and its ATS score. Powers the
    Resume page's history list. Tenant-scoped."""
    rows = repo.get_tailored_resumes(user_id)
    return [
        TailoredResumeResponse(
            id=str(r["id"]),
            lead_id=str(r["lead_id"]) if r.get("lead_id") else None,
            company=r.get("company"),
            role=r.get("role"),
            keyword_coverage=r.get("keyword_coverage"),
            template=r.get("template") or "jake",
            model_used=r.get("model_used"),
            source=r.get("source") or "pipeline",
            created_at=r["created_at"].isoformat() if r.get("created_at") else "",
            tailored_json=r.get("tailored_json"),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Demo Code Generation, Docker Sandboxing & Multi-Cloud Deployment Routes
# ---------------------------------------------------------------------------

class DemoBuildRequest(BaseModel):
    title: str
    description: str
    company_name: Optional[str] = None
    tech_stack: Optional[list[str]] = None
    project_type: Optional[str] = "fullstack"  # fullstack | frontend_only | backend_only


class DemoRefineRequest(BaseModel):
    prompt: str


class ProviderKeysRequest(BaseModel):
    github_token: Optional[str] = None
    vercel_token: Optional[str] = None
    render_api_key: Optional[str] = None


@app.post("/api/demos/build")
def start_demo_build_route(
    body: DemoBuildRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Trigger an AI demo code generation, Docker sandbox build, and multi-cloud deploy.
    Quota rate-limiting is temporarily bypassed for development.
    """
    # repo.check_and_increment_demo_quota(user_id, max_daily=5) — Bypassed per request

    build_id = f"demo-{uuid.uuid4().hex[:8]}"
    demo_spec = {
        "title": body.title,
        "description": body.description,
        "tech_stack": body.tech_stack or ["React", "FastAPI"],
        "deliverable": "a working build",
    }

    demo_row = repo.create_demo_build(
        user_id=user_id,
        build_id=build_id,
        title=body.title,
        company_name=body.company_name,
        project_type=body.project_type or "fullstack",
        spec_json=demo_spec,
    )

    from api.tasks import enqueue_pipeline_task
    from orchestrator.task_dispatch import TASK_TYPE_DEMO_BUILD

    enqueue_pipeline_task(
        user_id=user_id,
        task_type=TASK_TYPE_DEMO_BUILD,
        payload={
            "build_id": build_id,
            "demo_project": demo_spec,
            "company": body.company_name or "",
            "project_type": body.project_type or "fullstack",
        },
    )

    return demo_row


@app.post("/api/demos/build/{build_id}/refine")
def refine_demo_build_route(
    build_id: str,
    body: DemoRefineRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Submit a refinement turn prompt to modify an existing demo build and re-deploy."""
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Refinement prompt cannot be empty")

    demo_row = repo.get_demo_build(user_id, build_id)

    from api.tasks import enqueue_pipeline_task
    from orchestrator.task_dispatch import TASK_TYPE_DEMO_REFINE

    enqueue_pipeline_task(
        user_id=user_id,
        task_type=TASK_TYPE_DEMO_REFINE,
        payload={
            "build_id": build_id,
            "prompt": body.prompt,
        },
    )

    return repo.add_refinement_turn(user_id, build_id, body.prompt, stage="building")


@app.get("/api/demos/build/{build_id}")
def get_demo_build_route(
    build_id: str,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Fetch status, stage, repo_url, frontend_url, backend_url for a demo build."""
    try:
        return repo.get_demo_build(user_id, build_id)
    except repo.NotFoundError:
        raise HTTPException(status_code=404, detail="Demo build not found")


@app.get("/api/demos/list")
def list_demo_builds_route(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_authenticated_user_id),
):
    """List all recent demo builds for user."""
    return repo.list_user_demo_builds(user_id, limit=limit)


@app.get("/api/demos/quota")
def get_demo_quota_route(
    user_id: str = Depends(get_authenticated_user_id),
):
    """Check remaining demo build quota for today."""
    usage = repo.get_daily_demo_usage(user_id, max_daily=5)
    return {
        "date": usage["date"],
        "used": usage["used"],
        "limit": 999,
        "remaining": 999,
    }


@app.get("/api/user/provider-keys")
def get_provider_keys_route(
    user_id: str = Depends(get_authenticated_user_id),
):
    """Retrieve saved provider keys status."""
    keys = repo.get_user_provider_keys(user_id)
    return {
        "has_github_token": bool(keys.get("github_token")),
        "has_vercel_token": bool(keys.get("vercel_token")),
        "has_render_api_key": bool(keys.get("render_api_key")),
    }


@app.post("/api/user/provider-keys")
def update_provider_keys_route(
    body: ProviderKeysRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Update user's connected provider API tokens."""
    updated = repo.update_user_provider_keys(
        user_id,
        github_token=body.github_token,
        vercel_token=body.vercel_token,
        render_api_key=body.render_api_key,
    )
    return {
        "status": "updated",
        "has_github_token": bool(updated.get("github_token")),
        "has_vercel_token": bool(updated.get("vercel_token")),
        "has_render_api_key": bool(updated.get("render_api_key")),
    }


# ---------------------------------------------------------------------------
# GitHub & Vercel 1-Click OAuth Connect Routes
# ---------------------------------------------------------------------------

@app.get("/api/auth/github/connect")
def github_oauth_connect(user_id: str = Depends(get_authenticated_user_id)):
    """Generate 1-click GitHub OAuth authorization URL."""
    try:
        from api.provider_oauth import get_github_auth_url, ProviderOAuthConfigError
        url = get_github_auth_url(user_id)
        return {"auth_url": url}
    except ProviderOAuthConfigError as e:
        raise HTTPException(
            status_code=400,
            detail=f"GitHub 1-Click OAuth is not configured: {e} Please set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in config/.env, or paste a Personal Access Token in Settings."
        )


@app.get("/api/auth/github/callback")
async def github_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Callback for GitHub OAuth authorization."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    if error or not code or not state:
        err_msg = error or "missing_code_or_state"
        return RedirectResponse(url=f"{frontend_url}/settings?github=error&msg={err_msg}")

    try:
        from api.provider_oauth import verify_provider_state, exchange_github_code
        user_id = verify_provider_state(state, expected_provider="github")
        token = await exchange_github_code(code)
        repo.update_user_provider_keys(user_id, github_token=token)
        return RedirectResponse(url=f"{frontend_url}/settings?github=connected")
    except Exception as e:
        print(f"[GitHub OAuth Error] {e}")
        return RedirectResponse(url=f"{frontend_url}/settings?github=error")


@app.get("/api/auth/vercel/connect")
def vercel_oauth_connect(user_id: str = Depends(get_authenticated_user_id)):
    """Generate 1-click Vercel OAuth authorization URL."""
    try:
        from api.provider_oauth import get_vercel_auth_url, ProviderOAuthConfigError
        url = get_vercel_auth_url(user_id)
        return {"auth_url": url}
    except ProviderOAuthConfigError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Vercel 1-Click OAuth is not configured: {e} Please set VERCEL_CLIENT_ID and VERCEL_CLIENT_SECRET in config/.env, or paste a Vercel API Token in Settings."
        )


@app.get("/api/auth/vercel/callback")
async def vercel_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Callback for Vercel OAuth authorization."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    if error or not code or not state:
        err_msg = error or "missing_code_or_state"
        return RedirectResponse(url=f"{frontend_url}/settings?vercel=error&msg={err_msg}")

    try:
        from api.provider_oauth import get_provider_state_payload, exchange_vercel_code
        state_data = get_provider_state_payload(state, expected_provider="vercel")
        user_id = state_data["user_id"]
        code_verifier = state_data.get("code_verifier")
        token = await exchange_vercel_code(code, code_verifier=code_verifier)
        repo.update_user_provider_keys(user_id, vercel_token=token)
        return RedirectResponse(url=f"{frontend_url}/settings?vercel=connected")
    except Exception as e:
        print(f"[Vercel OAuth Error] {e}")
        return RedirectResponse(url=f"{frontend_url}/settings?vercel=error")


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
