import os
import sys
import argparse
import sqlite3
from typing import List, Dict, Any, Optional

from langgraph.types import Command
from graph.pipeline import build_pipeline_graph, get_checkpointer_connection, DB_PATH

try:
    from storage.sheet_client import update_lead
    SHEET_CLIENT_AVAILABLE = True
except Exception:
    SHEET_CLIENT_AVAILABLE = False


def get_all_thread_ids(db_path: str = DB_PATH) -> List[str]:
    """Queries SQLite checkpoints table for all registered thread IDs."""
    if not os.path.exists(db_path):
        return []
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        rows = cursor.fetchall()
        return [row[0] for row in rows if row[0]]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_pending_review_leads(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Iterates through all graph threads and returns state details for those paused at review."""
    cp = get_checkpointer_connection(db_path)
    graph = build_pipeline_graph(cp)
    thread_ids = get_all_thread_ids(db_path)
    
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


def print_digest(db_path: str = DB_PATH) -> None:
    """Prints a clear summary digest of all leads currently waiting at the review checkpoint."""
    pending = get_pending_review_leads(db_path)
    
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
        draft_lines = lead['outreach_draft'].splitlines()
        for line in draft_lines:
            print(f"        {line}")
        print("    " + "-" * 72)

    print(f"\nTo take action, run:")
    print("    python -m orchestrator.review_cli approve <lead_id>")
    print("    python -m orchestrator.review_cli edit <lead_id> [--draft \"...\"]")
    print("    python -m orchestrator.review_cli reject <lead_id>")
    print("=" * 80 + "\n")


def approve_lead(lead_id: str, db_path: str = DB_PATH) -> bool:
    """Resumes the review checkpoint for lead_id with an approval decision."""
    cp = get_checkpointer_connection(db_path)
    graph = build_pipeline_graph(cp)
    config = {"configurable": {"thread_id": lead_id}}
    
    state = graph.get_state(config)
    if not state or not state.next or "review" not in state.next:
        print(f"Error: Lead ID '{lead_id}' is not currently paused at review.")
        return False

    graph.invoke(Command(resume="approved"), config)
    print(f"✅ [APPROVED] Lead '{lead_id}' approved successfully.")

    if SHEET_CLIENT_AVAILABLE:
        try:
            update_lead(lead_id, {"status": "approved", "review_decision": "approved"})
        except Exception as e:
            print(f"⚠️ Warning: Could not update Google Sheet status for lead '{lead_id}': {e}")

    return True


def edit_lead(lead_id: str, new_draft: Optional[str] = None, db_path: str = DB_PATH) -> bool:
    """Resumes the review checkpoint for lead_id with an edited outreach draft."""
    cp = get_checkpointer_connection(db_path)
    graph = build_pipeline_graph(cp)
    config = {"configurable": {"thread_id": lead_id}}
    
    state = graph.get_state(config)
    if not state or not state.next or "review" not in state.next:
        print(f"Error: Lead ID '{lead_id}' is not currently paused at review.")
        return False

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

    if SHEET_CLIENT_AVAILABLE:
        try:
            update_lead(lead_id, {"status": "approved", "outreach_draft": new_draft, "review_decision": "edited"})
        except Exception as e:
            print(f"⚠️ Warning: Could not update Google Sheet status for lead '{lead_id}': {e}")

    return True


def reject_lead(lead_id: str, db_path: str = DB_PATH) -> bool:
    """Resumes the review checkpoint for lead_id with a rejection decision."""
    cp = get_checkpointer_connection(db_path)
    graph = build_pipeline_graph(cp)
    config = {"configurable": {"thread_id": lead_id}}
    
    state = graph.get_state(config)
    if not state or not state.next or "review" not in state.next:
        print(f"Error: Lead ID '{lead_id}' is not currently paused at review.")
        return False

    graph.invoke(Command(resume="rejected"), config)
    print(f"❌ [REJECTED] Lead '{lead_id}' rejected.")

    if SHEET_CLIENT_AVAILABLE:
        try:
            update_lead(lead_id, {"status": "rejected", "review_decision": "rejected"})
        except Exception as e:
            print(f"⚠️ Warning: Could not update Google Sheet status for lead '{lead_id}': {e}")

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
