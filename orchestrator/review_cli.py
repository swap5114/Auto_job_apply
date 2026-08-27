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
                "active_channel": values.get("active_channel", "outreach"),
                "resume_version": values.get("resume_version", "N/A"),
                "outreach_draft": values.get("outreach_draft", "N/A"),
                "cover_note": values.get("cover_note", "N/A"),
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
        channel = lead.get("active_channel", "outreach")
        print(f"\n[{idx}] LEAD ID: {lead['lead_id']} [{channel}]")
        print(f"    Company: {lead['company']} | Role: {lead['role']} | Source: {lead['source']}")
        print(f"    Resume File: {lead['resume_version']}")
        print("    " + "-" * 72)
        if channel == "apply":
            print("    COVER NOTE:")
            note_lines = (lead.get("cover_note") or "N/A").splitlines()
            for line in note_lines:
                print(f"        {line}")
        else:
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

    Phase 5.2: a lead can have up to two independent threads (one per
    channel in Lead.channel), each with its own review checkpoint. A
    caller that already knows which channel it means (e.g. the apply
    review UI) passes channel explicitly and only that thread is
    considered. A caller that doesn't (e.g. existing outreach-only CLI/API
    call sites, or an already-in-flight pre-Phase-5 outreach thread) gets
    the same lookup order every one of them already relied on: try the
    legacy 2-arg thread_id first (make_thread_id(user_id, lead_id), i.e.
    channel=None), then fall back to trying "outreach" and "apply"
    explicitly -- this keeps every pre-Phase-5 caller's behavior
    unchanged while still resolving correctly for new dual-channel leads.

    Returns (thread_id, state) for the first matching paused-at-review
    thread found, or (None, None) if none match.
    """
    candidates = [channel] if channel is not None else [None, "outreach", "apply"]
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
    resolved_channel = state.values.get("active_channel") or "outreach"
    print(f"✅ [APPROVED] Lead '{lead_id}' ({resolved_channel}) approved successfully.")

    # The LangGraph checkpoint (above) is what actually drives the review
    # flow forward, but the leads table is the system of record for anything
    # querying/listing leads (the API, the dashboard). Syncing it here keeps
    # both in agreement. A failure here is loud (printed), not silent --
    # per the project's "never silently skip" rule -- but doesn't roll back
    # the already-resumed graph decision, since that resume already happened
    # and can't be un-done from here.
    #
    # For the apply channel, "approved" means the tailored resume + cover
    # note are ready to hand off -- the state-machine's own naming for
    # that is "ready_to_apply" (matched -> tailoring -> ready_to_apply ->
    # applied), distinct from outreach's "approved" (which still has a
    # send step ahead of it).
    lead_status = "ready_to_apply" if resolved_channel == "apply" else "approved"
    try:
        repo.update_lead(user_id, lead_id, {"status": lead_status, "review_decision": "approved"})
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
    contract -- identical here. Editing the apply channel's cover note
    (rather than the outreach draft) is a distinct flow -- see
    edit_apply_lead below -- since the interrupt payload/resume shape for
    that channel carries cover_note, not outreach_draft.
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
    print(f"✏️ [EDITED & APPROVED] Lead '{lead_id}' updated with new draft and approved.")

    try:
        repo.update_lead(user_id, lead_id, {
            "status": "approved", "outreach_draft": new_draft, "review_decision": "edited",
        })
    except Exception as e:
        print(f"⚠️ Warning: graph edited '{lead_id}' but failed to sync leads table status: {e}")

    return True


def edit_apply_lead(
    lead_id: str,
    new_cover_note: Optional[str] = None,
    user_id: Optional[str] = None,
    checkpointer=None,
) -> bool:
    """Resumes the apply-channel review checkpoint for lead_id with an
    edited cover note. Apply-channel counterpart to edit_lead (which
    edits outreach_draft) -- always resolves the "apply" channel's thread
    specifically, since a cover-note edit only ever makes sense there.
    """
    if user_id is None:
        user_id = get_current_user_id()
    if checkpointer is None:
        checkpointer = get_postgres_checkpointer()

    graph = build_pipeline_graph(checkpointer)
    thread_id = make_thread_id(user_id, lead_id, channel="apply")
    config = {"configurable": {"thread_id": thread_id}}

    state = graph.get_state(config)
    if not state or not state.next or "review" not in state.next:
        print(f"Error: Lead ID '{lead_id}' has no apply-channel review paused.")
        return False

    if not new_cover_note or not new_cover_note.strip():
        print("Error: Cover note cannot be empty.")
        return False

    decision = {
        "status": "approved",
        "cover_note": new_cover_note,
    }

    graph.invoke(Command(resume=decision), config)
    print(f"✏️ [EDITED & APPROVED] Lead '{lead_id}' (apply) updated with new cover note and approved.")

    try:
        repo.update_lead(user_id, lead_id, {
            "status": "ready_to_apply", "cover_note": new_cover_note, "review_decision": "edited",
        })
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
    approve_parser.add_argument(
        "--channel", choices=["apply", "outreach"], default=None,
        help="Which channel's review thread to approve, for leads paused on both (default: auto-detect)",
    )

    # edit command
    edit_parser = subparsers.add_parser("edit", help="Edit draft and approve a lead by lead_id")
    edit_parser.add_argument("lead_id", help="Lead ID to edit")
    edit_parser.add_argument("--draft", help="Optional new outreach draft text", default=None)
    edit_parser.add_argument(
        "--channel", choices=["apply", "outreach"], default=None,
        help="Which channel's review thread to edit, for leads paused on both (default: auto-detect)",
    )

    # reject command
    reject_parser = subparsers.add_parser("reject", help="Reject a lead by lead_id")
    reject_parser.add_argument("lead_id", help="Lead ID to reject")
    reject_parser.add_argument(
        "--channel", choices=["apply", "outreach"], default=None,
        help="Which channel's review thread to reject, for leads paused on both (default: auto-detect)",
    )

    args = parser.parse_args()

    if args.command in ("digest", "list") or not args.command:
        print_digest()
    elif args.command == "approve":
        approve_lead(args.lead_id, channel=args.channel)
    elif args.command == "edit":
        if args.channel == "apply":
            edit_apply_lead(args.lead_id, args.draft)
        else:
            edit_lead(args.lead_id, args.draft, channel=args.channel)
    elif args.command == "reject":
        reject_lead(args.lead_id, channel=args.channel)


if __name__ == "__main__":
    main()
