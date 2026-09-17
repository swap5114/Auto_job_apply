# Production Bug Fixes Bugfix Design

## Overview

Four independent production bugs are addressed here. Three concern the tailored-resume artifact produced by `skills/tailor_resume.py` and served by `api/main.py`; the fourth concerns credit accounting across the pipeline-start routes (`api/main.py`), the credit ledger (`db/repository.py`), and the "Run Pipeline" dialog (`frontend/src/components/pipeline/run-pipeline-dialog.tsx`).

The unifying strategy is targeted and preservation-first:

1. **Malformed filename (Bug 1)** — The internal storage key (`resume_version`) that `save_resume()` returns must stay byte-for-byte unchanged so every existing stored resume keeps resolving (Regression 3.2). The fix is to decouple the *served download filename* from the internal key: compute a clean, human-readable `{Name}_{Company}.pdf` at the point the PDF is served (`GET /api/leads/{lead_id}/resume-pdf`) rather than reusing the ID-bearing key as the `Content-Disposition` filename.
2. **Two-page overflow (Bug 2)** — `resume_to_pdf_bytes()` / `resume_to_pdf()` render through `xhtml2pdf` (`pisa.CreatePDF`) with `@page` CSS but no single-page constraint. Introduce a single-page constraint in the rendering path that keeps a resume already fitting one page unchanged (Regression 3.3).
3. **Non-clickable links (Bug 3)** — `resume_to_html()` already emits well-formed `<a href>` markup with normalized absolute URLs (`_normalize_url`). The gap is in how `xhtml2pdf` surfaces those anchors as live PDF link annotations. The fix ensures anchors render as clickable hyperlinks without altering plain-text-only resumes (Regression 3.4).
4. **Credit deduction + pre-flight check (Bug 4)** — Credits are only *derived* by `count_outreach_used()` counting `sent`/`draft_created` leads; there is no pre-flight sufficiency check on `POST /api/pipeline/run` or `POST /api/pipeline/run-for-leads`, and the dialog sends `yc_max_leads` with no check. The fix adds a pre-flight balance check on the pipeline-start routes and surfaces insufficient-credit rejection to the dialog, while preserving the existing derived-usage semantics and the `GET /api/outreach/quota` response shape (Regressions 3.6, 3.7, 3.8).

## Glossary

- **Bug_Condition (C)**: The condition that triggers a given bug (per-bug formal specification below).
- **Property (P)**: The desired behavior once the bug condition holds.
- **Preservation**: Existing behavior that must remain unchanged by the fix (bugfix.md clauses 3.1–3.8).
- **`resume_version`**: The stable, user-namespaced base filename returned by `save_resume()` in `skills/tailor_resume.py` and persisted on the lead. Used as the object-store key (`{resume_version}.pdf/.md/.json`). This is an INTERNAL key, not a user-facing filename.
- **`save_resume(resume, company, user_id, template)`**: Function in `skills/tailor_resume.py` that renders JSON/MD/PDF artifacts, stores them under `{base_filename}.*`, and returns `base_filename`. Currently builds `f"{slugify(user_id)}_{name_slug}_resume_{company_slug}"` when `user_id` is present.
- **`resume_to_html(resume, template)`**: Function in `skills/tailor_resume.py` that builds the resume HTML, already emitting `<a href="...">` anchors via `_normalize_url`.
- **`resume_to_pdf_bytes(resume, template)` / `resume_to_pdf(resume, output_path, template)`**: Functions in `skills/tailor_resume.py` that render the HTML through `pisa.CreatePDF` (xhtml2pdf).
- **`get_lead_resume_pdf(lead_id, user_id)`**: Route in `api/main.py` (`GET /api/leads/{lead_id}/resume-pdf`) that streams `{resume_version}.pdf` from the artifact store, currently setting `Content-Disposition: inline; filename="{resume_version}.pdf"`.
- **`count_outreach_used(user_id, since)`**: Function in `db/repository.py` that returns lifetime credits consumed by counting leads with status in `_OUTREACH_SENT_STATUSES` (`sent`, `draft_created`) and a non-null `sent_at`.
- **`get_outreach_quota(user_id)`**: Function in `db/repository.py` returning `{plan, used, limit, remaining, reset}` — the backend source of truth for the credit balance.
- **`PLAN_CREDIT_LIMIT`**: Per-plan lifetime credit allowance in `db/repository.py` (`free: 25`, `pro: 250`).
- **Pipeline-start routes**: `POST /api/pipeline/run` (`run_pipeline`) and `POST /api/pipeline/run-for-leads` (`run_for_leads`) in `api/main.py`.
- **`remaining`**: `max(0, limit - used)` from `get_outreach_quota` — the caller's remaining credit balance.
- **`requested_leads`**: The number of leads a pipeline-start request will attempt (`min(max(1, yc_max_leads), 15)` for `/run`; `len(lead_ids)` for `/run-for-leads`).

## Bug Details

### Bug Condition — Bug 1: Malformed filename

The bug manifests when a tailored resume is served for download/preview. `save_resume()` builds `resume_version = f"{slugify(user_id)}_{name_slug}_resume_{company_slug}"`, embedding the user UUID, and `get_lead_resume_pdf()` reuses that key verbatim as the `Content-Disposition` filename, so the user sees a long, ID-bearing filename.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ResumeDownloadRequest   // (user_id, name, company, resume_version)
  OUTPUT: boolean

  RETURN servedFilename(input) CONTAINS slugify(input.user_id)
END FUNCTION
```

### Bug Condition — Bug 2: Resume exceeds one page

The bug manifests when tailored content is long enough that `pisa.CreatePDF` flows it onto a second page, because the render path applies `@page` sizing/margins but no single-page constraint.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type Resume
  OUTPUT: boolean

  RETURN pageCount(renderPdf(input)) > 1
END FUNCTION
```

### Bug Condition — Bug 3: Live links not clickable

The bug manifests when a resume carries at least one live URL (contact links or project links). `resume_to_html()` emits `<a href>` markup, but the rendered PDF does not surface those anchors as clickable link annotations.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type Resume
  OUTPUT: boolean

  RETURN hasLiveLinks(input)          // contact.linkedin/github/portfolio OR any projects[].link
         AND EXISTS url IN liveLinks(input):
               NOT isClickableHyperlink(renderPdf(input), url)
END FUNCTION
```

### Bug Condition — Bug 4: Credit deduction and pre-flight check

The bug manifests when a pipeline-start request is accepted without any check that the caller has enough remaining credits for the requested number of leads (`sufficiency` gap). The related derivation concern is that credits are only ever *derived* after the fact by counting completed-outreach leads, with no explicit pre-flight gate.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type PipelineStart   // (user_id, requested_leads)
  OUTPUT: boolean

  RETURN input is pipelineStart
         AND NOT creditSufficiencyChecked(input)   // run accepted without comparing
                                                    // remaining >= requested_leads
END FUNCTION
```

### Examples

- **Bug 1**: For user `3f9c1a2e-...` named "Jane Doe" applying to "Acme Corp", the served download is `3f9c1a2e_..._jane_doe_resume_acme_corp.pdf` (ID-bearing). Expected: `Jane_Doe_Acme_Corp.pdf`.
- **Bug 2**: A tailored resume with an extra experience bullet and a longer summary renders as a 2-page PDF. Expected: strictly 1 page.
- **Bug 3**: A resume with `contact.linkedin` and a `projects[].link` renders those as blue text that cannot be clicked in the PDF. Expected: clicking the anchor opens the URL.
- **Bug 4 (edge case)**: A `free`-plan user with `remaining = 2` submits `yc_max_leads = 15`. Today the run starts anyway. Expected: rejected with a clear insufficient-credits response. A user with `remaining >= requested_leads` still starts normally.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- **3.1** Tailored resume *content* (bullets, skills, ordering, ATS keyword coverage) stays exactly as produced today; only the served filename changes.
- **3.2** The JSON/MD/PDF artifacts and the `TailoredResume` DB row continue to be persisted; the internal `resume_version` storage key is unchanged, so existing stored resumes keep resolving for download/preview.
- **3.3** A resume that already fits one page keeps its existing layout and content intact after the single-page constraint is added.
- **3.4** A resume with no live links continues to render its plain text content unchanged.
- **3.5** A lead that never completes the pipeline (no contact, tailoring/draft failed, or rejected at review) continues to consume zero credits.
- **3.6** A user with sufficient credits starts the pipeline run exactly as today.
- **3.7** `GET /api/outreach/quota` continues to return `{plan, used, limit, remaining, reset}`.
- **3.8** Credit counting continues to be per-tenant isolated (all queries scoped by `user_id`).

**Scope:**
All inputs that do NOT satisfy a bug condition are completely unaffected:
- Resumes already fitting one page (Bug 2 preservation).
- Resumes with no live links (Bug 3 preservation).
- Existing `resume_version` keys and all stored artifacts (Bug 1 preservation — the key is untouched; only `Content-Disposition` changes).
- Users with sufficient credits, and leads that never complete outreach (Bug 4 preservation).
- The derived-usage semantics of `count_outreach_used()` and the quota response shape (Bug 4 preservation).

**Note:** The expected correct behavior for buggy inputs is defined in the Correctness Properties section below.

## Hypothesized Root Cause

**Bug 1 — Malformed filename:**
1. **Overloaded key**: `save_resume()` returns a single string used for two distinct purposes — a stable object-store key (must be unique/namespaced) and, downstream, the user-facing download filename (must be clean). The namespacing that is correct for the key (`slugify(user_id)` prefix) is wrong for the filename.
2. **Verbatim reuse in `Content-Disposition`**: `get_lead_resume_pdf()` sets `filename="{resume_version}.pdf"`, propagating the ID-bearing key to the user.

**Bug 2 — Two-page overflow:**
1. **No single-page constraint**: The `@page` rule sets `size: letter` and margins but nothing bounds content height to one page; xhtml2pdf paginates naturally onto page 2 when content overflows.

**Bug 3 — Non-clickable links:**
1. **Renderer link handling**: The HTML anchors are correct (`_normalize_url` guarantees an absolute scheme). The gap is in xhtml2pdf's link-annotation output for the generated PDF, not in the markup.

**Bug 4 — Credit deduction + pre-flight check:**
1. **No pre-flight gate**: `run_pipeline()` and `run_for_leads()` create the run and spawn the background thread without ever reading `get_outreach_quota()`/`remaining` and comparing it to `requested_leads`.
2. **Derivation-only accounting**: Usage is only ever recomputed by counting completed-outreach leads (`count_outreach_used`), so there is no explicit pre-flight guard preventing a run that would exceed the balance. (The derived count remains the source of truth for the *balance*; the fix adds a gate, it does not replace the counting model — this preserves 3.5/3.7/3.8.)

## Correctness Properties

Property 1: Bug Condition - Clean, readable served filename (Bug 1)

_For any_ resume-download request where the bug condition holds (the served filename would contain `slugify(user_id)`), the fixed serving path SHALL set the `Content-Disposition` filename to a clean, human-readable value derived from the user's name and the company (pattern `{Name}_{Company}.pdf`) that does NOT contain `slugify(user_id)`, while leaving the internal `resume_version` storage key unchanged.

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition - Single-page PDF (Bug 2)

_For any_ resume where the bug condition holds (the current renderer produces more than one page), the fixed renderer SHALL produce a PDF constrained to exactly one page.

**Validates: Requirements 2.3**

Property 3: Bug Condition - Clickable hyperlinks (Bug 3)

_For any_ resume where the bug condition holds (it carries at least one live URL that is not surfaced as a clickable link), the fixed renderer SHALL embed each such URL as an actual clickable hyperlink annotation in the PDF.

**Validates: Requirements 2.4**

Property 4: Bug Condition - Real-time deduction + pre-flight sufficiency (Bug 4)

_For any_ pipeline-start request where the bug condition holds (no sufficiency check), the fixed route SHALL compare the caller's `remaining` credits against `requested_leads`: if `remaining >= requested_leads` the run SHALL start exactly as today; if `remaining < requested_leads` the run SHALL be rejected with a clear insufficient-credits response and no run created. A lead that completes outreach (status `sent`/`draft_created`) SHALL be reflected in the backend-derived balance in real time.

**Validates: Requirements 2.5, 2.6**

Property 5: Preservation - Non-buggy inputs unchanged

_For any_ input where the bug condition does NOT hold — a resume already fitting one page, a resume with no live links, an existing `resume_version` key and its stored artifacts, a user with sufficient credits, a lead that never completes outreach, and the `GET /api/outreach/quota` response — the fixed system SHALL produce the same result as the original system, preserving tailored content, stored artifacts, layout, plain-text rendering, run-start behavior, the quota response shape, and per-tenant isolation.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**Bug 1 — Clean served filename**

**File**: `api/main.py`
**Function**: `get_lead_resume_pdf` (`GET /api/leads/{lead_id}/resume-pdf`)

**Specific Changes**:
1. **Derive a clean filename at serve time**: Build a human-readable name from the lead's owner name and the lead's company (e.g. `{Name}_{Company}`), sanitized to filesystem-safe characters (mirroring the existing `download_resume_pdf` sanitizer: keep alphanumerics/space/`-`/`_`, collapse spaces to `_`), falling back to `resume` when empty.
2. **Change only `Content-Disposition`**: Set `filename="{clean_name}.pdf"`; keep fetching bytes by the unchanged `resume_version` store key (`store.get_bytes(f"{resume_version}.pdf")`).
3. **Leave `save_resume()`/`resume_version` untouched** so the object-store key and all existing references keep resolving (Regression 3.2).

**Note on name/company source**: The company is available on the lead; the display name is available from the tailored-resume JSON (`resume.get("name")`) or the user record. The implementation will resolve the cleanest available source without changing what is stored.

**Bug 2 — Single-page constraint**

**File**: `skills/tailor_resume.py`
**Functions**: `resume_to_pdf_bytes`, `resume_to_pdf` (shared render path via `resume_to_html` / `pisa.CreatePDF`)

**Specific Changes**:
1. **Constrain output to one page**: Add a single-page constraint to the render path (e.g. via the `@page` / body sizing and the xhtml2pdf render options) so overflow content is contained to a single letter page.
2. **Preserve one-page resumes**: The constraint must be a no-op for content that already fits (Regression 3.3) — verified by rendering an existing one-page resume before/after and comparing page count and content.

**Bug 3 — Clickable hyperlinks**

**File**: `skills/tailor_resume.py`
**Functions**: `resume_to_html` (anchor markup — already correct) and the `pisa.CreatePDF` render path

**Specific Changes**:
1. **Ensure link annotations render**: Make the xhtml2pdf render path emit live link annotations for existing `<a href>` anchors (contact links + project links). The anchor markup and `_normalize_url` scheme normalization stay as-is.
2. **No change for link-free resumes**: A resume with no anchors renders identically (Regression 3.4).

**Bug 4 — Pre-flight sufficiency check**

**File**: `api/main.py`
**Functions**: `run_pipeline` (`POST /api/pipeline/run`), `run_for_leads` (`POST /api/pipeline/run-for-leads`)

**Specific Changes**:
1. **Read the balance before starting**: In each route, before `repo.create_pipeline_run(...)`, call `repo.get_outreach_quota(user_id)` to obtain `remaining`.
2. **Compute `requested_leads`**: For `/run` use the clamped `yc_max` (`min(max(1, yc_max_leads or 5), 15)`); for `/run-for-leads` use `len(body.lead_ids)`.
3. **Gate the run**: If `remaining < requested_leads`, raise an HTTP error with a clear insufficient-credits detail (e.g. 402/403 with `{needed, remaining}` context) and do NOT create a run or spawn a thread. If `remaining >= requested_leads`, proceed exactly as today (Regression 3.6).
4. **Preserve counting semantics**: Do not alter `count_outreach_used()` / `get_outreach_quota()` return shape or per-tenant scoping (Regressions 3.7, 3.8). The derived balance already reflects completed-outreach leads in real time (each `sent`/`draft_created` lead increments the count) — no separate ledger is introduced.

**File**: `frontend/src/components/pipeline/run-pipeline-dialog.tsx`
**Function**: `handleRun`

**Specific Changes**:
1. **Surface rejection**: When `api.pipeline.run(...)` returns the insufficient-credits error, show a clear toast (reusing the existing `toast.error` path) so the user understands why the run did not start.
2. **Optional pre-flight display**: Optionally compare `ycMax` against the known remaining balance to disable/annotate the Run button before submit; the backend gate remains the authority.

## Testing Strategy

### Validation Approach

Two-phase: first surface counterexamples that demonstrate each bug on the unfixed code, then verify the fix works and preserves existing behavior. Because each bug is independent, each has its own exploratory + fix + preservation checks.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples on the UNFIXED code before implementing fixes; confirm or refute the root-cause analysis.

**Test Plan**: Exercise each affected function/route directly against representative inputs and assert the current (buggy) behavior, to lock in the counterexamples.

**Test Cases**:
1. **Filename (Bug 1)**: Call `save_resume(resume, "Acme Corp", user_id=<uuid>)` and assert the returned key contains `slugify(user_id)`; hit `GET /api/leads/{lead_id}/resume-pdf` and assert the `Content-Disposition` filename contains the UUID slug (will show the bug on unfixed code).
2. **Page count (Bug 2)**: Render a deliberately long tailored resume via `resume_to_pdf_bytes` and assert the PDF has >1 page (will fail-to-be-one-page on unfixed code).
3. **Hyperlinks (Bug 3)**: Render a resume with `contact.linkedin`/`github`/`portfolio` and a `projects[].link`; inspect the PDF for link annotations and assert they are absent/non-clickable on unfixed code.
4. **Pre-flight (Bug 4)**: With a user whose `remaining < requested_leads`, POST `/api/pipeline/run` with `yc_max_leads` above the balance and assert the run starts anyway (bug) on unfixed code; same for `/api/pipeline/run-for-leads` with more `lead_ids` than credits.

**Expected Counterexamples**:
- Served filename contains the user UUID slug.
- PDF page count > 1 for long content.
- No clickable link annotation for present URLs.
- Run accepted despite `remaining < requested_leads`.
- Possible alternative causes to rule out: for Bug 3, that the anchors are actually missing from the HTML (refuted — `resume_to_html` emits them), pointing to the renderer as the true cause.

### Fix Checking

**Goal**: Verify that for all inputs where a bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  // Bug 1
  IF input is ResumeDownloadRequest THEN
    result := servedFilename_fixed(input)
    ASSERT NOT (result CONTAINS slugify(input.user_id))
       AND result MATCHES pattern("{Name}_{Company}.pdf")
  // Bug 2
  ELSE IF input is Resume with overflow THEN
    ASSERT pageCount(renderPdf_fixed(input)) = 1
  // Bug 3
  ELSE IF input is Resume with live links THEN
    ASSERT FOR EACH url IN liveLinks(input): isClickableHyperlink(renderPdf_fixed(input), url)
  // Bug 4
  ELSE IF input is pipelineStart THEN
    ASSERT (remaining(input.user_id) >= input.requested_leads) IMPLIES runStarted(input)
    ASSERT (remaining(input.user_id) <  input.requested_leads) IMPLIES runRejected(input)
  END IF
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where no bug condition holds, the fixed function produces the same result as the original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT F(input) = F'(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation because it generates many inputs across the domain (varied resumes, varied credit balances, varied lead counts) and catches edge cases manual tests miss, giving strong assurance that non-buggy behavior is unchanged.

**Test Plan**: Observe behavior on UNFIXED code first, then write property-based tests capturing that behavior and re-run against the fix.

**Test Cases**:
1. **Storage key unchanged (3.2)**: `save_resume()` returns the same `resume_version` key for the same inputs after the fix; existing `{resume_version}.pdf` still resolves via `get_lead_resume_pdf`.
2. **Tailored content unchanged (3.1)**: For a fixed base resume + JD, the tailored JSON/MD content is byte-identical before/after (only the served filename differs).
3. **One-page resume unchanged (3.3)**: A resume already fitting one page renders with identical page count and content after the single-page constraint.
4. **Link-free resume unchanged (3.4)**: A resume with no URLs renders identically before/after.
5. **Sufficient-credit run unchanged (3.6)**: A user with `remaining >= requested_leads` starts the run exactly as today (same `{status, sources}` / `{status, leads}` response, run created, thread spawned).
6. **Quota shape + isolation (3.7, 3.8)**: `GET /api/outreach/quota` returns `{plan, used, limit, remaining, reset}`; one user's completed-outreach leads never change another user's `used`/`remaining`.
7. **Zero-credit-for-incomplete lead (3.5)**: A lead that never reaches `sent`/`draft_created` never contributes to `count_outreach_used`.

### Unit Tests

- Bug 1: `get_lead_resume_pdf` sets a clean `Content-Disposition` filename; `save_resume` return value (the store key) is unchanged.
- Bug 2: `resume_to_pdf_bytes` page count == 1 for long and short resumes.
- Bug 3: rendered PDF contains link annotations for each contact/project URL; none for a link-free resume.
- Bug 4: `run_pipeline` / `run_for_leads` reject when `remaining < requested_leads`, proceed when `remaining >= requested_leads`.

### Property-Based Tests

- Generate resumes of varied length and assert the rendered PDF is always exactly one page (Bug 2 + 3.3).
- Generate resumes with random subsets of live links and assert every present URL is a clickable annotation and link-free resumes are untouched (Bug 3 + 3.4).
- Generate `(remaining, requested_leads)` pairs and assert the route accepts iff `remaining >= requested_leads` (Bug 4 + 3.6), and that `get_outreach_quota` always returns the `{plan, used, limit, remaining, reset}` shape (3.7).

### Integration Tests

- End-to-end: tailor a resume for a lead, download via `GET /api/leads/{lead_id}/resume-pdf`, assert the download filename is clean and the PDF is one page with clickable links, and that the stored artifact still resolves by its unchanged key.
- End-to-end: with a low-credit user, attempt "Run Pipeline" from the dialog and assert the request is rejected with a clear insufficient-credits toast and no run is created; then with a sufficient-credit user assert the run starts and progresses through the stage pipeline as today.
- Per-tenant: two users with independent balances; one user's completed-outreach run does not affect the other's quota.
