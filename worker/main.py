"""Worker service entrypoint -- the authenticated Cloud Tasks push-target
for pipeline work (Phase 4.4).

Receives one task per (user_id, task_type) pair from api/tasks.py's
enqueue_pipeline_task (real Cloud Tasks in production, or, in local dev
with USE_CLOUD_TASKS=false, api/tasks.py never calls this endpoint at all
-- it runs the task in-process instead; see that module's docstring).
Dispatches to orchestrator.task_dispatch.dispatch_task, which resumes the
LangGraph pipeline against the Postgres checkpointer (graph/pipeline.py's
get_postgres_checkpointer()), scoped by thread_id=f"{user_id}:{lead_id}".

SECURITY NOTE -- read this before deploying with USE_CLOUD_TASKS=true:
This endpoint is only as safe as its caller verification, and that
verification is INTENTIONALLY INCOMPLETE in this phase. What's implemented
today is a shared-secret header check (WORKER_SHARED_SECRET, compared with
hmac.compare_digest to avoid a timing side-channel) -- NOT full OIDC audience
verification of a Cloud Tasks-issued ID token. Real Cloud Tasks, configured
with an oidc_token target (see api/tasks.py's _enqueue_cloud_task), does
attach a verifiable Google-signed ID token to the request; this endpoint
does not yet verify that token's signature/audience/issuer. Until that
verification is added, an attacker who obtains (or guesses) the shared
secret -- or reaches this endpoint before it's put behind Cloud Run's own
IAM-based ingress control -- could trigger pipeline work against arbitrary
user_ids. Mitigations that DO apply today: (1) WORKER_SHARED_SECRET is a
long random value stored only in config/.env (gitignored) and Cloud Run's
env, never in client code; (2) In production, Cloud Run should be deployed
with --no-allow-unauthenticated and the invoker role restricted to the
Cloud Tasks queue's service account, which is the real access boundary --
the shared-secret header is a defense-in-depth belt, not the primary lock.
Full OIDC verification (`google.oauth2.id_token.verify_oauth2_token` against
WORKER_URL as the audience) is the natural follow-up hardening and is
flagged here, not silently deferred.
"""

import hmac
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET", "")

app = FastAPI(title="AutoApply Worker", version="0.2.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "autoapply-worker"}


@app.get("/ready")
def ready():
    from sqlalchemy import text
    from db.session import get_engine

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database not reachable: {e}")

    return {"status": "ready", "db": "ok"}


def _verify_request(request: Request) -> None:
    """Raises 401 unless the request carries a valid WORKER_SHARED_SECRET
    header. See this module's docstring for what this does and doesn't
    protect against.

    If WORKER_SHARED_SECRET isn't configured at all, this is a backend
    configuration problem in any environment where USE_CLOUD_TASKS=true --
    fail closed (401 on every request) rather than silently accepting
    everything, matching api/auth.py's "no soft auth mode" rule.
    """
    if not WORKER_SHARED_SECRET:
        raise HTTPException(
            status_code=401,
            detail=(
                "WORKER_SHARED_SECRET is not configured on this worker -- "
                "refusing every /tasks/run request until it is set. See "
                "config/.env.example."
            ),
        )

    provided = request.headers.get("x-worker-shared-secret", "")
    if not provided or not hmac.compare_digest(provided, WORKER_SHARED_SECRET):
        raise HTTPException(status_code=401, detail="Missing or invalid worker authentication")


@app.post("/tasks/run")
async def run_task(request: Request):
    """Cloud Tasks push target -- verifies the caller, deserializes the
    task payload, and dispatches to the right orchestrator function.

    Expected body (see api/tasks.py's _enqueue_cloud_task):
        {"user_id": "...", "task_type": "...", "payload": {...}, "task_id": "..."}
    """
    _verify_request(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    user_id = body.get("user_id")
    task_type = body.get("task_type")
    payload = body.get("payload") or {}

    if not user_id or not task_type:
        raise HTTPException(status_code=400, detail="Request body requires user_id and task_type")

    from orchestrator.task_dispatch import dispatch_task, UnknownTaskTypeError

    try:
        result = dispatch_task(user_id=user_id, task_type=task_type, payload=payload)
    except UnknownTaskTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # A 5xx here is what tells Cloud Tasks to retry per the queue's own
        # retry config -- don't swallow this into a 200, or a genuinely
        # failed task (e.g. a transient DB blip) would never be retried.
        raise HTTPException(status_code=500, detail=f"Task failed: {e}")

    return {"status": "success", **result}
