# Phase 3: Accounts & Multi-Tenancy

## Objective

Turn the anonymous session (Phase 2's parse → infer → match → preview flow) into a persistent,
secure, per-user account. This is the phase where "multi-tenant" stops being a schema property
(`user_id` columns, tenant-isolation tests) and becomes something actually reachable by more than
one real signed-in person.

## Where we actually stand right now (read this before starting)

- `db/models.py`'s `User` table already has `firebase_uid` (unique, indexed) — the schema was
  built for this in Phase 0, unused until now.
- `db/repository.py` already has `get_or_create_user`, `get_user_by_firebase_uid`,
  `create_user` — all user_id-scoped functions are tenant-isolation-tested (Phase 0's test suite).
- `db/current_user.py` is the single-user stand-in every skill/orchestrator/API call currently
  goes through. This phase's job is to make it possible to bypass this for real per-request auth
  — **not to delete it**. Single-operator CLI usage (scrapers, orchestrator scripts) should keep
  working against the one local user; only *API requests* need real per-request identity.
- No `firebase-admin` SDK is installed. No frontend Firebase SDK. No auth middleware anywhere in
  `api/main.py`. CORS is locked to `http://localhost:3000` only (`api/main.py` line ~83).
- The frontend (`frontend/src/app`) has **zero auth code** — no login page, no session context, no
  token attached to any `fetch` call in `frontend/src/lib/api.ts`. This was confirmed by an audit
  earlier in this project; nothing has changed since.
- Phase 2's anonymous flow was deliberately built stateless-server-side *specifically so this
  phase would be easy*: the frontend already holds `parsed_resume` + `inferred_criteria` +
  `matched_jobs` in memory after upload. Converting that to a saved account is a plain POST with
  the already-held data, not a session migration.

## Locked decisions (carried over, don't re-litigate)

- Firebase Auth, Google Sign-In only for v1 (no email/password, no other providers, per the
  original plan — revisit later if there's demand).
- No new ATS/session-store dependency (Redis, etc.) — Postgres is still the only store.
- Every protected endpoint requires a valid token; there is no "soft" auth mode.

## Task breakdown

### 3.1 — Firebase project setup (do this first, it's the one manual step)
- Create (or reuse) a Firebase project in the Firebase console. Enable Google as a sign-in
  provider under Authentication.
- Generate a service account key for the backend (Firebase Admin SDK needs this to verify ID
  tokens). Store it the same way `config/gmail_credentials.json` is handled today — gitignored,
  referenced via `config/.env` (e.g. `FIREBASE_SERVICE_ACCOUNT_PATH` or the JSON inlined as an
  env var for easier Cloud Run secret injection later).
- Get the frontend's Firebase config (apiKey, authDomain, projectId, etc.) — this is public,
  safe to commit, goes in a `frontend/.env.local` or directly in a config file.
- **Do this step personally, in the console, before asking for code** — creating the actual
  Firebase project isn't something to automate blindly.

### 3.2 — Backend: token verification middleware
- Add `firebase-admin` to `requirements.txt`.
- New module, e.g. `api/auth.py`: a FastAPI dependency (`get_current_firebase_user` or similar)
  that reads the `Authorization: Bearer <id_token>` header, verifies it via
  `firebase_admin.auth.verify_id_token`, and returns the decoded token (has `uid`, `email`).
- On every protected route, swap `get_current_user_id()` (the Phase 0 stand-in) for a call that
  resolves `repo.get_or_create_user(firebase_uid=decoded["uid"], email=decoded["email"])` — same
  repository function Phase 0 already uses, just fed a real uid instead of the fixed local one.
- Missing/invalid/expired token → `401`, not `403` and not a silent fallback to the local user.
  This is the one place "no soft auth" has to be airtight.
- Decide the protected/unprotected split explicitly and write it down before touching routes:
  - **Stays open** (per the locked "no auth gate" decision from Phase 2): `/api/anon/resume`,
    `/api/anon/preview`, `/api/health`, `/health`, `/ready`.
  - **Becomes protected**: everything under `/api/leads/*`, `/api/pipeline/*`,
    `/api/settings/*`, `/api/stats`, `/api/builds*`, `/api/scheduler/*` — i.e. every route that
    currently silently uses `db/current_user.py`'s single fixed user.
- `orchestrator/*.py` CLI scripts and the scheduler (`orchestrator/scheduler.py`) keep using
  `db/current_user.py` as-is — they're not HTTP requests, there's no token to check. Don't touch
  these.

### 3.3 — Backend: lock down CORS + clean error responses
- CORS `allow_origins` needs the real deployed frontend origin added once one exists — for now,
  keep localhost for dev but stop assuming this list never grows. Make it env-driven
  (`ALLOWED_ORIGINS` in `.env`, comma-split) rather than hardcoded, so prod doesn't need a code
  change to add its own origin.
- Audit `api/main.py` for any place a raw exception/traceback could leak to a client response
  (the plan's "clean error responses (no raw exceptions)" requirement). Grep for bare `except
  Exception as e: raise HTTPException(..., detail=str(e))` — some of these already exist (e.g.
  the demo-build routes) and are fine for now, but anything that could leak a DB connection
  string or file path needs a generic message instead.

### 3.4 — Backend: anon → account conversion endpoint
- New route, e.g. `POST /api/account/convert-anon-session` (protected — requires a valid token).
  Body: `{parsed_resume: dict, inferred_criteria: dict}` — exactly what `/api/anon/resume`
  returned to the frontend.
- On call: persist the resume into the (currently-unused) `resumes` table, persist criteria into
  the (currently-unused) `search_criteria` table, both scoped to the now-real `user_id` from the
  verified token. Mark `search_criteria.inferred_from_resume = True` (the field already exists in
  the inferred-criteria shape from Phase 2 — it's designed to flow straight through).
- This is the one place `db/models.py`'s `Resume` and `SearchCriteria` tables get their first real
  writer. Check `db/repository.py` for existing CRUD on these — if it doesn't exist yet, this task
  includes adding `repo.create_resume(user_id, ...)` and `repo.create_search_criteria(user_id,
  ...)` following the exact same pattern as every other repo function (user_id-scoped, tested for
  tenant isolation).
- Idempotency matters here: what happens if a user calls this twice (e.g. double-clicks "sign
  up")? Decide (probably: create a new resume version each time, which matches
  `resumes.is_primary` already being a field — first one becomes primary, more info flows into
  the plan's "resume versions" concept for later) and write a test for it.

### 3.5 — Frontend: Firebase SDK + Google Sign-In
- Add `firebase` (the JS SDK) to `frontend/package.json`.
- New `frontend/src/lib/firebase.ts`: initializes the Firebase app client-side with the public
  config from 3.1.
- New auth context (`frontend/src/lib/auth-context.tsx` or similar, mirroring the existing
  `pipeline-context.tsx` pattern already in the codebase): wraps `onAuthStateChanged`, exposes
  `user`, `signInWithGoogle()`, `signOut()`, and a `getIdToken()` helper.
- Update `frontend/src/lib/api.ts`'s `request()` function to attach `Authorization: Bearer
  <token>` to every call when a user is signed in. This is the one central chokepoint — every
  existing dashboard call (`leads`, `stats`, `settings`, etc.) starts working correctly the moment
  this one function is fixed, no per-page changes needed.
- Add a sign-in entry point. Simplest version: a "Sign in with Google" button on the existing
  marketing landing page (`frontend/src/app/page.tsx`) and/or right after the anonymous
  upload/feed flow if that's been wired up by the time this phase starts.
- Add a route guard for the `(dashboard)` route group (`frontend/src/app/(dashboard)/layout.tsx`)
  — redirect to sign-in if there's no authenticated user, instead of the current "renders
  unconditionally" behavior.

### 3.6 — Frontend: anon → account conversion UX
- Right after a successful Google sign-in, if the frontend still has an in-memory
  `parsed_resume`/`inferred_criteria` from a prior anonymous upload (Phase 2), call
  `POST /api/account/convert-anon-session` with it, then route to the dashboard.
- If there's no anonymous data in memory (a visitor signs in without ever uploading a resume
  first), skip straight to the dashboard — the profile page just starts empty, matches Phase 4's
  "profile page (resume versions, editable criteria)" scope, not this phase's problem to solve
  further.

### 3.7 — Profile page (resume versions, editable criteria)
- New dashboard page, e.g. `frontend/src/app/(dashboard)/profile/page.tsx`: shows the signed-in
  user's saved resume(s) and search criteria, editable.
- Backend: `GET/PUT` routes for `search_criteria` and resume listing, scoped to the authenticated
  user (reuses the auth middleware from 3.2). This overlaps with the existing
  `/api/settings/search-criteria` routes, which currently read/write `config/search_criteria.json`
  (a single global file) — decide whether to migrate those routes to read/write the
  `search_criteria` table per-user instead, or keep them as a separate "global pipeline defaults"
  concept distinct from per-user criteria. Recommend: migrate them, since the whole point of this
  phase is that config/*.json single-user files stop being the source of truth.

## Tests (per the project's "phase isn't done until its test gate is green" rule)

- **Auth middleware**: valid token → 200 with correct user context; missing token → 401; expired
  token → 401; malformed/garbage token → 401 (not 500). Test against `/api/anon/*` too, confirming
  they still work with *no* token (regression guard — don't accidentally lock down the one thing
  that's supposed to stay open).
- **Tenant isolation through the API, not just the repository layer**: sign in as two different
  Firebase UIDs (mocked token verification in tests — don't hit real Firebase in CI), confirm
  user A's `/api/leads` never returns user B's leads via the real HTTP layer. Phase 0 already
  proved this at the repository level; this test proves the middleware wiring doesn't leak it.
- **Anon → account conversion**: convert with a real Phase-2-shaped payload, confirm a `Resume`
  row and a `SearchCriteria` row exist afterward, correctly scoped to the new user_id. Confirm
  calling it twice doesn't corrupt state (decide + test the idempotency behavior from 3.4).
- **Profile CRUD**: get/update search criteria and resume listing, scoped correctly, rejecting
  another user's data the same way leads already do.
- Mock Firebase token verification in tests (don't make real Firebase Admin SDK calls in CI) —
  patch `firebase_admin.auth.verify_id_token` the same way LLM calls are already mocked
  throughout the existing test suite.

## Test gate (must be green before calling this phase done)

Every protected endpoint enforces auth + user scoping; signing in right after the anonymous flow
keeps the feed and resume (i.e. 3.6's conversion actually works end to end, not just unit-tested).

## Demo (what "done" looks like)

Sign in with Google right after trying the anonymous hook. The parsed resume, inferred criteria,
and matched jobs from before sign-in are all still there, now saved to the account, and editable
from a real profile page.

## Explicitly out of scope for this phase (don't scope-creep into these)

- Billing/plan enforcement (Phase 7).
- Gmail OAuth per-user connection (Phase 6) — that's a *different* OAuth flow (Gmail API scopes),
  not Firebase Auth. Don't conflate them even though both involve Google.
- Any actual pipeline processing changes (Apply/Outreach channels) — this phase is purely
  "can a real person log in and own their data," not "can they run the pipeline yet."
- Multi-provider sign-in (email/password, GitHub, etc.) — Google only, per the locked decision.
