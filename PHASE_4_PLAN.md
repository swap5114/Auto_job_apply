# Phase 4: Pipeline Engine

## Objective

Make background pipeline processing (scraping, tailoring, drafting, review, sending, follow-ups)
durable and correctly scoped per-user, so two different signed-in users' pipelines can run at the
same time without colliding, and a worker restart mid-run resumes exactly where it left off. This
is the phase where the lean, in-process background-thread approach from the earlier re-plan gets
replaced with the real thing, now that Phase 3 gives every request a real `user_id`.

## Where we actually stand right now (read this before starting)

- **Auth is real.** `api/auth.py`'s `get_authenticated_user_id` is wired onto every `/api/pipeline/*`,
  `/api/leads/*`, `/api/settings/*`, `/api/builds*`, `/api/scheduler/*` route already (confirmed by
  grep across `api/main.py` — every one of them takes `user_id: str = Depends(get_authenticated_user_id)`).
  Phase 3 did more of this than its own plan required — good, it means Phase 4 starts from a
  correctly-authenticated API, not a partially-open one.
- **The gap Phase 4 exists to close**: those routes resolve a real per-request `user_id`, but
  everything downstream of them still isn't user-aware in the way that matters for concurrency:
  - `api/main.py`'s `/api/pipeline/run` background work (`_run_pipeline_bg`) uses ONE global
    `_pipeline_run_state` dict + ONE global `_pipeline_lock` (line ~879). Two different signed-in
    users hitting "run pipeline" at the same time will collide — the second call gets a 409
    "Pipeline already running" even though it's a different person's pipeline. This is the
    single biggest concurrency bug this phase must fix.
  - `graph/pipeline.py`'s `PipelineState` (TypedDict) has no `user_id` field at all. Every node
    (`find_email_node`, `tailor_resume_node`, etc.) calls skill functions that now require a
    `user_id` argument (Phase 0 made every `db.repository` function user-scoped) — but the graph
    itself never threads one through. Check each node's skill call carefully; some may currently
    be silently falling back to `db.current_user.get_current_user_id()` inside the skill layer
    instead of using the real per-request user, which would leak Phase 3's whole point.
  - `graph/pipeline.py`'s checkpointer is a single fixed-path SQLite file (`DB_PATH =
    storage/checkpoints.sqlite`, `SqliteSaver`) shared by every user and every lead. `thread_id`
    is currently just `lead_id` — not `{user_id}:{lead_id}` or similar — so if two different
    users' leads ever got the same UUID (astronomically unlikely with real UUIDs, but the
    isolation should be structural, not probabilistic) there'd be no scoping boundary at all.
    SQLite also isn't safe across multiple worker processes writing concurrently — fine for one
    dev process, not fine for "two users' pipelines running at once" in any real deployment.
  - `orchestrator/feed_graph.py`, `orchestrator/check_followups.py`, and (per its own docstring)
    `orchestrator/review_cli.py` all call `db.current_user.get_current_user_id()` directly — the
    Phase 0 single-operator stand-in — not a real per-user id. This was correct when they were
    CLI-only tools with no HTTP caller. It stops being correct the moment `/api/pipeline/feed-graph`
    (already Depends-wrapped with real auth per the grep above) calls `feed_pending_leads()` on
    behalf of a real signed-in user but the function ignores that and processes the *local
    operator's* leads instead. **This mismatch is real and already live in the current code** —
    confirm it and fix it as this phase's first concrete task.
  - `worker/main.py` is exactly what its own docstring says: a health-checkable placeholder.
    `/tasks/run` returns `{"status": "not_implemented"}`. There is no Cloud Tasks queue, no task
    schema, nothing calling this endpoint. This phase is where it becomes real.
  - `skills/llm_client.py`'s retry/backoff (`LLM_MAX_RETRIES`, `_is_transient_error`) is already
    wired into `llm_generate()` (confirmed — this was fixed early in Phase 0, not still open).
    Don't re-do this; just make sure whatever task-retry logic this phase adds (Cloud
    Tasks-level retries) doesn't double up with the LLM-level retry already inside
    `llm_generate()` in a way that multiplies delay unpredictably.
  - `db/models.py` has no `channel` handling yet in the graph — `Lead.channel` is an array column
    (`apply`/`outreach`) but `graph/pipeline.py` has no router node branching on it. That's this
    phase's other big piece of real work per the original plan.

## Locked decisions (carried over)

- Cloud Tasks push-to-authenticated-worker model, per the original architecture — not a raw queue
  library, not Celery. `worker/main.py`'s `/tasks/run` is the eventual push target.
- LangGraph stays; this phase is about correctly scoping and persisting it, not replacing it.
- Postgres checkpointer, not SQLite — this is explicitly called for in the original architecture
  ("LangGraph on Cloud SQL Postgres checkpointer with thread_id scoped by user_id") and is now
  also a correctness requirement, not just a nice-to-have, given multi-user concurrency.
- Two channels (Apply/Outreach) share one graph with a router node, not two separate graphs.

## Task breakdown

### 4.1 — Fix the immediate user-scoping bugs (do this first, before anything else)
- Audit and fix `orchestrator/feed_graph.py`, `orchestrator/check_followups.py`,
  `orchestrator/review_cli.py`: every function that's reachable from an authenticated API route
  (check `api/main.py` for what calls what under `/api/pipeline/feed-graph`,
  `/api/pipeline/check-followups`, and the approve/reject/edit lead routes) must accept a
  `user_id` parameter instead of calling `db.current_user.get_current_user_id()` internally.
  CLI-only entry points (`if __name__ == "__main__"` blocks, `main()` functions meant for direct
  `python -m orchestrator.x` invocation) can keep using the local-operator stand-in — that's a
  legitimate, intentional use, not a bug. The bug is specifically: *HTTP-reachable code path
  silently using the wrong user*.
- Write a regression test proving this: two different `user_id`s' pending-review leads, call the
  now-fixed `feed_pending_leads(user_id=...)`, confirm user B's leads are untouched by user A's
  feed call. This is the same shape as Phase 0's tenant-isolation tests — reuse that pattern.

### 4.2 — Postgres checkpointer for LangGraph
- Add `langgraph-checkpoint-postgres` (check current LangGraph version compatibility) to
  `requirements.txt`, replacing `langgraph-checkpoint-sqlite`'s role (keep the sqlite package
  installed if `tests/test_phase7_review.py` or other tests still construct a SQLite checkpointer
  for speed — check before ripping it out; a fast SQLite checkpointer for tests and a Postgres one
  for real runs can coexist, they're just two different `get_checkpointer_connection` call sites).
- Replace `graph/pipeline.py`'s `get_checkpointer_connection`/`SqliteSaver` with a Postgres-backed
  equivalent, pointed at the same `DATABASE_URL` everything else already uses (`db/session.py`).
  LangGraph's Postgres checkpointer needs its own tables — check whether it wants to manage its
  own schema/migration or needs an Alembic migration added alongside the existing ones.
- Change `thread_id` construction (in `feed_graph.py`, `check_followups.py`, wherever a graph is
  invoked) from bare `lead_id` to `f"{user_id}:{lead_id}"` (or similar) so tenant isolation is
  structural in the checkpoint store, not just "IDs happen not to collide."
- Test: kill/restart the checkpointer connection mid-graph-run (simulate a worker restart),
  confirm `graph.get_state()` on the same thread_id resumes with the correct paused state — this
  is explicitly the plan's own test gate ("job/interrupt state survives worker restart").

### 4.3 — Thread user_id through the graph itself
- Add `user_id: str` to `PipelineState` (currently missing entirely).
- Every node that calls a `db.repository` function or a skill needing `user_id` (tailor_resume,
  find_contact_email, send_via_gmail, draft_outreach — check each) must pull it from
  `state["user_id"]`, not let the skill fall back to `db.current_user`.
- `feed_pending_leads`/`check_and_queue_followups` must set `user_id` in the initial state dict
  they build before calling `graph.invoke(...)`.

### 4.4 — Cloud Tasks + the real worker
- Add a Cloud Tasks client wrapper, e.g. `api/tasks.py`: `enqueue_pipeline_task(user_id, task_type,
  payload)` — pushes a task pointing at `worker/main.py`'s `/tasks/run` endpoint. In local dev
  without real Cloud Tasks configured, fall back to the existing in-process
  `threading.Thread(daemon=True)` pattern already used by `_run_pipeline_bg` — don't force a real
  GCP dependency just to run `docker compose up` locally. Gate this with an env flag (e.g.
  `USE_CLOUD_TASKS=true`), same spirit as `ENABLE_SCHEDULER`.
- Implement `worker/main.py`'s `/tasks/run` for real: verify the request actually came from Cloud
  Tasks (OIDC token audience check, or at minimum an internal shared-secret header for now — this
  endpoint being open would let anyone trigger pipeline work against arbitrary user_ids, a real
  security hole, flag this explicitly if the OIDC verification doesn't make it into this phase),
  deserialize the task payload (`user_id`, `task_type`, whatever else — e.g. `lead_id` for a
  single-lead resume/tailor step, nothing for a batch scrape), dispatch to the right
  `orchestrator.pipeline_runner` function with the right `user_id`.
- Fix `api/main.py`'s `_pipeline_run_state`/`_pipeline_lock` globals: replace with per-user state,
  keyed by `user_id` (a dict of dicts, or — better, since this is exactly what's being persisted
  anyway — read live status from the LangGraph checkpointer / a lightweight `pipeline_runs` table
  instead of an in-memory dict that a second worker replica wouldn't share). Decide: is a new
  `PipelineRun` table (user_id, status, started_at, current_step, summary) worth adding to
  `db/models.py`? Recommend yes — this closes the "why does this die on restart" gap for free,
  consistent with the plan's actual test gate wording.
- `/api/pipeline/run-status` changes from "return the one global dict" to "return this user's
  run status," scoped by the now-real `user_id` dependency already on that route.

### 4.5 — Apply vs Outreach router node
- Add a router node to `graph/pipeline.py` right after wherever `channel` is known (probably right
  after `find_email_node`/`research_company_node`, before tailoring) that branches on
  `state["channel"]` — `Lead.channel` is already an array (a lead can be both), so the router may
  need to fan out to both paths rather than pick exactly one, or the state needs a
  "which channel is this specific graph run processing" field distinct from the lead's full
  `channel` array. Decide this explicitly and document it in the node's docstring — it's a real
  design choice, not a mechanical wire-up.
- This is preparation for Phase 5 (Apply channel) and Phase 6 (Outreach channel) — this phase adds
  the routing scaffold, not the full channel-specific logic (that's explicitly out of scope below).

### 4.6 — Concurrency test
- The plan's actual demo/test gate: "queue runs for two users at once, restart the worker, both
  continue from where they paused." Write this as a real test: two different `user_id`s, each with
  a lead fed into the graph and paused at the review interrupt, confirm both threads' state is
  independently correct (no cross-contamination), then simulate a restart (new checkpointer
  connection object, same underlying Postgres tables) and confirm both resume correctly via
  `approve_lead`/`reject_lead`.

## Tests

- Regression test for 4.1 (the user-scoping bug fix) — two users, `feed_pending_leads` only
  touches the caller's own leads.
- Postgres checkpointer survives a simulated restart (new connection, same thread_id) with state intact.
- `PipelineState`'s `user_id` is correctly used by every node that touches `db.repository` — at
  minimum, extend the existing `tests/test_phase7_review.py`-style mocked graph test to assert the
  mocked skill functions were called with the expected `user_id`, not silently omitted.
- Cloud Tasks enqueue path: with `USE_CLOUD_TASKS=false` (default local dev), confirm pipeline
  runs still work via the in-process thread fallback — don't let this phase break local dev.
- `/tasks/run` rejects a request with no/invalid verification header — same "no soft auth" rule
  Phase 3 established for `api/auth.py`, applied to the worker's own entry point.
- The concurrency test from 4.6.

## Test gate (must be green before calling this phase done)

Two users' pipelines run concurrently and independently; killing and restarting the worker mid-run
resumes both correctly.

## Demo (what "done" looks like)

Queue a pipeline run for two different signed-in users at once. Restart the worker process.  Both
users' runs continue from exactly where they paused, with no leakage between them.

## Explicitly out of scope for this phase (don't scope-creep into these)

- The actual Apply-channel tailored-resume-PDF-plus-cover-note UX and the Outreach-channel
  enrichment/draft/send UX (Phases 5 and 6) — this phase only adds the router *scaffold*, not the
  channel-specific business logic or UI.
- Billing/quota enforcement (Phase 7).
- Terraform/real GCP Cloud Tasks provisioning — per the earlier lean re-plan, keep this
  environment-gated and locally runnable without real GCP infra until there's a concrete reason to
  provision it for real.
- Gmail per-user OAuth connection flow (Phase 6) — don't let 4.4's worker implementation quietly
  grow Gmail-sending logic; it should dispatch to the existing `orchestrator.pipeline_runner`
  functions, which already handle that correctly once a real per-user Gmail account exists later.
