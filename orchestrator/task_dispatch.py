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
TASK_TYPE_DEMO_BUILD = "demo_build"
TASK_TYPE_DEMO_REFINE = "demo_refine"

VALID_TASK_TYPES = {
    TASK_TYPE_SOURCING_PIPELINE,
    TASK_TYPE_FOLLOWUP_PIPELINE,
    TASK_TYPE_FEED_GRAPH,
    TASK_TYPE_CHECK_FOLLOWUPS,
    TASK_TYPE_DEMO_BUILD,
    TASK_TYPE_DEMO_REFINE,
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

    if task_type == TASK_TYPE_DEMO_BUILD:
        return _dispatch_demo_build(user_id, payload)

    if task_type == TASK_TYPE_DEMO_REFINE:
        return _dispatch_demo_refine(user_id, payload)

    raise UnknownTaskTypeError(f"Unknown task_type: {task_type!r}")


def _dispatch_demo_build(user_id: str, payload: dict) -> dict:
    from db import repository
    from sandbox import orchestrator

    build_id = payload.get("build_id", "")
    demo_project = payload.get("demo_project", {})
    company = payload.get("company", "")
    project_type = payload.get("project_type", "fullstack")

    keys = repository.get_user_provider_keys(user_id)
    repository.update_demo_build_status(user_id, build_id, stage="building", deploy_stage="exporting")

    state = orchestrator.start_build(demo_project, company=company, max_attempts=3)
    state.build_id = build_id

    repository.update_demo_build_status(
        user_id, build_id,
        stage=state.stage,
        error=state.error,
    )

    if state.stage == "success":
        try:
            state.project_dir = orchestrator.export_build_output(state)
            orchestrator.deploy_build(
                state,
                demo_project=demo_project,
                company=company,
                github_token=keys.get("github_token"),
                vercel_token=keys.get("vercel_token"),
                render_api_key=keys.get("render_api_key"),
                project_type=project_type,
            )
        finally:
            orchestrator.stop_build(state)

        repository.update_demo_build_status(
            user_id, build_id,
            stage=state.stage,
            deploy_stage=state.deploy_stage,
            repo_url=state.repo_url,
            frontend_url=state.frontend_url,
            backend_url=state.backend_url,
            deploy_error=state.deploy_error,
        )

    return {"build_id": build_id, "stage": state.stage, "deploy_stage": state.deploy_stage}


def _dispatch_demo_refine(user_id: str, payload: dict) -> dict:
    from db import repository
    from sandbox import orchestrator

    build_id = payload.get("build_id", "")
    refinement_prompt = payload.get("prompt", "")

    keys = repository.get_user_provider_keys(user_id)
    demo_row = repository.get_demo_build(user_id, build_id)
    demo_project = demo_row.get("spec_json", {})
    company = demo_row.get("company_name", "")
    project_type = demo_row.get("project_type", "fullstack")

    repository.add_refinement_turn(user_id, build_id, refinement_prompt, stage="building")

    # In a refinement turn, append the refinement instruction to demo_project description
    refined_project = dict(demo_project)
    existing_desc = refined_project.get("description", "")
    refined_project["description"] = f"{existing_desc}\n\n[REFINEMENT REVISION REQUEST]: {refinement_prompt}"

    state = orchestrator.start_build(refined_project, company=company, max_attempts=3)
    state.build_id = build_id

    if state.stage == "success":
        try:
            state.project_dir = orchestrator.export_build_output(state)
            orchestrator.deploy_build(
                state,
                demo_project=refined_project,
                company=company,
                github_token=keys.get("github_token"),
                vercel_token=keys.get("vercel_token"),
                render_api_key=keys.get("render_api_key"),
                project_type=project_type,
            )
        finally:
            orchestrator.stop_build(state)

    repository.update_demo_build_status(
        user_id, build_id,
        stage=state.stage,
        deploy_stage=state.deploy_stage,
        repo_url=state.repo_url or demo_row.get("repo_url"),
        frontend_url=state.frontend_url or demo_row.get("frontend_url"),
        backend_url=state.backend_url or demo_row.get("backend_url"),
        deploy_error=state.deploy_error,
    )

    return {"build_id": build_id, "stage": state.stage, "deploy_stage": state.deploy_stage}
