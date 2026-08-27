"""Task dispatch — the single place that turns a (user_id, task_type,
payload) tuple into an actual orchestrator.pipeline_runner call.

Phase 4.4 needs this logic reachable from two different places:
  1. api/tasks.py's local-dev fallback (USE_CLOUD_TASKS=false): runs the
     task in-process on a background thread, same as api/main.py's
     pre-Phase-4 `_run_pipeline_bg` pattern.
  2. worker/main.py's `/tasks/run` (USE_CLOUD_TASKS=true): runs the task
     after verifying the request actually came from Cloud Tasks (or, for
     now, carries the correct shared-secret header -- see worker/main.py's
     module docstring for the real-OIDC gap this leaves open).

Keeping dispatch here means both paths call the exact same code -- the
worker's real, authenticated entry point and local dev's in-process
fallback can never silently drift into different behavior.
"""

from typing import Any, Optional

# Every task_type this dispatcher knows how to run. Kept as a small,
# explicit allowlist (not "whatever attribute name shows up in the
# payload") so a malformed/malicious task body can't reach for an
# arbitrary orchestrator function by name.
TASK_TYPE_SOURCING_PIPELINE = "sourcing_pipeline"
TASK_TYPE_FOLLOWUP_PIPELINE = "followup_pipeline"
TASK_TYPE_FEED_GRAPH = "feed_graph"
TASK_TYPE_CHECK_FOLLOWUPS = "check_followups"

VALID_TASK_TYPES = {
    TASK_TYPE_SOURCING_PIPELINE,
    TASK_TYPE_FOLLOWUP_PIPELINE,
    TASK_TYPE_FEED_GRAPH,
    TASK_TYPE_CHECK_FOLLOWUPS,
}


class UnknownTaskTypeError(ValueError):
    """Raised when a task payload names a task_type outside VALID_TASK_TYPES."""


def dispatch_task(user_id: str, task_type: str, payload: Optional[dict] = None) -> dict:
    """Run one task on behalf of user_id. Returns a small result dict.

    Args:
        user_id: whose data this task operates on -- always the real
            authenticated user_id the task was enqueued for (never a
            db.current_user fallback; there is no "local operator" concept
            once a task is flowing through Cloud Tasks/the worker).
        task_type: one of VALID_TASK_TYPES.
        payload: task-specific arguments (e.g. sourcing_pipeline's
            sources/yc_max_leads/x_max_leads/csv_path). Absent/empty for
            task types that take no extra arguments.

    Raises UnknownTaskTypeError for any task_type not in VALID_TASK_TYPES
    -- callers (api/tasks.py's fallback, worker/main.py's /tasks/run)
    should treat this as a 400, not a 500: it's a malformed request, not
    an internal failure.
    """
    if task_type not in VALID_TASK_TYPES:
        raise UnknownTaskTypeError(f"Unknown task_type: {task_type!r}")

    payload = payload or {}

    if task_type == TASK_TYPE_SOURCING_PIPELINE:
        from orchestrator.pipeline_runner import run_sourcing_pipeline

        summary = run_sourcing_pipeline(
            sources=payload.get("sources"),
            yc_max_leads=payload.get("yc_max_leads", 15),
            x_max_leads=payload.get("x_max_leads", 5),
            csv_path=payload.get("csv_path"),
            user_id=user_id,
        )
        return {"task_type": task_type, "result": summary}

    if task_type == TASK_TYPE_FOLLOWUP_PIPELINE:
        from orchestrator.pipeline_runner import run_followup_pipeline

        summary = run_followup_pipeline(user_id=user_id)
        return {"task_type": task_type, "result": summary}

    if task_type == TASK_TYPE_FEED_GRAPH:
        from orchestrator.feed_graph import feed_pending_leads

        count = feed_pending_leads(user_id=user_id)
        return {"task_type": task_type, "result": {"leads_fed": count}}

    if task_type == TASK_TYPE_CHECK_FOLLOWUPS:
        from orchestrator.check_followups import check_and_queue_followups

        count = check_and_queue_followups(user_id=user_id)
        return {"task_type": task_type, "result": {"followups_queued": count}}

    # Unreachable given the VALID_TASK_TYPES check above, but keeps mypy/
    # readers honest that every branch returns.
    raise UnknownTaskTypeError(f"Unknown task_type: {task_type!r}")
