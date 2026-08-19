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


def _run_step(label: str, fn, *args, **kwargs) -> dict:
    """Run a single pipeline step, catching and reporting any error.

    Returns a small result dict: {step, status, error}.
    """
    print(f"\n{'─' * 60}")
    print(f"▶  {label}  [{_now()}]")
    print(f"{'─' * 60}")
    try:
        fn(*args, **kwargs)
        print(f"✅ {label} — done")
        return {"step": label, "status": "ok", "error": None}
    except Exception as e:
        print(f"❌ {label} — failed: {e}")
        traceback.print_exc()
        return {"step": label, "status": "error", "error": str(e)}


def run_sourcing_pipeline(
    sources: list[str] | None = None,
    yc_max_leads: int = 15,
    x_max_leads: int = 5,
) -> dict:
    """Run the full sourcing + processing chain.

    Order:
      1. Scrape sources (arbeitnow, jobicy, careers_page, yc, x)
      2. find_contact_email
      3. tailor_resume
      4. draft_outreach
      5. feed_graph (pauses leads at review interrupt)

    Args:
        sources: which scrapers to run. Defaults to the free/no-key ones + yc.
        yc_max_leads: cap on YC startups per run.
        x_max_leads: cap on X leads per run.

    Returns a summary dict with per-step results.
    """
    print("\n" + "=" * 60)
    print(f"  SOURCING PIPELINE START  [{_now()}]")
    print("=" * 60)

    if sources is None:
        sources = ["arbeitnow", "jobicy", "yc"]

    results = []

    # --- 1. Sourcing ---
    for source in sources:
        if source == "arbeitnow":
            from skills.scrape_job_boards.arbeitnow import run as arbeitnow_run
            results.append(_run_step("scrape:arbeitnow", arbeitnow_run))
        elif source == "jobicy":
            from skills.scrape_job_boards.jobicy import run as jobicy_run
            results.append(_run_step("scrape:jobicy", jobicy_run))
        elif source == "careers_page":
            from skills.scrape_job_boards.careers_page import run as careers_run
            results.append(_run_step("scrape:careers_page", careers_run))
        elif source == "yc":
            from skills.scrape_job_boards.yc_startups import run as yc_run
            results.append(_run_step("scrape:yc", yc_run, yc_max_leads))
        elif source == "x":
            from skills.scrape_x_leads import run as x_run
            results.append(_run_step("scrape:x", x_run, x_max_leads))
        else:
            print(f"  ⚠️  Unknown source '{source}', skipping")

    # --- 2. Enrich: find contact emails ---
    from skills.find_contact_email import run as find_email_run
    results.append(_run_step("find_contact_email", find_email_run))

    # --- 3. Tailor resumes ---
    from skills.tailor_resume import run as tailor_run
    results.append(_run_step("tailor_resume", tailor_run))

    # --- 4. Draft outreach ---
    from skills.draft_outreach import run as draft_run
    results.append(_run_step("draft_outreach", draft_run))

    # --- 5. Feed into graph (pause at review) ---
    from orchestrator.feed_graph import feed_pending_leads
    results.append(_run_step("feed_graph", feed_pending_leads))

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    print("\n" + "=" * 60)
    print(f"  SOURCING PIPELINE DONE  [{_now()}]")
    print(f"  {ok} steps ok, {failed} failed")
    print("=" * 60 + "\n")

    return {"pipeline": "sourcing", "ok": ok, "failed": failed, "steps": results}


def run_followup_pipeline() -> dict:
    """Run the follow-up check: re-queue stale sent leads through the graph."""
    print("\n" + "=" * 60)
    print(f"  FOLLOW-UP PIPELINE START  [{_now()}]")
    print("=" * 60)

    results = []

    from orchestrator.check_followups import check_and_queue_followups
    results.append(_run_step("check_followups", check_and_queue_followups))

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    print("\n" + "=" * 60)
    print(f"  FOLLOW-UP PIPELINE DONE  [{_now()}]")
    print(f"  {ok} steps ok, {failed} failed")
    print("=" * 60 + "\n")

    return {"pipeline": "followup", "ok": ok, "failed": failed, "steps": results}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "sourcing"
    if which == "sourcing":
        run_sourcing_pipeline()
    elif which == "followups":
        run_followup_pipeline()
    else:
        print("Usage: python -m orchestrator.pipeline_runner [sourcing|followups]")


if __name__ == "__main__":
    main()
