"""Pipeline runner — chains sourcing + processing into single callables.

This is the glue that the scheduler (Phase 10b) calls on a cron trigger.
It wraps the existing standalone skills into two high-level jobs:

  run_sourcing_pipeline():
      scrape all sources -> find_contact_email -> tailor_resume
      -> draft_outreach -> feed_graph (pauses leads at the review interrupt)

  run_followup_pipeline():
      check_followups (re-queues stale sent leads through the graph)

Each step is wrapped in its own try/except so one failing stage never kills
the whole run — matching the project's "log loudly, never silently skip"
discipline. Every step reports what it did.

Can also run standalone:
    python -m orchestrator.pipeline_runner sourcing
    python -m orchestrator.pipeline_runner followups
"""

import os
import sys
import traceback
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run_step(label: str, fn, *args, callback=None, **kwargs) -> dict:
    """Run a single pipeline step, catching and reporting any error.

    If a `callback(label, status)` is given, it's invoked when the step starts
    ("running") and when it finishes ("ok"/"error") — used for live progress.

    Returns a small result dict: {step, status, error}.
    """
    print(f"\n{'─' * 60}")
    print(f"▶  {label}  [{_now()}]")
    print(f"{'─' * 60}")
    if callback:
        callback(label, "running")
    try:
        fn(*args, **kwargs)
        print(f"✅ {label} — done")
        result = {"step": label, "status": "ok", "error": None}
    except Exception as e:
        print(f"❌ {label} — failed: {e}")
        traceback.print_exc()
        result = {"step": label, "status": "error", "error": str(e)}
    if callback:
        callback(label, result["status"])
    return result


def run_sourcing_pipeline(
    sources: list[str] | None = None,
    yc_max_leads: int = 5,
    x_max_leads: int = 5,
    csv_path: str | None = None,
    progress_callback=None,
    user_id: str | None = None,
) -> dict:
    """Run the full sourcing + processing chain.

    Order:
      1. Scrape sources (arbeitnow, jobicy, careers_page, company_list, yc, x)
      2. find_contact_email
      3. tailor_resume
      4. draft_outreach (outreach channel only -- the apply channel and its
         cover-note drafting were removed in v1)
      5. feed_graph (pauses leads at review interrupt)

    Args:
        sources: which scrapers to run. Defaults to the free/no-key ones + yc.
        yc_max_leads: cap on YC startups per run.
        x_max_leads: cap on X leads per run.
        csv_path: path to a companies CSV (required if 'company_list' in sources).
        progress_callback: optional fn(step_label, status) for live progress.
        user_id: whose leads this run's feed_graph step feeds into the
            LangGraph review pipeline (Phase 4.1). api/main.py's
            /api/pipeline/run route (the only HTTP-reachable caller of this
            function) always passes the real authenticated user_id here.
            Defaults to None -- feed_pending_leads falls back to
            db.current_user's single-operator stand-in only for the
            standalone CLI entry point below (`python -m
            orchestrator.pipeline_runner sourcing`), which has no real
            per-request identity to thread through. v1 fix: user_id is now
            threaded into EVERY step (scrape, find_contact_email,
            tailor_resume, draft_outreach, feed_graph), not just feed_graph
            -- so a signed-in user's run writes leads/enrichment/drafts to
            their OWN leads table, not the local operator's. Each run()
            still defaults to db.current_user when user_id is None (the CLI
            path), so standalone invocation is unchanged.

    Returns a summary dict with per-step results.
    """
    print("\n" + "=" * 60)
    print(f"  SOURCING PIPELINE START  [{_now()}]")
    print("=" * 60)

    if sources is None:
        sources = ["arbeitnow", "jobicy", "yc"]

    # No dedup-cache reset needed here anymore: storage/sheet_client.py's
    # in-memory dedup cache (a workaround for Google Sheets' read-quota
    # limits) doesn't exist in the Postgres path. db.repository.add_lead
    # dedups via a real per-tenant unique constraint on every call, so
    # there's no cache to go stale across runs.
    cb = progress_callback
    results = []

    # --- 1. Sourcing ---
    for source in sources:
        if source == "arbeitnow":
            from skills.scrape_job_boards.arbeitnow import run as arbeitnow_run
            results.append(_run_step("scrape:arbeitnow", arbeitnow_run, user_id=user_id, callback=cb))
        elif source == "jobicy":
            from skills.scrape_job_boards.jobicy import run as jobicy_run
            results.append(_run_step("scrape:jobicy", jobicy_run, user_id=user_id, callback=cb))
        elif source == "careers_page":
            from skills.scrape_job_boards.careers_page import run as careers_run
            results.append(_run_step("scrape:careers_page", careers_run, user_id=user_id, callback=cb))
        elif source == "company_list":
            if csv_path:
                from skills.scrape_job_boards.company_list import run as cl_run
                results.append(_run_step("scrape:company_list", cl_run, csv_path, user_id=user_id, callback=cb))
            else:
                print("  ⚠️  'company_list' requested but no csv_path provided, skipping")
        elif source == "yc":
            from skills.scrape_job_boards.yc_startups import run as yc_run
            results.append(_run_step("scrape:yc", yc_run, yc_max_leads, user_id=user_id, callback=cb))
        elif source == "x":
            from skills.scrape_x_leads import run as x_run
            results.append(_run_step("scrape:x", x_run, x_max_leads, user_id=user_id, callback=cb))
        else:
            print(f"  ⚠️  Unknown source '{source}', skipping")

    # --- 2. Enrich: find contact emails ---
    from skills.find_contact_email import run as find_email_run
    results.append(_run_step("find_contact_email", find_email_run, user_id=user_id, callback=cb))

    # --- 3. Tailor resumes ---
    from skills.tailor_resume import run as tailor_run
    results.append(_run_step("tailor_resume", tailor_run, user_id=user_id, callback=cb))

    # --- 4. Draft outreach + cover notes (channel-filtered internally) ---
    from skills.draft_outreach import run as draft_run
    results.append(_run_step("draft_outreach", draft_run, user_id=user_id, callback=cb))

    # --- 5. Feed into graph (pause at review) ---
    from orchestrator.feed_graph import feed_pending_leads
    results.append(_run_step("feed_graph", feed_pending_leads, user_id=user_id, callback=cb))

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    print("\n" + "=" * 60)
    print(f"  SOURCING PIPELINE DONE  [{_now()}]")
    print(f"  {ok} steps ok, {failed} failed")
    print("=" * 60 + "\n")

    return {"pipeline": "sourcing", "ok": ok, "failed": failed, "steps": results}


def run_pipeline_for_leads(
    user_id: str | None = None,
    lead_ids: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """Process a user's already-saved leads through to the review queue --
    the hero-chat "approve these startups -> start outreach" bridge (v1 Task 10).

    Unlike run_sourcing_pipeline, this does NO scraping: the leads already
    exist (saved from matched catalog jobs at status="matched"). It runs the
    persisting processing chain in order:

      1. find_contact_email  -> fills contact_email (uses the shared cache)
      2. tailor_resume       -> resume_version, status="tailored"
      3. draft_outreach      -> outreach_draft, status="pending_review"
      4. feed_graph          -> pauses each at the review interrupt

    Each skill is field/status-driven and user-scoped, so it naturally acts on
    exactly the leads that still need each step (which, for a fresh hero-chat
    user, are the ones they just saved). Each step is wrapped so one failing
    stage never aborts the rest (per-lead isolation lives inside the graph
    nodes; per-step isolation lives here).

    lead_ids is accepted for validation/telemetry by the caller (the API route
    checks they belong to the user before enqueuing); the processing itself is
    field-driven, not id-filtered.
    """
    print("\n" + "=" * 60)
    print(f"  PROCESS-LEADS PIPELINE START  [{_now()}]  ({len(lead_ids or [])} leads)")
    print("=" * 60)

    cb = progress_callback
    results = []

    from skills.find_contact_email import run as find_email_run
    results.append(_run_step("find_contact_email", find_email_run, user_id=user_id, callback=cb))

    from skills.tailor_resume import run as tailor_run
    results.append(_run_step("tailor_resume", tailor_run, user_id=user_id, callback=cb))

    from skills.draft_outreach import run as draft_run
    results.append(_run_step("draft_outreach", draft_run, user_id=user_id, callback=cb))

    from orchestrator.feed_graph import feed_pending_leads
    results.append(_run_step("feed_graph", feed_pending_leads, user_id=user_id, callback=cb))

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    print("\n" + "=" * 60)
    print(f"  PROCESS-LEADS PIPELINE DONE  [{_now()}]  {ok} ok, {failed} failed")
    print("=" * 60 + "\n")

    return {"pipeline": "process_leads", "ok": ok, "failed": failed, "steps": results}


def run_followup_pipeline(progress_callback=None, user_id: str | None = None) -> dict:
    """Run the follow-up check: re-queue stale sent leads through the graph.

    Args:
        user_id: whose sent leads to check (Phase 4.1) -- see
            run_sourcing_pipeline's docstring for the same contract.
            Defaults to None for the CLI/scheduler entry points, which
            legitimately fall back to db.current_user.
    """
    print("\n" + "=" * 60)
    print(f"  FOLLOW-UP PIPELINE START  [{_now()}]")
    print("=" * 60)

    results = []

    from orchestrator.check_followups import check_and_queue_followups
    results.append(_run_step(
        "check_followups", check_and_queue_followups, user_id=user_id, callback=progress_callback
    ))

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    print("\n" + "=" * 60)
    print(f"  FOLLOW-UP PIPELINE DONE  [{_now()}]")
    print(f"  {ok} steps ok, {failed} failed")
    print("=" * 60 + "\n")

    return {"pipeline": "followup", "ok": ok, "failed": failed, "steps": results}


def run_catalog_refresh(providers: list[str] | None = None, progress_callback=None) -> dict:
    """Sync the shared job catalog (companies/jobs) from Greenhouse, Lever,
    and Ashby's public APIs.

    Unlike run_sourcing_pipeline, this writes to the SHARED catalog
    (db.models.Company/Job -- no user_id), not per-user leads. It's meant
    to be run on a schedule (Cloud Scheduler in production, per the
    project's phased GCP plan) independent of any single user's session,
    since the catalog is read by every user's matched-jobs feed.

    Args:
        providers: which connectors to run. Defaults to all three.
        progress_callback: optional fn(step_label, status) for live progress.

    Returns a summary dict with per-provider results.
    """
    print("\n" + "=" * 60)
    print(f"  CATALOG REFRESH START  [{_now()}]")
    print("=" * 60)

    if providers is None:
        # v1: YC is the primary active catalog source for the hero-chat match feed.
        providers = ["yc"]

    cb = progress_callback
    results = []

    for provider in providers:
        if provider == "yc":
            from skills.scrape_job_boards.yc_startups import run_catalog as yc_catalog_run
            results.append(_run_step("catalog:yc", yc_catalog_run, callback=cb))
        elif provider == "greenhouse":
            from skills.scrape_job_boards.greenhouse import run as greenhouse_run
            results.append(_run_step("catalog:greenhouse", greenhouse_run, callback=cb))
        elif provider == "lever":
            from skills.scrape_job_boards.lever import run as lever_run
            results.append(_run_step("catalog:lever", lever_run, callback=cb))
        elif provider == "ashby":
            from skills.scrape_job_boards.ashby import run as ashby_run
            results.append(_run_step("catalog:ashby", ashby_run, callback=cb))
        else:
            print(f"  ⚠️  Unknown catalog provider '{provider}', skipping")

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    print("\n" + "=" * 60)
    print(f"  CATALOG REFRESH DONE  [{_now()}]")
    print(f"  {ok} steps ok, {failed} failed")
    print("=" * 60 + "\n")

    return {"pipeline": "catalog_refresh", "ok": ok, "failed": failed, "steps": results}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "sourcing"
    if which == "sourcing":
        run_sourcing_pipeline()
    elif which == "followups":
        run_followup_pipeline()
    elif which == "catalog":
        run_catalog_refresh()
    else:
        print("Usage: python -m orchestrator.pipeline_runner [sourcing|followups|catalog]")


if __name__ == "__main__":
    main()
