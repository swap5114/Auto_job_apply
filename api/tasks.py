"""Cloud Tasks client wrapper (Phase 4.4) -- enqueues pipeline work onto
worker/main.py's `/tasks/run` push target.

Local dev fallback (USE_CLOUD_TASKS=false, the default): runs the task
in-process on a daemon thread, exactly like api/main.py's pre-Phase-4
`_run_pipeline_bg` pattern -- no real GCP dependency required to
`docker compose up` locally. Same env-flag-gated spirit as
ENABLE_SCHEDULER (see api/main.py's lifespan docstring).

Real Cloud Tasks mode (USE_CLOUD_TASKS=true): pushes an HTTP task at
WORKER_URL + "/tasks/run", authenticated via an OIDC token Cloud Tasks
attaches automatically when the queue's target is configured with a
service-account OIDC token (see CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL below).
worker/main.py's own /tasks/run verifies that token (see its module
docstring for the current, intentionally-flagged gap: a shared-secret
header is checked today as a stopgap since full OIDC audience
verification isn't wired up in this phase).
"""

import json
import os
import threading
import uuid
from typing import Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

# --- Config -----------------------------------------------------------------

USE_CLOUD_TASKS = os.getenv("USE_CLOUD_TASKS", "false").lower() == "true"

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCP_LOCATION = os.getenv("GCP_TASKS_LOCATION", "us-central1")
CLOUD_TASKS_QUEUE = os.getenv("CLOUD_TASKS_QUEUE", "autoapply-pipeline")
WORKER_URL = os.getenv("WORKER_URL", "").rstrip("/")
CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL = os.getenv("CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL", "")

# Shared-secret header, checked by worker/main.py's /tasks/run as a stopgap
# authentication mechanism -- see that module's docstring for why this
# isn't full OIDC verification yet, and the security implication of that gap.
WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET", "")


def _local_dispatch(user_id: str, task_type: str, payload: Optional[dict]) -> None:
    """Runs the task in-process on a daemon thread (local dev fallback)."""
    from orchestrator.task_dispatch import dispatch_task

    def _run():
        try:
            dispatch_task(user_id, task_type, payload)
        except Exception as e:
            print(f"  ❌ local task dispatch failed (user={user_id}, task_type={task_type}): {e}")

    threading.Thread(target=_run, daemon=True).start()


def enqueue_pipeline_task(
    user_id: str,
    task_type: str,
    payload: Optional[dict] = None,
) -> dict:
    """Enqueue one pipeline task for user_id.

    With USE_CLOUD_TASKS=false (default, local dev): runs the task
    in-process on a background thread and returns immediately -- the same
    "fire and forget, poll status separately" contract callers already
    expect from api/main.py's pipeline routes.

    With USE_CLOUD_TASKS=true: creates a real Cloud Tasks task pointing at
    WORKER_URL + "/tasks/run", which Cloud Tasks will push to (with
    automatic retries per the queue's own retry config -- this is a
    separate retry layer from skills/llm_client.py's LLM-level retries;
    see PHASE_4_PLAN.md's note on not letting the two multiply delay
    unpredictably. Cloud Tasks' queue-level retry only re-runs a whole
    task on a 5xx/timeout from the worker, it does not retry individual
    LLM calls -- those already succeeded-or-gave-up inside llm_generate()
    before the task handler returns).

    Returns a small dict describing what happened -- {"mode": "local"} or
    {"mode": "cloud_tasks", "task_name": ...}.
    """
    if not user_id:
        raise ValueError("enqueue_pipeline_task requires a user_id")

    from orchestrator.task_dispatch import VALID_TASK_TYPES, UnknownTaskTypeError

    if task_type not in VALID_TASK_TYPES:
        raise UnknownTaskTypeError(f"Unknown task_type: {task_type!r}")

    if not USE_CLOUD_TASKS:
        _local_dispatch(user_id, task_type, payload)
        return {"mode": "local", "task_type": task_type}

    return _enqueue_cloud_task(user_id, task_type, payload)


def _enqueue_cloud_task(user_id: str, task_type: str, payload: Optional[dict]) -> dict:
    """Creates a real Cloud Tasks HTTP task targeting worker/main.py's
    /tasks/run. Requires GCP_PROJECT_ID and WORKER_URL to be configured --
    raises a clear RuntimeError rather than silently falling back to the
    local thread path if USE_CLOUD_TASKS=true but the config is incomplete
    (a misconfigured prod deployment should fail loudly, not quietly
    process tasks in-process on whichever replica happened to receive the
    HTTP request that enqueued them).
    """
    if not GCP_PROJECT_ID or not WORKER_URL:
        raise RuntimeError(
            "USE_CLOUD_TASKS=true but GCP_PROJECT_ID and/or WORKER_URL is not "
            "set in config/.env. Both are required to create a real Cloud "
            "Tasks task -- set them, or set USE_CLOUD_TASKS=false for local dev."
        )

    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(GCP_PROJECT_ID, GCP_LOCATION, CLOUD_TASKS_QUEUE)

    body = {
        "user_id": user_id,
        "task_type": task_type,
        "payload": payload or {},
        # Lets worker/main.py log/dedupe by a stable id if it ever needs to.
        "task_id": str(uuid.uuid4()),
    }

    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": f"{WORKER_URL}/tasks/run",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body).encode("utf-8"),
    }

    if CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL:
        # Cloud Tasks attaches a real OIDC ID token for this service
        # account to the outgoing request when configured this way --
        # worker/main.py's /tasks/run is meant to verify that token's
        # audience/issuer (see that module's docstring for the current
        # stopgap state of that verification).
        http_request["oidc_token"] = {
            "service_account_email": CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL,
            "audience": WORKER_URL,
        }
    elif WORKER_SHARED_SECRET:
        http_request["headers"]["X-Worker-Shared-Secret"] = WORKER_SHARED_SECRET

    task = {"http_request": http_request}

    created = client.create_task(request={"parent": parent, "task": task})
    return {"mode": "cloud_tasks", "task_type": task_type, "task_name": created.name}
