"""FastAPI backend — bridges the frontend dashboard to the existing Python pipeline.

Run with:
    uvicorn api.main:app --reload --port 8000

Or from project root:
    python -m uvicorn api.main:app --reload --port 8000
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path so we can import existing modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


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

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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


class StatsResponse(BaseModel):
    total: int
    new: int
    pending_review: int
    in_review: int
    approved: int
    sent: int
    replied: int
    rejected: int


class EditRequest(BaseModel):
    outreach_draft: str


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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _get_sheet_client():
    """Lazy import of sheet_client to avoid import errors if creds are missing."""
    try:
        from storage.sheet_client import get_leads, update_lead, add_lead
        return get_leads, update_lead, add_lead
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Google Sheets connection unavailable: {str(e)}"
        )


# --- Short-lived leads cache -------------------------------------------------
# Reading the whole Sheet is slow and rate-limited. A single page load fires
# several read endpoints (stats + leads + review filters), each of which would
# otherwise hit the Sheet independently. This TTL cache collapses those into
# one Sheet read, which is the main fix for slow page loads.
_LEADS_TTL = 8  # seconds
_leads_cache: dict = {"data": None, "ts": 0.0}
_leads_cache_lock = threading.Lock()


def _get_all_leads_cached(force: bool = False) -> list[dict]:
    """Return all leads, served from an in-memory cache when fresh."""
    now = time.monotonic()
    with _leads_cache_lock:
        if not force and _leads_cache["data"] is not None and (now - _leads_cache["ts"]) < _LEADS_TTL:
            return _leads_cache["data"]

    get_leads, _, _ = _get_sheet_client()
    data = get_leads()
    with _leads_cache_lock:
        _leads_cache["data"] = data
        _leads_cache["ts"] = time.monotonic()
    return data


def _invalidate_leads_cache():
    """Drop the cached leads so the next read re-fetches from the Sheet."""
    with _leads_cache_lock:
        _leads_cache["data"] = None
        _leads_cache["ts"] = 0.0


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

@app.get("/api/leads", response_model=list[LeadResponse])
def list_leads(status: Optional[str] = Query(None, description="Filter by status")):
    """List all leads, optionally filtered by status (served from TTL cache)."""
    leads = _get_all_leads_cached()
    if status:
        leads = [l for l in leads if str(l.get("status", "")).strip() == status]

    # Normalize all fields to strings
    result = []
    for lead in leads:
        result.append(LeadResponse(
            id=str(lead.get("id", "")),
            source=str(lead.get("source", "")),
            company=str(lead.get("company", "")),
            role=str(lead.get("role", "")),
            jd_text=str(lead.get("jd_text", "")),
            contact_name=str(lead.get("contact_name", "")),
            contact_email=str(lead.get("contact_email", "")),
            x_handle=str(lead.get("x_handle", "")),
            status=str(lead.get("status", "")),
            resume_version=str(lead.get("resume_version", "")),
            outreach_draft=str(lead.get("outreach_draft", "")),
            sent_at=str(lead.get("sent_at", "")),
            last_checked=str(lead.get("last_checked", "")),
            followup_count=str(lead.get("followup_count", "")),
            listing_url=str(lead.get("listing_url", "")),
            posted_date=str(lead.get("posted_date", "")),
            domain=str(lead.get("domain", "")),
            review_decision=str(lead.get("review_decision", "")),
        ))

    return result


@app.get("/api/leads/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: str):
    """Get a single lead by ID (served from TTL cache)."""
    leads = _get_all_leads_cached()
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)

    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    return LeadResponse(
        id=str(lead.get("id", "")),
        source=str(lead.get("source", "")),
        company=str(lead.get("company", "")),
        role=str(lead.get("role", "")),
        jd_text=str(lead.get("jd_text", "")),
        contact_name=str(lead.get("contact_name", "")),
        contact_email=str(lead.get("contact_email", "")),
        x_handle=str(lead.get("x_handle", "")),
        status=str(lead.get("status", "")),
        resume_version=str(lead.get("resume_version", "")),
        outreach_draft=str(lead.get("outreach_draft", "")),
        sent_at=str(lead.get("sent_at", "")),
        last_checked=str(lead.get("last_checked", "")),
        followup_count=str(lead.get("followup_count", "")),
        listing_url=str(lead.get("listing_url", "")),
        posted_date=str(lead.get("posted_date", "")),
        domain=str(lead.get("domain", "")),
        review_decision=str(lead.get("review_decision", "")),
    )


@app.post("/api/leads/{lead_id}/approve")
def approve_lead(lead_id: str):
    """Approve a lead.

    Tries to resume the LangGraph review checkpoint first; if the lead isn't
    currently paused in the graph, falls back to updating the Sheet directly
    so the dashboard button always works.
    """
    try:
        from orchestrator.review_cli import approve_lead as _approve
        if _approve(lead_id):
            _invalidate_leads_cache()
            return {"status": "approved", "lead_id": lead_id, "via": "graph"}
    except Exception as e:
        print(f"  approve via graph failed ({e}), falling back to sheet update")

    _, update_lead, _ = _get_sheet_client()
    update_lead(lead_id, {"status": "approved", "review_decision": "approved"})
    _invalidate_leads_cache()
    return {"status": "approved", "lead_id": lead_id, "via": "sheet"}


@app.post("/api/leads/{lead_id}/reject")
def reject_lead(lead_id: str):
    """Reject a lead (graph resume, or Sheet fallback)."""
    try:
        from orchestrator.review_cli import reject_lead as _reject
        if _reject(lead_id):
            _invalidate_leads_cache()
            return {"status": "rejected", "lead_id": lead_id, "via": "graph"}
    except Exception as e:
        print(f"  reject via graph failed ({e}), falling back to sheet update")

    _, update_lead, _ = _get_sheet_client()
    update_lead(lead_id, {"status": "rejected", "review_decision": "rejected"})
    _invalidate_leads_cache()
    return {"status": "rejected", "lead_id": lead_id, "via": "sheet"}


@app.post("/api/leads/{lead_id}/edit")
def edit_lead(lead_id: str, body: EditRequest):
    """Edit outreach draft and approve the lead (graph resume, or Sheet fallback)."""
    try:
        from orchestrator.review_cli import edit_lead as _edit
        if _edit(lead_id, body.outreach_draft):
            _invalidate_leads_cache()
            return {"status": "approved", "lead_id": lead_id, "draft_updated": True, "via": "graph"}
    except Exception as e:
        print(f"  edit via graph failed ({e}), falling back to sheet update")

    _, update_lead, _ = _get_sheet_client()
    update_lead(lead_id, {
        "status": "approved",
        "outreach_draft": body.outreach_draft,
        "review_decision": "edited",
    })
    _invalidate_leads_cache()
    return {"status": "approved", "lead_id": lead_id, "draft_updated": True, "via": "sheet"}


@app.post("/api/leads/{lead_id}/research", response_model=ResearchResponse)
def research_lead(lead_id: str):
    """Generate structured company research with demo project idea for a lead."""
    leads = _get_all_leads_cached()
    lead = next((l for l in leads if str(l.get("id", "")) == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    try:
        from skills.research_company import research_company
        result = research_company(
            company=str(lead.get("company", "")),
            domain=str(lead.get("domain", "")),
            role=str(lead.get("role", "")),
            jd_text=str(lead.get("jd_text", "")),
        )
        
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
# Routes: Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    """Dashboard stats — count leads by status (served from TTL cache)."""
    leads = _get_all_leads_cached()
    total = len(leads)

    counts = {
        "new": 0,
        "pending_review": 0,
        "in_review": 0,
        "approved": 0,
        "sent": 0,
        "replied": 0,
        "rejected": 0,
    }

    for lead in leads:
        status = str(lead.get("status", "")).strip()
        if status in counts:
            counts[status] += 1
        elif status == "draft_created":
            counts["sent"] += 1
        elif not status:
            counts["new"] += 1

    return StatsResponse(total=total, **counts)


# ---------------------------------------------------------------------------
# Routes: Pipeline Actions
# ---------------------------------------------------------------------------

@app.post("/api/pipeline/scrape")
def trigger_scrape(sources: Optional[list[str]] = None):
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

# Shared run-state, updated live by the background pipeline thread.
_pipeline_run_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "current_step": None,
    "steps": [],        # [{step, status}]
    "summary": None,    # final summary dict from the runner
    "error": None,
}
_pipeline_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunPipelineRequest(BaseModel):
    sources: Optional[list[str]] = None
    yc_max_leads: int = 15
    x_max_leads: int = 5
    csv_path: Optional[str] = None


def _run_pipeline_bg(sources, yc_max_leads, x_max_leads, csv_path):
    """Background worker that runs the sourcing pipeline and tracks progress."""
    from orchestrator.pipeline_runner import run_sourcing_pipeline

    with _pipeline_lock:
        _pipeline_run_state.update({
            "running": True,
            "started_at": _now_iso(),
            "finished_at": None,
            "current_step": "starting",
            "steps": [],
            "summary": None,
            "error": None,
        })

    def on_step(label: str, status: str):
        with _pipeline_lock:
            _pipeline_run_state["current_step"] = label if status == "running" else None
            # Record only terminal states to keep the list clean
            if status in ("ok", "error"):
                _pipeline_run_state["steps"].append({"step": label, "status": status})

    try:
        summary = run_sourcing_pipeline(
            sources=sources,
            yc_max_leads=yc_max_leads,
            x_max_leads=x_max_leads,
            csv_path=csv_path,
            progress_callback=on_step,
        )
        with _pipeline_lock:
            _pipeline_run_state["summary"] = summary
    except Exception as e:
        with _pipeline_lock:
            _pipeline_run_state["error"] = str(e)
    finally:
        # New leads were likely written to the Sheet — drop the cache so the
        # next dashboard/leads read reflects them.
        _invalidate_leads_cache()
        with _pipeline_lock:
            _pipeline_run_state["running"] = False
            _pipeline_run_state["current_step"] = None
            _pipeline_run_state["finished_at"] = _now_iso()


@app.post("/api/pipeline/run")
def run_pipeline(body: RunPipelineRequest):
    """Start the full sourcing+processing pipeline on demand (non-blocking).

    Runs in a background thread; poll /api/pipeline/run-status for progress.
    """
    with _pipeline_lock:
        if _pipeline_run_state["running"]:
            raise HTTPException(status_code=409, detail="Pipeline already running")

    sources = body.sources or ["arbeitnow", "jobicy", "yc"]
    threading.Thread(
        target=_run_pipeline_bg,
        args=(sources, body.yc_max_leads, body.x_max_leads, body.csv_path),
        daemon=True,
    ).start()

    return {"status": "started", "sources": sources}


@app.get("/api/pipeline/run-status")
def pipeline_run_status():
    """Return the live state of the current/last pipeline run."""
    with _pipeline_lock:
        return dict(_pipeline_run_state)


@app.post("/api/pipeline/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Upload a companies CSV and run the company_list scraper + processing.

    The CSV is saved to config/uploaded_companies.csv, then the pipeline runs
    with only the company_list source in the background.
    """
    with _pipeline_lock:
        if _pipeline_run_state["running"]:
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

    threading.Thread(
        target=_run_pipeline_bg,
        args=(["company_list"], 15, 5, save_path),
        daemon=True,
    ).start()

    return {"status": "started", "filename": file.filename, "saved_to": save_path}


@app.post("/api/pipeline/find-emails")
def trigger_find_emails():
    """Run the contact email discovery skill."""
    try:
        from skills.find_contact_email import run
        run()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/tailor-resumes")
def trigger_tailor_resumes():
    """Run the resume tailoring skill for leads that need it."""
    try:
        from skills.tailor_resume import run
        run()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/draft-outreach")
def trigger_draft_outreach():
    """Run the outreach drafting skill."""
    try:
        from skills.draft_outreach import run
        run()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/feed-graph")
def trigger_feed_graph():
    """Feed pending leads into the LangGraph review pipeline."""
    try:
        from orchestrator.feed_graph import feed_pending_leads
        count = feed_pending_leads()
        return {"status": "success", "leads_fed": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/send")
def trigger_send():
    """Send approved leads via Gmail."""
    try:
        from skills.send_via_gmail import run
        run()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/check-followups")
def trigger_check_followups():
    """Check sent leads for follow-up needs."""
    try:
        from orchestrator.check_followups import check_and_queue_followups
        count = check_and_queue_followups()
        return {"status": "success", "followups_queued": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Routes: Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings/search-criteria", response_model=SettingsResponse)
def get_search_criteria():
    """Get current search criteria configuration."""
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
def update_search_criteria(body: SettingsUpdateRequest):
    """Update search criteria configuration."""
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


@app.get("/api/settings/pipeline-config", response_model=PipelineConfigResponse)
def get_pipeline_config():
    """Get pipeline configuration from .env."""
    return PipelineConfigResponse(
        model_backend=_read_env_value("MODEL_BACKEND", "claude"),
        followup_days=int(_read_env_value("FOLLOWUP_DAYS", "5")),
        max_followups=int(_read_env_value("MAX_FOLLOWUPS", "2")),
        gmail_direct_send=_read_env_value("GMAIL_DIRECT_SEND", "false").lower() == "true",
    )


@app.put("/api/settings/pipeline-config")
def update_pipeline_config(body: PipelineConfigUpdateRequest):
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
def scheduler_status():
    """Return whether the scheduler is running and its jobs' next run times."""
    try:
        from orchestrator.scheduler import get_scheduler, get_jobs_status
        sched = get_scheduler()
        running = bool(sched and sched.running)
        return {"running": running, "jobs": get_jobs_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/start")
def scheduler_start():
    """Start the scheduler (idempotent)."""
    try:
        from orchestrator.scheduler import start_scheduler, get_jobs_status
        start_scheduler()
        return {"status": "started", "jobs": get_jobs_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/stop")
def scheduler_stop():
    """Stop the scheduler."""
    try:
        from orchestrator.scheduler import stop_scheduler
        stop_scheduler()
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/trigger/{job_id}")
def scheduler_trigger(job_id: str):
    """Manually trigger a scheduled job now (runs in the background).

    Valid job_ids: sourcing, followups
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
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "autoapply-api"}
