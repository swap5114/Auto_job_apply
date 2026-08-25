"""Worker service entrypoint -- placeholder for Phase 0.

Phase 4 ("Pipeline Engine") is where this becomes the real authenticated
Cloud Run push-target for Cloud Tasks: it will receive a task per lead/user,
resume the LangGraph graph from the Postgres checkpointer scoped by
thread_id=user_id, run the Apply/Outreach router node, and report back.

Right now this only exists so the service is a real, deployable, health-
checkable Cloud Run container from day one -- Phase 0's job is the
skeleton, not the pipeline logic. Wiring Cloud Tasks -> this endpoint,
and the actual task-handling body, happens in Phase 4.
"""

from fastapi import FastAPI

app = FastAPI(title="AutoApply Worker", version="0.1.0")


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
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=f"Database not reachable: {e}")

    return {"status": "ready", "db": "ok"}


@app.post("/tasks/run")
def run_task():
    """Placeholder Cloud Tasks push target. Implemented in Phase 4."""
    return {"status": "not_implemented", "note": "Wired in Phase 4 (Pipeline Engine)"}
