"""Graph feeder — bridges standalone skills with the LangGraph review interrupt.

Reads all leads at status=pending_review from Postgres, starts a LangGraph
thread for each one (so the graph pauses at the review node), and marks the
lead as 'in_review' to avoid double-feeding.

Usage:
    python -m orchestrator.feed_graph

After this runs, use the review CLI to act on paused leads:
    python -m orchestrator.review_cli digest
    python -m orchestrator.review_cli approve <lead_id>
"""

import os
import sys
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from db import repository as repo
from db.current_user import get_current_user_id
from graph.pipeline import (
    build_pipeline_graph,
    get_postgres_checkpointer,
    make_thread_id,
)


def feed_pending_leads(user_id: Optional[str] = None) -> int:
    """Feeds all of user_id's pending_review leads into the LangGraph pipeline.

    Each lead gets one outreach thread (thread_id =
    f"{user_id}:{lead_id}:outreach", per Phase 4.2's structural tenant
    isolation). Each run pauses at the review interrupt, waiting for
    approve/edit/reject via the CLI or API. v1 is outreach-only (the apply
    channel was removed), so there is exactly one thread per lead.

    Args:
        user_id: whose pending_review leads to feed. Every HTTP-reachable
            caller (api/main.py's /api/pipeline/feed-graph route, and
            orchestrator.pipeline_runner.run_sourcing_pipeline when invoked
            on behalf of a real request) MUST pass the real authenticated
            user_id here -- defaulting to db.current_user's single-operator
            stand-in is only correct for the CLI entry point below
            (`python -m orchestrator.feed_graph`, no HTTP caller, no real
            per-request identity to thread through).

    Returns the number of (lead, channel) runs fed into the graph.
    """
    if user_id is None:
        user_id = get_current_user_id()

    cp = get_postgres_checkpointer()
    graph = build_pipeline_graph(cp)

    leads = repo.get_leads(user_id, status="pending_review")

    if not leads:
        print("No leads at status=pending_review. Nothing to feed.")
        return 0

    fed = 0
    skipped = 0

    for lead in leads:
        lead_id = lead.get("id")
        if not lead_id:
            print(f"Warning: skipping lead with no id — {lead.get('company', '?')}")
            continue

        thread_id = make_thread_id(user_id, lead_id, channel="outreach")

        # Check if this lead's thread already exists (avoid re-feeding).
        config = {"configurable": {"thread_id": thread_id}}
        existing_state = graph.get_state(config)
        if existing_state and existing_state.values:
            skipped += 1
            continue

        # Build pipeline state from lead fields (v1: outreach-only).
        state = {
            "user_id": user_id,
            "lead_id": lead_id,
            "source": lead.get("source", ""),
            "company": lead.get("company", ""),
            "role": lead.get("role", ""),
            "jd_text": lead.get("jd_text", ""),
            "contact_name": lead.get("contact_name") or None,
            "contact_email": lead.get("contact_email") or None,
            "x_handle": lead.get("x_handle") or None,
            "resume_version": lead.get("resume_version") or None,
            "outreach_draft": lead.get("outreach_draft") or None,
            "listing_url": lead.get("listing_url") or None,
            "domain": lead.get("domain") or None,
            "channel": ["outreach"],
            "status": "in_review",
        }

        # Start graph execution — it will hit the review interrupt and pause
        graph.invoke(state, config)

        fed += 1
        label = lead.get("company") or lead.get("x_handle") or lead_id
        print(f"  Fed into graph: {label} ({lead_id})")

        try:
            repo.update_lead(user_id, lead_id, {"status": "in_review"})
        except Exception as e:
            print(f"Warning: fed lead {lead_id} into graph but failed to update status: {e}")

    print(f"\nfeed_graph: {fed} (lead, channel) runs fed, {skipped} already had active threads.")
    return fed


def main():
    """CLI-only entry point (`python -m orchestrator.feed_graph`) -- no HTTP
    caller, no real per-request user_id to thread through, so this
    legitimately falls back to db.current_user's single-operator stand-in
    (see feed_pending_leads' user_id=None default) rather than being a bug.
    """
    print("=" * 60)
    print("  GRAPH FEEDER — Loading pending_review leads into pipeline")
    print("=" * 60)
    print()

    count = feed_pending_leads()

    if count > 0:
        print(f"\nDone. Run 'python -m orchestrator.review_cli digest' to review.")
    print()


if __name__ == "__main__":
    main()
