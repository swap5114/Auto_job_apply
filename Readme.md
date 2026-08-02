# Job Application Multi-Agent Pipeline

A personal automation pipeline for job hunting. It finds leads from job boards, company career pages, and X, structures them into one tracked list, then uses Claude to tailor a resume and draft outreach for each one. **Nothing goes out automatically** — every tailored resume and every outreach draft sits in a review queue (a Google Sheet) until it's manually approved. Once approved, it will be sent via Gmail (not yet built), and the system will track replies to trigger follow-ups on leads that go quiet (not yet built either).

This is a personal learning project, not a product. It's built and driven by me; Claude Code is used as a pair-programming guide — I review every skill's real output before moving to the next one, not just the diff.

---

## Status

| Phase | What it is | Status |
|---|---|---|
| 0 | Repo scaffold | ✅ Done |
| 1 | Leads storage/dedupe layer (`storage/sheet_client.py`) | ✅ Done |
| 2 | Scrape job boards — Arbeitnow, Jobicy, one careers page | ✅ Done |
| 2b | `company_list.py` — CSV-driven bulk company scraping (not in the original plan, added later) | ⚠️ Built, not yet verified against a live run |
| 3 | Scrape X for hiring-signal leads (Sorsa API) | ✅ Done |
| 4 | Find contact email (Hunter.io) | ✅ Done, verified end-to-end |
| 5 | Tailor resume per lead (Claude + PDF generation) | ✅ Done, thoroughly verified |
| 6 | Draft outreach per lead (Claude) | ✅ Done, verified end-to-end |
| 7 | Human review checkpoint (LangGraph interrupt) | ⬜ Not started |
| 8 | Send via Gmail (drafts-first, then approved-send) | ⬜ Not started |
| 9 | Track follow-ups (cyclic edge back into draft_outreach) | ⬜ Not started |
| 10 | Wire everything into an actual LangGraph graph | ⬜ Not started |
| 10b | Vellum Assistant as the cron trigger | ⬜ Not started |
| 11 | Deploy to a VM | ⬜ Not started |

A cross-cutting piece not in the original phase numbering: `skills/relevance_filter.py` + `config/search_criteria.json`, a keyword filter applied by every scraper before a lead is even written to the Sheet.

---

## Architecture

### Target architecture: a LangGraph graph

The pipeline is designed as a **graph**, not a script — nodes are skills, edges are what runs next. A human review step is a genuine **interrupt** (the graph pauses and waits), and follow-up tracking is a genuine **cycle** (a node's output can route back into an earlier node), not a `while` loop bolted on top.

```mermaid
flowchart TD
    Vellum["Vellum Assistant\n(cron trigger only)"] -->|starts a run| Scrape

    subgraph Scrape["Lead sourcing (parallel nodes)"]
        A1[arbeitnow.py]
        A2[jobicy.py]
        A3[careers_page.py]
        A4[company_list.py]
        A5[scrape_x_leads.py]
    end

    Scrape -->|relevance_filter, then add_lead| Sheet[(Google Sheet\nleads DB)]

    Sheet --> FCE[find_contact_email.py\nHunter.io]
    FCE --> TR[tailor_resume.py\nClaude + PDF]
    TR --> DO[draft_outreach.py\nClaude]
    DO --> Review{{"Review checkpoint\n(LangGraph interrupt)"}}

    Review -->|approved| Send[send_via_gmail.py]
    Review -->|rejected / edited| DO

    Send --> Track[track_followups.py]
    Track -->|no reply after N days| DO
    Track -->|replied / closed| Done([Done])
```

**Why a graph instead of a script:** two of the remaining phases genuinely don't fit a linear script. Phase 7 needs the pipeline to *pause mid-run and wait for a human*, then resume exactly where it left off — that's what a LangGraph interrupt is for. Phase 9 needs a *real cycle*: a stale lead's follow-up should re-enter `draft_outreach` and go through the same review gate again, not call itself recursively or get hand-rolled with a scheduler. A plain script can fake both with enough `if`/`while` scaffolding, but the graph gives them as first-class primitives instead of ad-hoc state management.

### Current architecture: independent scripts around a shared Sheet

None of the graph/interrupt/cycle machinery exists yet. **Phases 0–6 today are standalone Python scripts**, each runnable independently, coordinating purely through the Google Sheet as shared state:

```mermaid
flowchart LR
    A1[arbeitnow.py] --> Sheet[(Google Sheet)]
    A2[jobicy.py] --> Sheet
    A3[careers_page.py] --> Sheet
    A4[company_list.py] --> Sheet
    A5[scrape_x_leads.py] --> Sheet
    Sheet --> FCE[find_contact_email.py]
    FCE --> Sheet
    Sheet --> TR[tailor_resume.py]
    TR --> Sheet
    Sheet --> DO[draft_outreach.py]
    DO --> Sheet
    Sheet -.human reviews in the Sheet UI, no send yet.-> Human((You))
```

Every script follows the same shape: **read leads missing some field → do the work → write that field back via `update_lead`**. `tailor_resume.py` only processes leads with no `resume_version`; `draft_outreach.py` only processes leads with a `resume_version` but no `outreach_draft`; `find_contact_email.py` only processes leads with no `contact_email`. This makes every script naturally idempotent and re-runnable — running it twice in a row is always safe and does zero extra work the second time.

**Why build it this way first, deliberately, instead of the graph up front:**

| | |
|---|---|
| **Benefit** | Each phase is independently testable and debuggable *before* any orchestration complexity exists — critical when learning, since a bug can be isolated to one script instead of hiding inside graph control flow. |
| **Benefit** | The Sheet already behaves like a durable queue/checkpoint between stages. Migrating to LangGraph later is mostly wrapping existing `run()` functions as graph nodes and adding routing — the business logic inside each skill doesn't need to be rewritten. |
| **Benefit** | Lower blast radius: a bug in `tailor_resume.py` can't take down scraping, and re-running just the affected script picks up exactly where it left off (see the idempotency note above). |
| **Tradeoff** | No automatic sequencing today — a human runs each script in order by hand. Nothing currently triggers the next stage automatically. |
| **Tradeoff** | No conditional routing (e.g. "retry `find_contact_email` later if Hunter has no data yet, skip straight to a manual-lookup queue instead") — this is exactly what graph edges will add. |
| **Tradeoff** | "Resume where you left off" today just means "whichever Sheet fields are still empty" — a real interrupt would give a first-class pause/resume state instead of inferring it from column emptiness. |
| **Tradeoff** | The Phase 9 cyclic follow-up edge fundamentally can't be faked with a plain script without hand-rolled scheduling — it's blocked on Phase 10 (the graph) existing. |

---

## Design decisions and tradeoffs

| Decision | Chosen | Alternative considered | Why chosen | Tradeoff accepted |
|---|---|---|---|---|
| Leads database | Google Sheets (`gspread` + service account) | A real DB (Postgres/SQLite) | Zero infrastructure, and it *is* the human review UI for free — no separate dashboard needed, which keeps "no web dashboard" out of scope honestly. | Not queryable — every read is `get_all_records()` + Python filtering (scans the whole sheet), every write is a rate-limited Sheets API call. Fine at personal job-search volume, wouldn't scale past low thousands of rows. |
| Contact discovery | Hunter.io Domain Search | Apollo | Apollo's free tier returns `403 API_INACCESSIBLE` on its email-enrichment endpoint — confirmed live, not a docs-reading mistake. Hunter's Domain Search is usable on a free key. | Hunter's free index has real coverage gaps for small/startup domains — confirmed live: correct domain, zero emails returned. No fix for that other than accepting some leads need a manual contact lookup. `APOLLO_API_KEY` still sits unused in `.env` for reference. |
| Scraping backend | Firecrawl REST API called directly from Python | "Hermes Agent" (local Ollama model + Scrapling), per the original plan | The `hermes -z` one-shot agent CLI was unreliable — it hallucinated fake environment limitations and ignored its own tools. Ironically, Hermes itself generated a plain Firecrawl-REST-plus-regex solution that worked, which is the pattern that got ported into the real code. | Lost the "an agent figures out selectors per site" flexibility. `company_list.py`'s role-link extraction is a hand-rolled heuristic (markdown link regex + known-ATS-domain matching + a nav-link denylist) — it will miss some postings and occasionally pick up a stray link, capped at 20 roles/company as a budget guard. |
| Resume-tailoring model | Claude Sonnet 5 | Claude Haiku ("for volume", per the original plan) | Resume content directly represents the candidate to employers — fabrication risk was judged too high-stakes for a cheaper/smaller model. | Higher per-call cost, but tailoring is inherently one call per lead (low volume), so the absolute cost difference is small. Easy call once framed that way. |
| Resume PDF rendering | HTML/CSS template rendered via `xhtml2pdf` | `fpdf2` with manually positioned cells (the original approach) | `fpdf2` hit two real bugs (assumed `response.content[0]` was always text when Sonnet 5 returns a thinking block first; `multi_cell` doesn't reset the cursor like `cell` does) and even once fixed, the output didn't visually match the candidate's real resume template. HTML/CSS gives close visual control for far less code. | An extra dependency, plus PDF-encoding quirks — the default fonts only support Latin-1/WinAnsi, so a `sanitize_for_pdf` step swaps em-dashes/smart quotes/arrows for ASCII equivalents before rendering. |
| Relevance filtering | Keyword/regex filter (`relevance_filter.py`) | An LLM classifier per listing | Zero marginal cost — a scrape run can pull hundreds of listings, and an LLM call per listing just to decide "is this worth tailoring for" would be needless spend before any real filtering value is added. | Coarse. Whole-word matching fixed one real bug (substring match on `"ai"` matching inside `"maintain"`/`"email"`) but the filter still can't catch tech-stack-specific mismatches (a "Full Stack" JD that turns out to require Rails specifically) or spoken-language requirements (German B2+). Those slip through to the expensive Claude stages — caught only by the zero-fabrication discipline there, not blocked upstream. Known, accepted gap. |
| Orchestration | LangGraph graph (**planned**, not yet built) | A single linear script | Phase 7 (pause-and-wait-for-human) and Phase 9 (cycle back into `draft_outreach`) aren't naturally linear — see the Architecture section above for the full reasoning. | Until Phase 10 is built, there's no automatic sequencing between phases — see the Architecture tradeoffs table above. |
| Scheduling | Vellum Assistant as a thin cron trigger (**planned**, not yet built) | Scheduling logic built into the app itself | Keeps the pipeline's own code free of scheduling concerns — Vellum's only job is "wake up on a schedule, start a LangGraph run." | An external dependency for something as simple as a cron tick — accepted since it was already part of the original plan and keeps the app itself simpler. |

---

## Repo structure

```
skills/
  scrape_job_boards/
    arbeitnow.py       Arbeitnow public job API (free, no key)
    jobicy.py          Jobicy public remote-job API (free, no key)
    careers_page.py     Firecrawl scrape of a hardcoded (url, company) list
    company_list.py     CSV-driven bulk scraping + Firecrawl career-page auto-discovery
  scrape_x_leads.py     Sorsa API — X hiring-signal leads
  relevance_filter.py   Keyword filter applied before every add_lead()
  find_contact_email.py Hunter.io Domain Search + regex bio/tweet scan
  tailor_resume.py      Claude-powered resume tailoring + PDF/MD/JSON generation
  draft_outreach.py     Claude-powered outreach drafting (email or X-DM)
storage/
  sheet_client.py       The shared leads DB: add_lead, get_leads, update_lead
config/
  .env                  API keys (gitignored)
  .env.example           Template for the above
  credentials.json       Google service-account key (gitignored)
  base_resume.json        The candidate's real resume, as structured JSON
  search_criteria.json    Relevance-filter criteria (roles, seniority, location)
resumes/
  swapnil_jain_resume.pdf                 Original resume (template reference)
  swapnil_jain_resume_{company}.{json,md,pdf}   Tailored output, one set per lead
tests/
  test_sheet_client.py   Manual verification script for Phase 1
```

---

## Leads schema (Google Sheet columns)

`id, source, company, role, jd_text, contact_name, contact_email, x_handle, status, resume_version, outreach_draft, sent_at, last_checked, followup_count, listing_url, posted_date, domain`

- `source` is one of `arbeitnow`, `jobicy`, `careers_page`, `company_list`, or `x`.
- A lead needs either (`company` **and** `role`) or a non-empty `x_handle` — X leads legitimately have neither of the first two.
- `domain`, when known (from `company_list.py`'s CSV or its own guessing fallback), takes priority over `find_contact_email.py`'s own domain-guessing heuristic, regardless of source.
- Every downstream skill (`find_contact_email`, `tailor_resume`, `draft_outreach`) treats all sources identically once a lead exists — there's no branching by source past `add_lead()`, except inside `draft_outreach.py`, which drafts a short DM instead of an email specifically for `source == "x"`.

---

## Skills reference

**`storage/sheet_client.py`** — the shared data layer. `add_lead` rejects duplicates (same company+role, case-insensitive, or same non-empty `x_handle`) and raises loudly if a lead has neither identifying field. `get_leads` optionally filters by `status`. `update_lead` writes named fields by row lookup on `id`.

**Scrapers** (`arbeitnow.py`, `jobicy.py`, `careers_page.py`, `company_list.py`, `scrape_x_leads.py`) — each pulls raw postings from one source, builds a lead dict, runs it through `relevance_filter.matches_criteria`, and calls `add_lead`. Every one prints a summary line (`added` / `skipped` / `filtered_out`) so a run's outcome is never silent.

**`relevance_filter.py`** — whole-word keyword matching (not substring — see the tradeoffs table above) against `config/search_criteria.json`: role keywords must match, seniority-exclude keywords must not match, and JD mentions of "N+ years" are rejected once N crosses the configured threshold. Location is informational only, never a hard filter, per explicit instruction.

**`find_contact_email.py`** — X leads get a free regex scan of their bio/tweet text first. Company leads with a known `domain` use it directly; otherwise, `arbeitnow`/`jobicy` leads get a domain *guessed* from the company name (legal-entity suffixes like "B.V."/"Inc"/"GmbH" stripped, both a smashed-together and hyphenated candidate tried against Hunter, since it costs nothing on a miss); `careers_page` leads use the real domain straight from their `listing_url`. A miss is always printed with which domains were tried, never silently counted.

**`tailor_resume.py`** — sends the base resume (JSON) and a lead's JD to Claude Sonnet 5 under a strict zero-fabrication system prompt (nothing invented; bullets may be reordered/reworded but never claim new scope, tools, or metrics beyond what the base resume already supports). Saves the tailored resume as `.json`, `.md`, and a template-matched `.pdf` per lead, and prints a rough (directional-only) ATS keyword-coverage percentage.

**`draft_outreach.py`** — reads the *tailored* resume (not the base one) so the message stays consistent with what actually gets sent. Two formats by `source`: a short email (`Subject:` line + body, hard-capped at 150 words) for company leads, a casual DM (hard-capped at 60 words) for X leads. Same zero-fabrication discipline as tailoring, plus rules earned from a real review pass: no cover-letter clichés ("I came across your opening", "I look forward to hearing from you"), and every message must pull a genuinely company-specific hook from the actual JD text rather than a compliment generic enough to paste into any other outreach.

---

## Permanent constraints

These hold regardless of how much automation gets added later — never relaxed as a "v1 simplification":

- **Human review gate before any send.** No auto-send-once-confident shortcut, ever.
- **Every skill logs or raises loudly on failure.** Never silently skip a lead.
- **Zero fabrication** anywhere resume or outreach content touches the candidate's actual history. Stress-tested against a genuinely mismatched JD (a role requiring Ruby on Rails and German B2+, neither of which the candidate has) — both `tailor_resume` and `draft_outreach` correctly declined to fabricate or paper over the gap.
- **Out of scope for v1:** ATS auto-fill, LinkedIn scraping/automation, a web dashboard (the Sheet *is* the dashboard).

---

## Running it today

There's no orchestrator yet, so each stage is run by hand, in order:

```bash
# 1. Source leads (any subset, any order)
python -m skills.scrape_job_boards.arbeitnow
python -m skills.scrape_job_boards.jobicy
python -m skills.scrape_job_boards.careers_page
python -m skills.scrape_job_boards.company_list path/to/companies.csv
python -m skills.scrape_x_leads

# 2. Enrich + process (each is safe to re-run; only touches leads missing that field)
python -m skills.find_contact_email
python -m skills.tailor_resume
python -m skills.draft_outreach

# 3. Review manually in the Google Sheet.
#    Sending (Phase 8) doesn't exist yet -- for now, review and send by hand.
```

### Setup

1. `python -m venv venv` and activate it, then `pip install -r requirements.txt`.
2. Copy `config/.env.example` to `config/.env` and fill in: `SORSA_API_KEY`, `HUNTER_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_SHEET_ID`, `FIRECRAWL_API_KEY`. (`APOLLO_API_KEY` and the `GMAIL_*` keys are reserved for unused/not-yet-built pieces.)
3. Add a Google service-account key at `config/credentials.json` (never committed — see `.gitignore`), shared with edit access on the target Sheet.
4. `config/base_resume.json` and `config/search_criteria.json` are already checked in — edit them to match your own resume and search preferences.
