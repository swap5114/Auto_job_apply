"""Follow-up checker — starts the follow-up graph for sent leads.

This is the cron entry point that:
1. Reads all 'sent' leads from Postgres
2. Starts a followup_graph run for each one
3. The graph checks for replies, drafts follow-ups if needed,
   and pauses at the review interrupt

Usage:
    python -m orchestrator.check_followups
"""

import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from db import repository as repo
from db.current_user import get_current_user_id
from graph.pipeline import (
    build_followup_graph,
    get_postgres_checkpointer,
    make_followup_thread_id,
)


def check_and_queue_followups(user_id: Optional[str] = None) -> int:
    """Check all of user_id's sent leads for follow-up needs via the
    followup graph.

    Args:
        user_id: whose sent leads to check. Every HTTP-reachable caller
            (api/main.py's /api/pipeline/check-followups route, and
            orchestrator.pipeline_runner.run_followup_pipeline when invoked
            on behalf of a real request) MUST pass the real authenticated
            user_id -- defaulting to db.current_user's single-operator
            stand-in is only correct for the CLI entry point below and
            orchestrator.scheduler's cron trigger (neither has a real
            per-request identity to thread through).

    Returns the number of leads that entered the follow-up flow.
    """
    if user_id is None:
        user_id = get_current_user_id()

    cp = get_postgres_checkpointer()
    graph = build_followup_graph(cp)

    leads = repo.get_leads(user_id, status="sent")

    if not leads:
        print("No sent leads to check for follow-ups.")
        return 0

    queued = 0
    replied = 0

    for lead in leads:
        lead_id = lead.get("id")
        if not lead_id:
            continue

        company = lead.get("company") or lead.get("x_handle") or lead_id

        # Use a unique thread ID for follow-up runs to avoid collision
        # with the main pipeline thread for the same lead, scoped by
        # user_id (Phase 4.2) for structural tenant isolation.
        thread_id = make_followup_thread_id(user_id, lead_id, lead.get("followup_count", 0))
        config = {"configurable": {"thread_id": thread_id}}

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
            "channel": lead.get("channel") or [],
            "followup_count": int(lead.get("followup_count") or 0),
            "is_followup": False,  # followup_check_node will set this if needed
            "status": "sent",
            # M-1: pass the sent timestamp so reply detection only looks at
            # mail received after we actually reached out.
            "sent_at": (str(lead.get("sent_at")) if lead.get("sent_at") else ""),
        }

        try:
            graph.invoke(state, config)

            now = datetime.now(timezone.utc)

            # Check if it paused at review (meaning a follow-up draft was generated)
            final_state = graph.get_state(config)
            if final_state and final_state.next and "review" in final_state.next:
                queued += 1
                # C-4: persist the advanced followup_count back to the lead.
                # followup_check_node increments it in graph state, but if we
                # never write it back, the leads table stays at the old value,
                # so the NEXT sweep rebuilds the SAME make_followup_thread_id
                # and re-invokes an already-completed thread instead of
                # starting a fresh follow-up cycle. Persisting it makes each
                # cycle's thread_id distinct and keeps MAX_FOLLOWUPS honest.
                new_count = (
                    int(final_state.values.get("followup_count") or 0)
                    if final_state.values else int(lead.get("followup_count") or 0)
                )
                _safe_update(user_id, lead_id, {"last_checked": now, "followup_count": new_count})
                print(f"  📋 {company} — follow-up draft queued for review "
                      f"(thread: {thread_id}, followup_count -> {new_count})")
            else:
                # Ran to END — either replied, max followups, or check failed.
                status = final_state.values.get("status", "unknown") if final_state else "unknown"
                if status == "replied":
                    # v1 Task 7: persist the reply so the dashboard reflects it.
                    # Reply detection lives only in the graph state otherwise --
                    # the leads table (what the API/dashboard read) never learned
                    # about it before this write.
                    _safe_update(user_id, lead_id, {
                        "status": "replied", "replied_at": now, "last_checked": now,
                    })
                    replied += 1
                    print(f"  💬 {company} — REPLY detected, marked replied")
                else:
                    _safe_update(user_id, lead_id, {"last_checked": now})
                    print(f"  ✓  {company} — no follow-up needed (status: {status})")

        except Exception as e:
            print(f"  ❌ Error processing {company}: {e}")

    if replied:
        print(f"\ncheck_followups: {replied} reply(ies) detected and marked.")
    return queued


def _safe_update(user_id: str, lead_id: str, fields: dict) -> None:
    """Best-effort lead update -- a persistence failure is logged loudly (per
    the project's 'never silently skip' rule) but doesn't abort the whole
    follow-up sweep for the remaining leads."""
    try:
        repo.update_lead(user_id, lead_id, fields)
    except Exception as e:
        print(f"  ⚠️  failed to persist follow-up update for lead {lead_id}: {e}")


def main():
    print("=" * 60)
    print("  FOLLOW-UP CHECKER — Checking sent leads for reply status")
    print("=" * 60)
    print()

    count = check_and_queue_followups()

    if count > 0:
        print(f"\n{count} follow-up drafts queued. Run review_cli digest to act on them.")
    print()


if __name__ == "__main__":
    main()
