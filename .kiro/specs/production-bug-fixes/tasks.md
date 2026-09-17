# Implementation Plan

- [ ] 1. Write bug condition exploration tests (surface counterexamples on UNFIXED code)
  - **Property 1: Bug Condition** - Four Production Bugs Reproduced
  - **CRITICAL**: These tests MUST FAIL (or assert the current buggy behavior) on unfixed code - failure/buggy-assertion confirms each bug exists
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior - they will validate the fix when they pass after implementation
  - **GOAL**: Surface concrete counterexamples that demonstrate each of the four bugs
  - **Scoped PBT Approach**: These are deterministic bugs; scope each property to concrete failing case(s) for reproducibility
  - Create `tests/test_production_bug_fixes.py` (pytest, mirroring existing `tests/` conventions)
  - **Bug 1 (filename)**: Call `save_resume(resume, "Acme Corp", user_id=<uuid>)` and assert the returned `resume_version` key contains `slugify(user_id)`; assert `get_lead_resume_pdf` sets a `Content-Disposition` filename containing the UUID slug. From Bug Condition: `servedFilename(input) CONTAINS slugify(input.user_id)`
  - **Bug 2 (page count)**: Render a deliberately long tailored resume via `resume_to_pdf_bytes` and assert `pageCount(pdf) > 1`. From Bug Condition: `pageCount(renderPdf(input)) > 1`
  - **Bug 3 (hyperlinks)**: Render a resume with `contact.linkedin`/`github`/`portfolio` and a `projects[].link`; inspect the PDF and assert the live URLs are NOT surfaced as clickable link annotations. From Bug Condition: `hasLiveLinks(input) AND EXISTS url: NOT isClickableHyperlink(renderPdf(input), url)`
  - **Bug 4 (pre-flight)**: With a user whose `remaining < requested_leads`, POST `/api/pipeline/run` with `yc_max_leads` above the balance and assert the run starts anyway; repeat for `/api/pipeline/run-for-leads` with more `lead_ids` than credits. From Bug Condition: `pipelineStart AND NOT creditSufficiencyChecked(input)`
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests demonstrate the bugs (ID-bearing filename, >1 page, no clickable annotations, run accepted despite insufficient credits)
  - Document the counterexamples found (served filename with UUID slug; 2-page PDF; missing link annotation; accepted over-budget run)
  - Mark task complete when tests are written, run, and the buggy behavior is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Buggy Inputs Unchanged
  - **IMPORTANT**: Follow observation-first methodology - observe behavior on UNFIXED code, then encode it
  - Add preservation tests to `tests/test_production_bug_fixes.py`
  - **3.2 storage key unchanged**: Observe `save_resume()` returns a specific `resume_version` for given inputs; write a test asserting that key is byte-identical, and that an existing `{resume_version}.pdf` still resolves via `get_lead_resume_pdf`
  - **3.1 tailored content unchanged**: Observe the tailored JSON/MD content for a fixed base resume + JD; assert it is unchanged (only the served filename may differ)
  - **3.3 one-page resume unchanged**: Observe a short resume renders as exactly 1 page today; property-based test over short resumes asserting page count and content are preserved
  - **3.4 link-free resume unchanged**: Observe a resume with no URLs renders identically today; assert unchanged rendering
  - **3.6 sufficient-credit run unchanged**: Observe a user with `remaining >= requested_leads` starts the run (same response shape, run created, thread spawned); assert unchanged
  - **3.5 zero-credit for incomplete lead**: Observe a lead that never reaches `sent`/`draft_created` contributes 0 to `count_outreach_used`; assert unchanged
  - **3.7 / 3.8 quota shape + isolation**: Property-based test asserting `get_outreach_quota` always returns `{plan, used, limit, remaining, reset}` and that one user's completed-outreach leads never change another user's `used`/`remaining`
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms the baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [ ] 3. Fix Bug 1 - Clean, readable served resume filename

  - [ ] 3.1 Derive a clean filename at serve time in `get_lead_resume_pdf`
    - In `api/main.py` `get_lead_resume_pdf` (`GET /api/leads/{lead_id}/resume-pdf`), build a human-readable name from the lead owner's name and the lead's company, e.g. `{Name}_{Company}`
    - Sanitize to filesystem-safe chars, mirroring the existing `download_resume_pdf` sanitizer (keep alphanumerics/space/`-`/`_`, collapse spaces to `_`), falling back to `resume` when empty
    - Resolve the display name from the tailored-resume JSON (`resume.get("name")`) or the user record; keep the company from the lead
    - Change only `Content-Disposition` to `filename="{clean_name}.pdf"`; keep fetching bytes by the unchanged `resume_version` key (`store.get_bytes(f"{resume_version}.pdf")`)
    - Leave `save_resume()` / `resume_version` untouched
    - _Bug_Condition: isBugCondition(input) where servedFilename(input) CONTAINS slugify(input.user_id)_
    - _Expected_Behavior: served filename matches `{Name}_{Company}.pdf` and does NOT contain slugify(user_id); internal key unchanged_
    - _Preservation: 3.1 content unchanged, 3.2 storage key/artifacts unchanged_
    - _Requirements: 2.1, 2.2, 3.1, 3.2_

  - [ ] 3.2 Verify the Bug 1 exploration test now passes
    - **Property 1: Expected Behavior** - Clean, readable served filename
    - **IMPORTANT**: Re-run the SAME Bug 1 assertions from task 1 - do NOT write a new test
    - Assert the `Content-Disposition` filename matches `{Name}_{Company}.pdf` and does NOT contain the UUID slug; assert `save_resume` return value (store key) is unchanged
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2_

- [ ] 4. Fix Bug 2 - Single-page PDF constraint

  - [ ] 4.1 Add a single-page constraint to the render path
    - In `skills/tailor_resume.py`, constrain `resume_to_pdf_bytes` / `resume_to_pdf` (shared render path via `resume_to_html` / `pisa.CreatePDF`) so overflow content is contained to a single letter page (via `@page`/body sizing and/or xhtml2pdf render options)
    - Ensure the constraint is a no-op for content that already fits one page
    - _Bug_Condition: isBugCondition(input) where pageCount(renderPdf(input)) > 1_
    - _Expected_Behavior: pageCount(renderPdf_fixed(input)) = 1_
    - _Preservation: 3.3 one-page resume layout/content intact_
    - _Requirements: 2.3, 3.3_

  - [ ] 4.2 Verify the Bug 2 exploration test now passes
    - **Property 1: Expected Behavior** - Single-page PDF
    - **IMPORTANT**: Re-run the SAME Bug 2 assertion from task 1 - do NOT write a new test
    - Assert the long tailored resume now renders as exactly 1 page
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.3_

- [ ] 5. Fix Bug 3 - Clickable hyperlinks

  - [ ] 5.1 Ensure link annotations render for existing anchors
    - In `skills/tailor_resume.py`, make the `pisa.CreatePDF` render path emit live link annotations for the existing `<a href>` anchors (contact links + project links)
    - Leave the anchor markup and `_normalize_url` scheme normalization in `resume_to_html` as-is
    - Ensure a resume with no anchors renders identically
    - _Bug_Condition: isBugCondition(input) where hasLiveLinks(input) AND some url is not a clickable hyperlink_
    - _Expected_Behavior: FOR EACH url IN liveLinks(input): isClickableHyperlink(renderPdf_fixed(input), url)_
    - _Preservation: 3.4 link-free resume rendered unchanged_
    - _Requirements: 2.4, 3.4_

  - [ ] 5.2 Verify the Bug 3 exploration test now passes
    - **Property 1: Expected Behavior** - Clickable hyperlinks
    - **IMPORTANT**: Re-run the SAME Bug 3 assertion from task 1 - do NOT write a new test
    - Assert every present contact/project URL is now a clickable link annotation in the PDF; none for a link-free resume
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.4_

- [ ] 6. Fix Bug 4 - Pre-flight credit sufficiency check + real-time balance

  - [ ] 6.1 Add a pre-flight sufficiency gate to the pipeline-start routes
    - In `api/main.py`, in `run_pipeline` (`POST /api/pipeline/run`) and `run_for_leads` (`POST /api/pipeline/run-for-leads`), before `repo.create_pipeline_run(...)`, call `repo.get_outreach_quota(user_id)` to obtain `remaining`
    - Compute `requested_leads`: for `/run` use the clamped `yc_max` (`min(max(1, yc_max_leads or 5), 15)`); for `/run-for-leads` use `len(body.lead_ids)`
    - If `remaining < requested_leads`, raise an HTTP error with a clear insufficient-credits detail (e.g. 402/403 with `{needed, remaining}`) and do NOT create a run or spawn a thread
    - If `remaining >= requested_leads`, proceed exactly as today
    - Do not alter `count_outreach_used()` / `get_outreach_quota()` return shape or per-tenant scoping; the derived balance already reflects completed-outreach leads (`sent`/`draft_created`) in real time - no separate ledger is introduced
    - _Bug_Condition: isBugCondition(input) where pipelineStart AND NOT creditSufficiencyChecked(input)_
    - _Expected_Behavior: remaining >= requested_leads IMPLIES runStarted; remaining < requested_leads IMPLIES runRejected with clear insufficient-credits response_
    - _Preservation: 3.5 incomplete lead=0 credits, 3.6 sufficient-credit run unchanged, 3.7 quota shape, 3.8 per-tenant isolation_
    - _Requirements: 2.5, 2.6, 3.5, 3.6, 3.7, 3.8_

  - [ ] 6.2 Surface the insufficient-credits rejection in the Run Pipeline dialog
    - In `frontend/src/components/pipeline/run-pipeline-dialog.tsx` `handleRun`, when `api.pipeline.run(...)` returns the insufficient-credits error, show a clear toast via the existing `toast.error` path so the user understands why the run did not start
    - Optionally compare `ycMax` against the known remaining balance to disable/annotate the Run button before submit; the backend gate remains the authority
    - _Bug_Condition: isBugCondition(input) where a run is rejected for insufficient credits_
    - _Expected_Behavior: user sees a clear insufficient-credits message; no run is created_
    - _Preservation: 3.6 sufficient-credit run still starts exactly as today_
    - _Requirements: 2.6, 3.6_

  - [ ] 6.3 Verify the Bug 4 exploration test now passes
    - **Property 1: Expected Behavior** - Pre-flight sufficiency + real-time balance
    - **IMPORTANT**: Re-run the SAME Bug 4 assertions from task 1 - do NOT write new tests
    - Assert `run_pipeline` / `run_for_leads` REJECT when `remaining < requested_leads` (no run created) and PROCEED when `remaining >= requested_leads`
    - Assert a completed-outreach lead (`sent`/`draft_created`) is reflected in the backend-derived balance in real time
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.5, 2.6_

- [ ] 7. Verify preservation tests still pass (all bugs)
  - **Property 2: Preservation** - Non-Buggy Inputs Unchanged
  - **IMPORTANT**: Re-run the SAME preservation tests from task 2 - do NOT write new tests
  - Run the full preservation suite from step 2 against the fixed code
  - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions across storage key, tailored content, one-page layout, link-free rendering, sufficient-credit runs, incomplete-lead credits, quota shape, and per-tenant isolation)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [ ] 8. Checkpoint - Ensure all tests pass
  - Run the full test suite (`pytest tests/` plus any frontend checks for the dialog change)
  - Confirm the four exploration tests now pass and all preservation tests still pass
  - Ensure all tests pass, ask the user if questions arise
