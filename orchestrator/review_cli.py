import os
import sys
import argparse
from typing import List, Dict, Any, Optional

from langgraph.types import Command
from langgraph.checkpoint.sqlite import SqliteSaver
from graph.pipeline import (
    build_pipeline_graph,
    get_postgres_checkpointer,
    make_thread_id,
)
from db import repository as repo
from db.current_user import get_current_user_id


def get_all_thread_ids(user_id: Optional[str] = None, checkpointer=None) -> List[str]:
    """Queries the checkpoints table for registered thread IDs.

    Args:
        user_id: if given, only thread IDs scoped to that user (thread_id
            prefix f"{user_id}:") are returned -- this is what makes
            get_pending_review_leads/print_digest safe to call per-request
            from the API without leaking another tenant's paused leads. If
            None (the CLI's default, single-operator usage), every
            thread_id is returned, matching the CLI's pre-Phase-4 behavior.
        checkpointer: injected checkpointer instance to query against.
            Defaults to the real Postgres checkpointer
            (get_postgres_checkpointer()) -- tests pass a SqliteSaver
            instead (see tests/test_phase7_review.py) to keep using a
            fast, disposable, file-based checkpointer without touching
            Postgres.
    """
    if checkpointer is None:
        checkpointer = get_postgres_checkpointer()

    if isinstance(checkpointer, SqliteSaver):
        cursor = checkpointer.conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
            rows = cursor.fetchall()
        except Exception:
            rows = []
        thread_ids = [row[0] for row in rows if row[0]]
    else:
        from psycopg.rows import tuple_row

        pool = checkpointer.conn  # ConnectionPool, per get_postgres_checkpointer()
        with pool.connection() as conn:
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("SELECT DISTINCT thread_id FROM checkpoints")
                rows = cur.fetchall()
        thread_ids = [row[0] for row in rows if row[0]]

    if user_id is not None:
        prefix = f"{user_id}:"
        thread_ids = [t for t in thread_ids if t.startswith(prefix)]
    return thread_ids


def get_pending_review_leads(user_id: Optional[str] = None, checkpointer=None) -> List[Dict[str, Any]]:
    """Iterates through graph threads and returns state details for those
    paused at review, scoped to user_id (see get_all_thread_ids).
    """
    if checkpointer is None:
        checkpointer = get_postgres_checkpointer()
    graph = build_pipeline_graph(checkpointer)
    thread_ids = get_all_thread_ids(user_id, checkpointer=checkpointer)
    
    pending = []
    for thread_id in thread_ids:
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        if state and state.next and "review" in state.next:
            values = state.values
            pending.append({
                "thread_id": thread_id,
                "lead_id": values.get("lead_id", thread_id),
                "company": values.get("company", "N/A"),
                "role": values.get("role", "N/A"),
                "source": values.get("source", "N/A"),
                "resume_version": values.get("resume_version", "N/A"),
                "outreach_draft": values.get("outreach_draft", "N/A"),
                "status": values.get("status", "pending_review")
            })
    return pending


def print_digest(user_id: Optional[str] = None, checkpointer=None) -> None:
    """Prints a clear summary digest of all leads currently waiting at the review checkpoint."""
    pending = get_pending_review_leads(user_id, checkpointer=checkpointer)
    
    print("\n" + "=" * 80)
    print(f"               PENDING REVIEW DIGEST ({len(pending)} leads paused)")
    print("=" * 80)
    
    if not pending:
        print("No leads currently paused for review.")
        print("=" * 80 + "\n")
        return

    for idx, lead in enumerate(pending, 1):
        print(f"\n[{idx}] LEAD ID: {lead['lead_id']}")
        print(f"    Company: {lead['company']} | Role: {lead['role']} | Source: {lead['source']}")
        print(f"    Resume File: {lead['resume_version']}")
        print("    " + "-" * 72)
        print("    OUTREACH DRAFT:")
        draft_lines = (lead.get("outreach_draft") or "N/A").splitlines()
        for line in draft_lines:
            print(f"        {line}")
        print("    " + "-" * 72)

    print(f"\nTo take action, run:")
    print("    python -m orchestrator.review_cli approve <lead_id>")
    print("    python -m orchestrator.review_cli edit <lead_id> [--draft \"...\"]")
    print("    python -m orchestrator.review_cli reject <lead_id>")
    print("=" * 80 + "\n")


def _resolve_paused_review_thread(graph, user_id: str, lead_id: str, channel: Optional[str]):
    """Finds the checkpoint thread currently paused at review for
    (user_id, lead_id), scoped to a specific channel when given.

    v1 is outreach-only. We try the legacy 2-arg thread_id first
    (make_thread_id(user_id, lead_id), i.e. channel=None), then the
    "outreach" channel thread that feed_graph now writes. The `channel`
    param is retained (defaulting to None) for backward-compatible call
    sites but only ever resolves outreach.

    Returns (thread_id, state) for the first matching paused-at-review
    thread found, or (None, None) if none match.
    """
    candidates = [channel] if channel is not None else [None, "outreach"]
    for candidate in candidates:
        thread_id = make_thread_id(user_id, lead_id, channel=candidate)
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        if state and state.next and "review" in state.next:
            return thread_id, state
    return None, None


def approve_lead(
    lead_id: str,
    user_id: Optional[str] = None,
    checkpointer=None,
    channel: Optional[str] = None,
) -> bool:
    """Resumes the review checkpoint for lead_id with an approval decision.

    Args:
        user_id: whose lead this is -- required to construct the correct
            thread_id (Phase 4.2's f"{user_id}:{lead_id}" scheme) and to
            sync the leads table afterward with the right tenant. Every
            HTTP-reachable caller (api/main.py's /api/leads/{lead_id}/approve
            route) MUST pass the real authenticated user_id. Defaults to
            db.current_user's single-operator stand-in only for the CLI
            entry point below, which has no per-request identity.
        checkpointer: injected checkpointer (see get_all_thread_ids) --
            defaults to the real Postgres checkpointer.
        channel: which of the lead's (up to two) channel-scoped review
            threads to resume (Phase 5.2). None (the default) resolves
            to whichever one is actually paused at review, trying the
            legacy unscoped thread first -- see
            _resolve_paused_review_thread's docstring.
    """
    if user_id is None:
        user_id = get_current_user_id()
    if checkpointer is None:
        checkpointer = get_postgres_checkpointer()

    graph = build_pipeline_graph(checkpointer)
    thread_id, state = _resolve_paused_review_thread(graph, user_id, lead_id, channel)

    if thread_id is None:
        print(f"Error: Lead ID '{lead_id}' is not currently paused at review.")
        return False

    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(Command(resume="approved"), config)

    # The graph ran through send_node on approval, so the TRUE resulting
    # status is whatever send_node produced (sent / draft_created /
    # approved_needs_gmail / send_failed), not a flat "approved". Read it back
    # from the checkpoint and sync THAT to the leads table (the system of
    # record the dashboard/API read), so the dashboard reflects reality
    # instead of a stale "approved". Fall back to "approved" if the state is
    # somehow unreadable.
    final = graph.get_state(config)
    final_status = (final.values.get("status") if (final and final.values) else None) or "approved"
    print(f"✅ [APPROVED] Lead '{lead_id}' -> {final_status}.")

    update_fields = {"status": final_status, "review_decision": "approved"}
    if final and final.values:
        if final.values.get("contact_email"):
            update_fields["contact_email"] = final.values["contact_email"]
        if final.values.get("contact_name"):
            update_fields["contact_name"] = final.values["contact_name"]

    try:
        repo.update_lead(user_id, lead_id, update_fields)
    except Exception as e:
        print(f"⚠️ Warning: graph approved '{lead_id}' but failed to sync leads table status: {e}")

    return True


def edit_lead(
    lead_id: str,
    new_draft: Optional[str] = None,
    user_id: Optional[str] = None,
    checkpointer=None,
    channel: Optional[str] = None,
) -> bool:
    """Resumes the review checkpoint for lead_id with an edited outreach draft.

    See approve_lead's docstring for the user_id/checkpointer/channel
    contract -- identical here.
    """
    if user_id is None:
        user_id = get_current_user_id()
    if checkpointer is None:
        checkpointer = get_postgres_checkpointer()

    graph = build_pipeline_graph(checkpointer)
    thread_id, state = _resolve_paused_review_thread(graph, user_id, lead_id, channel)

    if thread_id is None:
        print(f"Error: Lead ID '{lead_id}' is not currently paused at review.")
        return False

    config = {"configurable": {"thread_id": thread_id}}

    current_draft = state.values.get("outreach_draft", "")
    if not new_draft:
        print(f"\nEditing outreach draft for lead '{lead_id}':")
        print("--- CURRENT DRAFT ---")
        print(current_draft)
        print("---------------------")
        print("Enter new outreach draft below (press Ctrl+Z or Ctrl+D on empty line to save):")
        try:
            new_draft = sys.stdin.read().strip()
        except KeyboardInterrupt:
            print("\nEdit cancelled.")
            return False

    if not new_draft:
        print("Error: Outreach draft cannot be empty.")
        return False

    decision = {
        "status": "approved",
        "outreach_draft": new_draft
    }

    graph.invoke(Command(resume=decision), config)

    final = graph.get_state(config)
    final_status = (final.values.get("status") if (final and final.values) else None) or "approved"
    print(f"✏️ [EDITED & APPROVED] Lead '{lead_id}' updated with new draft -> {final_status}.")

    update_fields = {
        "status": final_status, "outreach_draft": new_draft, "review_decision": "edited",
    }
    if final and final.values:
        if final.values.get("contact_email"):
            update_fields["contact_email"] = final.values["contact_email"]
        if final.values.get("contact_name"):
            update_fields["contact_name"] = final.values["contact_name"]

    try:
        repo.update_lead(user_id, lead_id, update_fields)
    except Exception as e:
        print(f"⚠️ Warning: graph edited '{lead_id}' but failed to sync leads table status: {e}")

    return True


def reject_lead(
    lead_id: str,
    user_id: Optional[str] = None,
    checkpointer=None,
    channel: Optional[str] = None,
) -> bool:
    """Resumes the review checkpoint for lead_id with a rejection decision.

    See approve_lead's docstring for the user_id/checkpointer/channel
    contract -- identical here.
    """
    if user_id is None:
        user_id = get_current_user_id()
    if checkpointer is None:
        checkpointer = get_postgres_checkpointer()

    graph = build_pipeline_graph(checkpointer)
    thread_id, state = _resolve_paused_review_thread(graph, user_id, lead_id, channel)

    if thread_id is None:
        print(f"Error: Lead ID '{lead_id}' is not currently paused at review.")
        return False

    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(Command(resume="rejected"), config)
    print(f"❌ [REJECTED] Lead '{lead_id}' rejected.")

    try:
        repo.update_lead(user_id, lead_id, {"status": "rejected", "review_decision": "rejected"})
    except Exception as e:
        print(f"⚠️ Warning: graph rejected '{lead_id}' but failed to sync leads table status: {e}")

    return True


def main():
    parser = argparse.ArgumentParser(description="LangGraph Human Review CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Sub-command help")

    # digest / list command
    subparsers.add_parser("digest", help="Display summary digest of all leads pending review")
    subparsers.add_parser("list", help="Display summary digest of all leads pending review")

    # approve command
    approve_parser = subparsers.add_parser("approve", help="Approve a lead by lead_id")
    approve_parser.add_argument("lead_id", help="Lead ID to approve")

    # edit command
    edit_parser = subparsers.add_parser("edit", help="Edit draft and approve a lead by lead_id")
    edit_parser.add_argument("lead_id", help="Lead ID to edit")
    edit_parser.add_argument("--draft", help="Optional new outreach draft text", default=None)

    # reject command
    reject_parser = subparsers.add_parser("reject", help="Reject a lead by lead_id")
    reject_parser.add_argument("lead_id", help="Lead ID to reject")

    args = parser.parse_args()

    if args.command in ("digest", "list") or not args.command:
        print_digest()
    elif args.command == "approve":
        approve_lead(args.lead_id)
    elif args.command == "edit":
        edit_lead(args.lead_id, args.draft)
    elif args.command == "reject":
        reject_lead(args.lead_id)


if __name__ == "__main__":
    main()
