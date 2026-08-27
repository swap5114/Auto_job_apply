"""Scheduler (Phase 10b) — cron trigger for the pipeline.

Uses APScheduler's BackgroundScheduler to run the sourcing and follow-up
pipelines on a configurable schedule. This replaces the "Vellum Assistant as
cron trigger" plan with a self-contained, no-external-dependency scheduler
that fits the existing Python stack.

Schedule is defined in config/schedule.json and can be edited without touching
code. The scheduler can run:
  - standalone (blocking):  python -m orchestrator.scheduler
  - embedded in FastAPI:    started in the API's lifespan (see api/main.py)

Each job simply calls the corresponding function in pipeline_runner.py.
"""

import os
import sys
import json
import threading
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from orchestrator.pipeline_runner import (
    run_sourcing_pipeline,
    run_followup_pipeline,
    run_catalog_refresh,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "schedule.json")

# Module-level singleton so FastAPI and the CLI share one scheduler instance
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def load_schedule_config() -> dict:
    """Load the schedule config from config/schedule.json."""
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Schedule config not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Job wrappers — these are what the scheduler actually calls
# ---------------------------------------------------------------------------

def _sourcing_job(params: dict | None = None):
    """Scheduled sourcing job."""
    params = params or {}
    print(f"\n🕐 [SCHEDULER] Triggering sourcing pipeline at {datetime.now().isoformat()}")
    run_sourcing_pipeline(
        sources=params.get("sources"),
        yc_max_leads=params.get("yc_max_leads", 15),
        x_max_leads=params.get("x_max_leads", 5),
    )


def _followup_job():
    """Scheduled follow-up job."""
    print(f"\n🕐 [SCHEDULER] Triggering follow-up pipeline at {datetime.now().isoformat()}")
    run_followup_pipeline()


def _catalog_refresh_job(params: dict | None = None):
    """Scheduled catalog-refresh job -- the shared Job/Company catalog
    every user's matched-jobs feed reads from. Without this running on a
    schedule, the catalog only ever grows (and never closes stale
    listings) when someone manually hits /api/pipeline/catalog-refresh --
    see config/schedule.json's "catalog_refresh" entry for why this
    matters for a first-time user's experience specifically.
    """
    params = params or {}
    print(f"\n🕐 [SCHEDULER] Triggering catalog refresh at {datetime.now().isoformat()}")
    run_catalog_refresh(providers=params.get("providers"))


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def build_scheduler() -> BackgroundScheduler:
    """Build and configure the scheduler from config, without starting it."""
    config = load_schedule_config()
    timezone = config.get("timezone", "UTC")
    jobs = config.get("jobs", {})

    scheduler = BackgroundScheduler(timezone=timezone)

    # Sourcing job
    sourcing = jobs.get("sourcing", {})
    if sourcing.get("enabled", False):
        cron = sourcing.get("cron", {})
        params = sourcing.get("params", {})
        scheduler.add_job(
            _sourcing_job,
            trigger=CronTrigger(
                hour=cron.get("hour", 8),
                minute=cron.get("minute", 0),
                timezone=timezone,
            ),
            id="sourcing",
            name="Sourcing pipeline",
            kwargs={"params": params},
            replace_existing=True,
            misfire_grace_time=3600,  # 1h grace if the process was asleep
        )

    # Follow-up job
    followups = jobs.get("followups", {})
    if followups.get("enabled", False):
        cron = followups.get("cron", {})
        scheduler.add_job(
            _followup_job,
            trigger=CronTrigger(
                hour=cron.get("hour", 18),
                minute=cron.get("minute", 0),
                timezone=timezone,
            ),
            id="followups",
            name="Follow-up pipeline",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    # Catalog refresh job
    catalog_refresh = jobs.get("catalog_refresh", {})
    if catalog_refresh.get("enabled", False):
        cron = catalog_refresh.get("cron", {})
        params = catalog_refresh.get("params", {})
        scheduler.add_job(
            _catalog_refresh_job,
            trigger=CronTrigger(
                hour=cron.get("hour", 4),
                minute=cron.get("minute", 0),
                timezone=timezone,
            ),
            id="catalog_refresh",
            name="Catalog refresh",
            kwargs={"params": params},
            replace_existing=True,
            misfire_grace_time=3600,
        )

    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Start the shared scheduler singleton (idempotent)."""
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            print("Scheduler already running.")
            return _scheduler
        _scheduler = build_scheduler()
        _scheduler.start()
        print("✅ Scheduler started.")
        _print_jobs(_scheduler)
        return _scheduler


def stop_scheduler():
    """Stop the shared scheduler singleton if running."""
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            print("🛑 Scheduler stopped.")
        _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    """Return the current scheduler singleton (may be None)."""
    return _scheduler


def get_jobs_status() -> list[dict]:
    """Return a serializable list of scheduled jobs and their next run times."""
    if not _scheduler or not _scheduler.running:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs


def trigger_job_now(job_id: str) -> bool:
    """Manually trigger a scheduled job immediately (runs in a background thread).

    Returns True if the job exists and was triggered.
    """
    if job_id == "sourcing":
        threading.Thread(target=_sourcing_job, daemon=True).start()
        return True
    elif job_id == "followups":
        threading.Thread(target=_followup_job, daemon=True).start()
        return True
    elif job_id == "catalog_refresh":
        threading.Thread(target=_catalog_refresh_job, daemon=True).start()
        return True
    return False


def _print_jobs(scheduler: BackgroundScheduler):
    """Print the registered jobs and their next run times."""
    jobs = scheduler.get_jobs()
    if not jobs:
        print("  (no jobs enabled — check config/schedule.json)")
        return
    print("\n  Scheduled jobs:")
    for job in jobs:
        nxt = job.next_run_time.isoformat() if job.next_run_time else "n/a"
        print(f"    • {job.name} ({job.id}) — next run: {nxt}")
    print()


def main():
    """Run the scheduler standalone (blocking)."""
    import time

    print("=" * 60)
    print("  PIPELINE SCHEDULER (Phase 10b)")
    print("=" * 60)

    start_scheduler()

    print("Scheduler running. Press Ctrl+C to exit.\n")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        stop_scheduler()
        print("\nExiting.")


if __name__ == "__main__":
    main()
