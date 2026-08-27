  # Phase 5: Apply Channel (full)

## Objective

Complete ATS application prep, equal weight to Outreach. From a matched/saved job: tailored resume
PDF + tailored cover note (zero fabrication), a review/edit gate, a one-click deep link to the
real `apply_url`, and a way for the user to mark the lead "applied." No auto-fill anywhere — this
is prepare-and-hand-off, never a bot submitting a form.

## Where we actually stand right now (read this before starting)

- **The scaffold is already built and deliberately dead-ends here.** `graph/pipeline.py`'s
  `route_channel_node` (Phase 4.5) inspects `Lead.channel`/`active_channel`, and for
  `active_channel == "apply"` it returns `status: "apply_channel_not_implemented"` and routes
  straight to `END` (see `route_after_channel`). This is not a bug to work around — it's the exact
  hook this phase replaces. Read `route_channel_node`'s docstring in full before touching it; it
  explains why a lead with both `apply` and `outreach` in its `channel` array currently only gets
  one outreach-shaped graph run, and that the second, apply-shaped run for the same lead is
  "deferred until Phase 5" — i.e. this phase needs to decide how a dual-channel lead actually gets
  *two* runs (two separate thread_ids? one graph run that does both sequentially? see task 5.2).
- **Tailoring already exists and is reusable as-is.** `skills/tailor_resume.py`'s `tailor_resume()`
  (LLM call, zero-fabrication system prompt already written), `resume_to_pdf()` (xhtml2pdf,
  matches a real visual template), and `save_resume()` are all standalone, working functions with
  no per-user/channel assumptions baked in. This phase reuses them; it does not rewrite them.
- **No cover-note generation exists yet.** `Lead.cover_note` is a real column
  (`db/models.py`, already in `db/repository.py`'s `_LEAD_WRITABLE_FIELDS`), but nothing writes to
  it — grepping the whole repo for `cover_note` turns up only the schema/migration/repository
  plumbing, zero generation logic. This is new work, not a rename of something existing.
- **No "mark applied" plumbing exists.** `Lead.applied_at` is a real, unused column. No API route
  sets it. No frontend button calls anything like it.
- **Verified: `Lead.listing_url` is NOT populated from the catalog's `Job.apply_url` anywhere,
  because no code path exists yet that turns a catalog `Job` into a `Lead` at all.** Checked every
  lead-creation call site: `skills/scrape_job_boards/{greenhouse,lever,ashby}.py` (the three
  connectors that DO populate `Job.apply_url`) write only to the shared `companies`/`jobs` catalog
  tables — none of them ever calls `repo.add_lead`/`try_add_lead`. The six scrapers that DO create
  `Lead` rows (`skills/scrape_job_boards/{arbeitnow,jobicy,careers_page,company_list,yc_startups}.py`,
  `skills/scrape_x_leads.py`) each set their own `listing_url` from that source's own listing URL
  (the job-board URL, the Firecrawl-scraped page, the tweet URL) at creation time, and
  `db/repository.py`'s `add_lead` already writes it through correctly (`listing_url=lead.get("listing_url")`)
  — nothing to fix on that side. `Lead.job_id` is a real, writable FK
  (`db/models.py`, `_LEAD_WRITABLE_FIELDS`) meant to link a lead back to its catalog job, but no
  code anywhere ever sets it. Grepping the whole repo (API routes, orchestrator, skills) for any
  "convert this matched catalog job into a lead" endpoint turns up nothing beyond the read-only
  anonymous `/api/anon/resume` (returns matches, writes nothing) and `/api/anon/preview` (one-off
  tailored preview, writes nothing) routes. **Conclusion: this isn't a small copy-step fix, it's
  new work this phase (or whichever phase first lets a signed-in user act on a catalog job) has to
  build.** That new conversion code must explicitly set `lead["listing_url"] = job["apply_url"]`
  and `lead["job_id"] = job["id"]` at creation — there is no existing pipeline behavior to lean on.
- **The frontend review page (`frontend/src/app/(dashboard)/review/page.tsx`) only knows about
  `outreach_draft`.** It fetches `pending_review`/`in_review` leads and renders an
  edit/approve/reject flow keyed on `outreach_draft` text. There is no tailored-resume-preview UI,
  no cover-note UI, no "Apply" deep-link button anywhere in the frontend today. This phase adds a
  distinct review surface for apply-channel leads, it doesn't retrofit the outreach one.
- **Auth is real and already on every relevant route** (confirmed via Phase 4's audit — every
  `/api/leads/*` and `/api/pipeline/*` route already resolves `user_id` via
  `Depends(get_authenticated_user_id)`). New Apply-channel routes this phase adds follow that same
  pattern; there is no separate auth question to solve here.
- **Postgres checkpointer + per-user thread_id scoping already work** (Phase 4.2:
  `graph/pipeline.py`'s `get_postgres_checkpointer()`, `make_thread_id(user_id, lead_id)`). This
  phase's graph changes ride on that infrastructure, not around it.

## Locked decisions (carried over, don't re-litigate)

- No ATS auto-fill, ever. Prepare + a deep link + manual "mark applied," full stop.
- Zero fabrication: the cover note and any resume content must trace back to the candidate's real
  history. This is the same discipline `tailor_resume.py`'s existing system prompt already
  enforces for the resume; the cover-note prompt this phase writes must hold the same line.
- Apply and Outreach are equal-weight channels — this phase is not "the simpler one to skip
  through," it gets the same review-gate rigor as Outreach already has.

## Task breakdown

### 5.1 — Cover note generation
- New module, e.g. `skills/draft_cover_note.py`, mirroring `skills/draft_outreach.py`'s shape
  (system prompt with explicit zero-fabrication rules, one LLM call, word-count discipline). Input:
  the tailored resume (not the base one — same reasoning `draft_outreach.py`'s own docstring
  already gives for using the tailored version: stay consistent with what's actually being
  submitted) + company + role + `jd_text`. Output: cover note text, written to `Lead.cover_note`.
- Explicit rules to bake into the prompt (write these before generating anything, not after
  reviewing bad output): no cover-letter clichés (reuse the exact banned-phrase list
  `draft_outreach.py` already earned from a real review pass — "I came across your opening," "I
  look forward to hearing from you" — cover notes get written by the same kind of candidate to the
  same kind of company, the clichés don't need re-discovering), a genuine company/role-specific
  hook pulled from the real JD text, a hard word cap (recommend ~250-300 words, shorter than a
  full cover letter — most ATS cover-note fields are brief).
- Zero-fabrication stress test (this phase's own explicit test-gate requirement): feed a JD that
  doesn't match the candidate's real background at all, confirm the model declines to fabricate a
  connection rather than inventing one. Write this as a real test with a deliberately mismatched
  fixture, not just an assertion that *some* text came back.

### 5.2 — Graph: replace the apply-channel dead-end
- **Decision locked (do not re-litigate at code time): two separate thread_ids per lead, one per
  channel.** A lead with `channel = ["apply", "outreach"]` needs two independent review gates (a
  human approves the tailored resume+cover note separately from approving the outreach draft —
  they're different artifacts, possibly approved/edited/rejected independently and at different
  times). One graph run forking internally to pause on two interrupts at once would make a single
  checkpoint ambiguous about which channel's decision it's resuming — rejected for that reason.
  - Extend `make_thread_id(user_id, lead_id)` (`graph/pipeline.py`) to
    `make_thread_id(user_id, lead_id, channel=None)`, with `channel` **optional, defaulting to
    None**, not a new required positional arg. When `channel` is `None`, return the exact old
    `f"{user_id}:{lead_id}"` string. When given, return `f"{user_id}:{lead_id}:{channel}"`. This
    is a backward-compatibility requirement, not a nicety: the Postgres checkpointer already has
    real outreach-channel threads paused under the 2-arg format in the current
    `f"{user_id}:{lead_id}"` shape (Phase 4.2). If the signature silently changed shape instead of
    growing an optional param, every one of those in-flight checkpoints would become unaddressable
    (a differently-computed thread_id can't resume a paused thread it doesn't match) — a silent
    data-loss bug, not a refactor. All apply-channel call sites pass `channel="apply"` explicitly;
    outreach call sites are migrated to pass `channel="outreach"` explicitly too (new threads only
    — do not attempt to rewrite existing rows' thread_ids), so `make_thread_id`'s two-arg call form
    is only ever hit by old, already-in-flight outreach threads and by direct unit tests of the
    function's back-compat behavior itself.
  - `orchestrator/feed_graph.py`'s `feed_pending_leads` needs to feed a lead into the graph once
    per channel present in `Lead.channel`, not once per lead — loop over `lead.get("channel") or
    ["outreach"]` (default preserves current single-channel behavior for leads with no explicit
    channel set) and call `make_thread_id(user_id, lead_id, channel=ch)` per iteration, setting
    `active_channel` in the seeded state to `ch` so `route_channel_node` doesn't have to guess.
  - Same per-channel fan-out applies to `orchestrator/check_followups.py`'s equivalent seeding
    logic (it builds the same state shape) and to `orchestrator/review_cli.py`'s
    `approve_lead`/`edit_lead`/`reject_lead` (each needs a `channel` param threaded through to
    `make_thread_id` so an approve call resumes the right one of the lead's two possible threads,
    not always the outreach one).
- Add apply-channel nodes to `graph/pipeline.py`: `tailor_resume_for_apply_node` (reuses
  `skills/tailor_resume.tailor_resume_for_lead` — check whether this existing function's PDF/
  metadata-saving behavior is channel-agnostic already or needs a flag; likely reusable as-is
  since tailoring itself doesn't care which channel triggered it), `draft_cover_note_node` (calls
  5.1's new skill), an apply-specific `review_node` variant or a shared one that branches its
  interrupt payload shape by `active_channel` (decide based on how much the outreach review node's
  existing interrupt-payload logic can be generalized vs. duplicated — read `review_node`'s
  current body first).
- Replace `route_channel_node`'s `active_channel == "apply"` branch: instead of dead-ending to
  `END`, route into the new apply-specific node chain, ending at the apply review interrupt
  instead of `send` (there is no Gmail send step in this channel — the terminal action is a human
  clicking the deep link and then hitting "mark applied," not an automated send).
- New route_after_apply_review (or a generalized route_after_review that branches on
  active_channel): approved → status `ready_to_apply` (per the plan's own state-machine naming:
  `matched → tailoring → ready_to_apply → applied → (followup)`) → END (no send node to route to);
  rejected → END, same as outreach's existing behavior.

### 5.3 — API: apply-channel routes
- Extend `orchestrator/review_cli.py`'s or `api/main.py`'s existing approve/reject/edit-lead
  routes (`/api/leads/{lead_id}/approve` etc.) to be channel-aware, OR add distinct apply-specific
  routes if the existing ones' payload shape (built entirely around `outreach_draft`) can't
  cleanly branch — check the current implementation before deciding; don't force one shape onto
  both channels if it makes the code harder to read than two clearly-named route sets.
- New route: `POST /api/leads/{lead_id}/mark-applied` — sets `applied_at` to now, moves `status`
  to `applied`. Auth via the existing `Depends(get_authenticated_user_id)` pattern, scoped so a
  user can only mark their own leads (reuse `db.repository`'s existing tenant-isolation guarantees
  — this is a plain `repo.update_lead(user_id, lead_id, {...})` call, nothing new needed at the
  repository layer).
- Confirm/fix `Lead.listing_url` actually gets populated from the catalog's `Job.apply_url` when a
  lead is created from a catalog job (see the note above under "where we stand") — this is the
  literal deep link the whole channel exists to hand the user, it has to be real and correct, not
  a TODO discovered after the UI is built around it.
- Optional apply-follow-up reminder (explicitly called "optional" in the original plan — don't
  over-build this): a lightweight nudge if a lead sits at `ready_to_apply` for N days without
  moving to `applied`. Given Phase 4's `PipelineRun`-table precedent and the existing
  `orchestrator/check_followups.py` cron pattern, the natural home for this is a small addition to
  that same scheduled job, not a new subsystem.

### 5.4 — Frontend: apply-channel review surface
- New review UI (either a distinct tab/filter on the existing `review/page.tsx`, or a new page —
  decide based on how differently-shaped the apply artifact (resume PDF preview + cover note
  text) is from the outreach artifact (just draft text) once you're looking at the real component)
  showing: the tailored resume (PDF preview or a link to view/download it — `tailor_resume.py`
  already saves a `.pdf`, check `save_resume()`'s return shape for what the frontend needs to
  fetch it), the cover note (editable text, same edit/approve/reject pattern the outreach review
  page already has working), and — after approval — a prominent "Apply" button that's a real
  `<a href={listing_url} target="_blank">` deep link, plus a "Mark as Applied" button calling
  5.3's new route.
- Update `frontend/src/lib/api.ts` with the new endpoint(s) from 5.3, following the exact pattern
  already used for the outreach `approve`/`reject`/`edit` calls.
- Lead list/dashboard views (`frontend/src/app/(dashboard)/leads/page.tsx`,
  `frontend/src/app/(dashboard)/dashboard/page.tsx`) should visibly distinguish apply-channel
  leads from outreach-channel ones (a badge showing `channel`, at minimum) — check whether
  `LeadResponse` (in `api/main.py`) already exposes `channel` to the frontend; if not, that's a
  small, necessary addition here.

### 5.5 — ATS keyword coverage + status-transition correctness
- `skills/tailor_resume.py` already has `keyword_coverage()` (confirmed working, used by the
  anonymous-preview endpoint in Phase 2) — reuse it here to report a coverage score alongside the
  apply-channel tailored resume, matching the plan's own test-gate wording ("ATS keyword coverage
  sane"). Decide a sanity threshold (e.g. flag/warn under some %, don't hard-block on it — the
  original plan's language is "sane," not "enforced").
- Status-transition test: `matched → tailoring → ready_to_apply → applied` — write a test that
  drives a lead through this exact sequence via the real API routes (not just repository calls)
  and asserts each transition lands on the correct `status`/`applied_at` state, including the
  rejected branch (`ready_to_apply`-eligible → rejected → stays terminal, never silently reachable
  again without a fresh graph run).

## Tests

- Cover-note zero-fabrication stress test (5.1) — mismatched JD, model declines to fabricate.
- Cover-note word-cap and banned-cliché checks, mirroring whatever tests
  `skills/draft_outreach.py` already has for its own equivalent rules (check `tests/` for the
  existing outreach draft-quality tests and match that shape).
- Graph test: an apply-channel lead reaches the apply review interrupt (not `END` via the old
  dead-end, not the outreach `send` node) — this is the direct regression guard that 5.2's
  replacement of `route_channel_node`'s dead-end actually took effect.
- Dual-channel lead test: a lead with `channel = ["apply", "outreach"]` produces two independent,
  correctly-scoped graph threads (per 5.2's thread_id-per-channel decision) — approving one must
  not affect the other's state.
- `mark-applied` route: sets `applied_at`/`status` correctly, is user-scoped (a different user
  calling it on someone else's lead gets the standard tenant-isolation rejection, same shape as
  every other lead-scoped route already tested in Phase 0/3).
- PDF renders and matches the existing template — this is largely already covered by
  `tailor_resume.py`'s own tests if they exist; check before assuming this needs new coverage vs.
  just confirming existing coverage extends naturally to the apply-channel call path.
- End-to-end: matched job → tailored resume + cover note generated → review/edit UI → approve →
  real deep link → mark applied — the plan's own explicit test gate, written as one real
  integration test through the actual API routes (TestClient, mocked LLM calls, real Postgres —
  same pattern Phase 2's `tests/test_anon_endpoints.py` already established).

## Test gate (must be green before calling this phase done)

Apply golden-path e2e green: matched job → tailored resume + cover note → review/edit → deep link
→ marked applied.

## Demo (what "done" looks like)

Pick a real Greenhouse job from the Phase 1 catalog. Get a polished tailored resume + cover note.
Click through to the real, live apply page. Mark it applied.

## Explicitly out of scope for this phase (don't scope-creep into these)

- The Outreach channel's own remaining work (already mostly built in earlier phases) — this phase
  touches the graph's shared nodes only where Apply/Outreach genuinely need to diverge (review
  interrupt payload shape, routing), not anywhere else.
- Billing/quota enforcement on apply-channel usage (Phase 7).
- Any real ATS-side automation, autofill, or credential storage for the target company's
  application form — permanently out of scope per the project's own locked constraints, not just
  this phase's.
- Per-user Gmail OAuth (Phase 6) — the Apply channel never sends email; don't let anything from
  Outreach's Gmail plumbing leak into this phase's routes by accident.
