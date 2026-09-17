# Bugfix Requirements Document

## Introduction

Four distinct production bugs affect the Auto Job Apply application (FastAPI backend under `api/`, `db/`, `skills/`, `orchestrator/`, `graph/`; Next.js frontend under `frontend/src/`). Three concern the tailored-resume artifact the pipeline produces (`skills/tailor_resume.py`), and one concerns credit accounting across the pipeline run/save flows (`db/repository.py`, `api/main.py`, `frontend/src/components/pipeline/run-pipeline-dialog.tsx`).

Bug summaries and located root causes:

1. **Malformed resume filename** — The tailored resume's base filename is built as `f"{user_slug}_{name_slug}_resume_{company_slug}"` in `save_resume()` (`skills/tailor_resume.py`), where `user_slug = slugify(user_id)` expands a long user UUID into the filename. That same `resume_version` string is then used verbatim as the download filename (`Content-Disposition: filename="{resume_version}.pdf"` in `api/main.py`'s `/api/leads/{lead_id}/resume-pdf`), so the user sees a long, ID-bearing filename instead of a clean name.

2. **Resume overflows to a second page** — `resume_to_pdf_bytes()` / `resume_to_pdf()` render the resume HTML through `xhtml2pdf` (`pisa.CreatePDF`) with no constraint that keeps output to a single page. When tailored content grows (extra bullets, longer summary), it flows onto a second page.

3. **Live links render as plain text, not clickable hyperlinks** — The URLs exist as real values in the resume JSON (e.g. `contact.linkedin`, `contact.github`, `contact.portfolio`, `projects[].link`) and `resume_to_html()` emits `<a href>` markup, but the generated PDF does not surface them as clickable hyperlinks.

4. **Credits not deducted in real time and no pre-flight sufficiency check** — Credits are only ever *derived* by counting leads already in `sent`/`draft_created` status (`count_outreach_used()` in `db/repository.py`); there is no explicit deduction event when a lead completes outreach. The pipeline-start routes (`POST /api/pipeline/run`, `POST /api/pipeline/run-for-leads`) never check the caller's remaining credit balance against the requested number of leads before starting, and the "Run Pipeline" dialog (`run-pipeline-dialog.tsx`) sends `yc_max_leads` with no credit check.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a tailored resume is generated for a lead THEN the system builds the resume filename as `{slugify(user_id)}_{name}_resume_{company}`, producing a long filename that embeds the user's ID

1.2 WHEN a user downloads or previews a lead's tailored resume THEN the system serves it with the raw `resume_version` (the ID-bearing base filename) as the download filename

1.3 WHEN a tailored resume's content is long enough THEN the system renders a PDF that overflows onto a second page

1.4 WHEN a resume containing live links (portfolio, LinkedIn, GitHub, project links) is rendered to PDF THEN the links appear as plain, non-clickable text

1.5 WHEN a lead completes the pipeline to a successful outreach (status `sent` or `draft_created`) THEN the system does not perform a real-time backend credit deduction against the user's balance for that lead

1.6 WHEN a user submits a number of leads to process via "Run Pipeline" or "Save to Pipeline" THEN the system starts the run without first checking whether the user has enough credits for the requested number of leads

### Expected Behavior (Correct)

2.1 WHEN a tailored resume is generated for a lead THEN the system SHALL build the filename in a normal, readable format combining the user's name and the company name (e.g. `FirstName_LastName_CompanyName.pdf`) without embedding the user's ID

2.2 WHEN a user downloads or previews a lead's tailored resume THEN the system SHALL serve it with a clean, human-readable filename derived from the user's name and the company name, not the ID-bearing internal key

2.3 WHEN a tailored resume is rendered to PDF THEN the system SHALL constrain the output to strictly one page, never overflowing to a second page

2.4 WHEN a resume containing live links (portfolio, LinkedIn, GitHub, project links) is rendered to PDF THEN the system SHALL embed those links as actual clickable hyperlinks in the document

2.5 WHEN a lead completes the pipeline to a successful outreach (status `sent` or `draft_created`) THEN the system SHALL deduct exactly 1 credit per such lead from the user's balance, driven by the backend, and reflect the updated balance in real time

2.6 WHEN a user submits a number of leads to process via "Run Pipeline" or "Save to Pipeline" THEN the system SHALL first check the user's remaining credits and SHALL only proceed if the balance is sufficient for the requested number of leads, otherwise rejecting the request with a clear insufficient-credits response

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a resume is tailored THEN the system SHALL CONTINUE TO produce the same tailored resume content (bullets, skills, ordering, ATS keyword coverage) it produces today, changing only the filename

3.2 WHEN the tailored resume artifacts are stored THEN the system SHALL CONTINUE TO persist the JSON/MD/PDF artifacts and the tailored-resume DB row, and existing stored resumes SHALL CONTINUE TO resolve for download/preview

3.3 WHEN a resume already fits on one page THEN the system SHALL CONTINUE TO render it correctly with its existing layout and content intact

3.4 WHEN a resume has no live links THEN the system SHALL CONTINUE TO render its plain text content unchanged

3.5 WHEN a lead never completes the pipeline (no contact found, tailoring/draft failed, or rejected at review) THEN the system SHALL CONTINUE TO consume zero credits for that lead

3.6 WHEN a user has sufficient credits for the requested number of leads THEN the system SHALL CONTINUE TO start the pipeline run exactly as it does today

3.7 WHEN the credit balance is read via `GET /api/outreach/quota` THEN the system SHALL CONTINUE TO return the `{plan, used, limit, remaining, reset}` response shape the frontend depends on

3.8 WHEN credits are counted THEN the system SHALL CONTINUE TO enforce per-tenant isolation, so one user's credit changes never affect another user's balance

## Deriving the Bug Conditions

### Bug 1 — Malformed filename

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type ResumeArtifactRequest   // (user_id, name, company)
  OUTPUT: boolean

  // The generated/served filename embeds the user id
  RETURN filename_of(X) CONTAINS slugify(X.user_id)
END FUNCTION
```

```pascal
// Property: Fix Checking - readable filename
FOR ALL X WHERE isBugCondition(X) DO
  result ← buildFilename'(X)
  ASSERT NOT (result CONTAINS slugify(X.user_id))
     AND result MATCHES pattern("{name}_{company}")
END FOR
```

### Bug 2 — Resume exceeds one page

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type Resume
  OUTPUT: boolean

  RETURN pageCount(renderPdf(X)) > 1
END FUNCTION
```

```pascal
// Property: Fix Checking - single page
FOR ALL X WHERE isBugCondition(X) DO
  result ← renderPdf'(X)
  ASSERT pageCount(result) = 1
END FOR
```

### Bug 3 — Live links not hyperlinks

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type Resume
  OUTPUT: boolean

  // Resume carries at least one live URL (contact links or project links)
  RETURN hasLiveLinks(X)
END FUNCTION
```

```pascal
// Property: Fix Checking - clickable hyperlinks
FOR ALL X WHERE isBugCondition(X) DO
  result ← renderPdf'(X)
  ASSERT FOR EACH url IN liveLinks(X):
           isClickableHyperlink(result, url)
END FOR
```

### Bug 4 — Credit deduction and pre-flight check

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type PipelineAction   // (user_id, requested_leads) or a completed lead
  OUTPUT: boolean

  // A lead completing outreach with no deduction, OR a run started without a
  // sufficiency check.
  RETURN (X is completedOutreachLead AND NOT creditDeducted(X))
      OR (X is pipelineStart AND NOT creditSufficiencyChecked(X))
END FUNCTION
```

```pascal
// Property: Fix Checking - real-time deduction + pre-flight sufficiency
FOR ALL X WHERE isBugCondition(X) DO
  IF X is completedOutreachLead THEN
    ASSERT creditsBurnedFor(X) = 1 AND balanceReflectsDeduction(X)
  ELSE IF X is pipelineStart THEN
    ASSERT (remainingCredits(X.user_id) >= X.requested_leads)
           IMPLIES runStarted(X)
    ASSERT (remainingCredits(X.user_id) <  X.requested_leads)
           IMPLIES runRejected(X)
  END IF
END FOR
```

### Preservation Goal (all bugs)

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

For non-buggy inputs — resumes that already fit one page, resumes with no live links, tailored content itself, users with sufficient credits, leads that never complete the pipeline, and the quota response shape — the fixed system behaves identically to the original.
