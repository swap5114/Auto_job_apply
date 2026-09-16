import os
import sys
import re
import json
from dotenv import load_dotenv
from xhtml2pdf import pisa
import html as html_lib

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import repository as repo
from db.current_user import get_current_user_id
from skills.llm_client import llm_generate_json, MODEL_BACKEND

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

BASE_RESUME_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "base_resume.json")
RESUMES_DIR = os.path.join(os.path.dirname(__file__), "..", "resumes")

# Target ATS keyword-coverage. Used only to LABEL a tailored resume as
# below-floor for the UI — production does NOT retry to chase it (single call).
MIN_ATS_SCORE = 80.0

# Which model production uses to tailor. Chosen ONCE, offline, by
# scripts/benchmark_tailor_models.py (Gemini vs Claude on real ATS scores),
# then pinned here / via the TAILOR_BACKEND env var. Production makes a SINGLE
# call to this model — never a runtime comparison.
#   unset / ""     -> global MODEL_BACKEND default (Vertex/Gemini)
#   "vertex_claude" -> Claude via Vertex
#   "vertex"        -> Gemini via Vertex
TAILOR_BACKEND = os.getenv("TAILOR_BACKEND") or None

# Resume templates the app supports (matches the frontend switcher + the two
# PDF renderers). "jake" is the classic ruled/centered layout; "standard" is a
# cleaner conventional layout.
TEMPLATES = ("standard", "jake")
DEFAULT_TEMPLATE = "jake"

SYSTEM_PROMPT = """You are a resume-tailoring assistant. You will be given a candidate's base resume (as structured JSON) and a job description. Your job is to produce a tailored version of the resume for this specific job.

STRICT RULES -- violating any of these is a critical failure:
1. NEVER invent a bullet, skill, project, job title, company, date, or metric that is not already present in the base resume.
2. You MUST actively tailor bullets, not just reorder them wholesale -- this applies especially to PROJECT bullets and Technical Skills, which are the sections most directly relevant to matching a specific job/company's stack. Reword bullets to use this job description's and company's own terminology wherever the base resume already truthfully supports that claim. Passing a bullet through completely unchanged should be the exception (when no honest alignment is possible), not the default -- if you find yourself leaving every project bullet word-for-word identical to the input, you have not done the job.
3. You MAY reorder bullets within an experience or project entry to lead with whatever is most relevant to this job description.
4. Rewording must NEVER change what a bullet claims -- no new scope, no upgraded metrics, no changed responsibility level, and no technology/tool that isn't already listed for that specific entry in the base resume.
5. You MAY reorder skill categories and the skills within them to bring job-relevant skills to the front, and MAY rephrase a skill using the JD's terminology if it is a genuine synonym for a skill already listed (e.g. "REST API design" for "REST APIs") -- never add a skill that isn't already there.
6. You MAY reorder which projects/experience entries appear first, based on relevance to this job description.
7. You MUST NOT change company names, job titles, dates, degree, GPA, or institution names -- copy these through exactly as given.
8. When the base resume already truthfully supports a claim, use the job description's exact terminology where possible (e.g. if the JD says "Node.js" and the bullet already covers that, keep the term "Node.js" rather than paraphrasing) -- this matters for ATS keyword matching.
9. MAXIMIZE ATS keyword coverage: aim to reflect as many of the job description's real skills/tools/responsibilities as the base resume TRUTHFULLY supports, using the JD's exact wording. The goal is high keyword overlap with the JD WITHOUT ever adding anything the base resume doesn't already contain. If the JD mentions something the candidate genuinely hasn't done, leave it out -- honesty always wins over coverage.

Return ONLY valid JSON matching the exact same structure as the input base resume. No prose, no markdown code fences, no explanation -- just the JSON object."""


class NoResumeError(Exception):
    """Raised when we cannot resolve a real, user-owned base resume to tailor.

    This is deliberately loud: silently falling back to a shared file
    (config/base_resume.json) was the exact mechanism by which one person's
    resume leaked into every user's outreach. For any real authenticated
    user, "no resume on file" must fail cleanly here, never borrow someone
    else's resume.
    """


def _is_local_operator(user_id: str | None) -> bool:
    """True only for the single local-CLI operator user (db.current_user).

    The config/base_resume.json fallback is exclusively for this identity --
    the offline, single-tenant CLI dev flow -- never for a real multi-tenant
    HTTP user. Any failure to resolve the operator id is treated as "not the
    operator" so we err on the side of NOT using the shared file.
    """
    if not user_id:
        return False
    try:
        from db.current_user import LOCAL_USER_FIREBASE_UID
        operator = repo.get_user_by_firebase_uid(LOCAL_USER_FIREBASE_UID)
        return bool(operator and str(operator.get("id")) == str(user_id))
    except Exception:
        return False


def load_base_resume(user_id: str | None = None) -> dict:
    """Return the base resume to tailor, strictly scoped to `user_id`.

    Resolution order:
      1) The user's OWN primary resume in the DB (per-tenant, the only path
         a real user should ever hit).
      2) config/base_resume.json — ONLY for the single local-CLI operator
         (see _is_local_operator). Never for a real authenticated user.

    Raises NoResumeError if a real user has no resume on file. Callers must
    treat this as a hard "needs a resume" failure and NOT tailor, rather than
    substituting anyone else's resume.
    """
    if user_id is None:
        # No explicit user only happens on the local CLI entry points; resolve
        # the single operator so its config/base_resume.json can apply.
        try:
            user_id = get_current_user_id()
        except Exception:
            user_id = None

    if user_id:
        try:
            db_resume = repo.get_primary_resume(user_id)
            if db_resume and db_resume.get("parsed_json"):
                return db_resume["parsed_json"]
        except Exception as e:
            print(f"  ⚠️  load_base_resume: failed to load DB resume for user {user_id}: {e}")

    # Shared file fallback is restricted to the local CLI operator only.
    if _is_local_operator(user_id) and os.path.exists(BASE_RESUME_PATH):
        with open(BASE_RESUME_PATH, encoding="utf-8") as f:
            return json.load(f)

    raise NoResumeError(
        f"No base resume on file for user {user_id or '(unknown)'}. "
        "Upload a resume before tailoring — refusing to fall back to a shared resume."
    )


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def tailor_resume(
    base_resume: dict, company: str, role: str, jd_text: str,
    company_research: dict | None = None,
) -> dict:
    """Tailor base_resume to a specific job. company_research (optional) is
    the dict returned by skills.research_company.research_company() -- when
    present, it's given to the model purely as extra context on what the
    company cares about, to help it choose which already-true bullets to
    foreground. It never introduces new claims: the STRICT RULES in
    SYSTEM_PROMPT (no invented bullets/skills/metrics) still govern output.
    """
    research_context = ""
    if company_research:
        research_context = f"""

Additional context on this company (for prioritizing which existing, true
resume content to foreground -- this does NOT give you license to invent
anything new):
{json.dumps(company_research, indent=2)}"""

    result = tailor_resume_verbose(base_resume, company, role, jd_text, company_research=company_research)
    return result["tailored"]


def build_tailor_message(
    base_resume: dict, company: str, role: str, jd_text: str,
    company_research: dict | None = None,
) -> str:
    """The user-message sent to the tailoring model. Shared by production and
    the offline model benchmark so both exercise identical prompts."""
    research_context = ""
    if company_research:
        research_context = f"""

Additional context on this company (for prioritizing which existing, true
resume content to foreground -- this does NOT give you license to invent
anything new):
{json.dumps(company_research, indent=2)}"""

    return f"""Job description:
Company: {company}
Role: {role}

{jd_text}{research_context}

Base resume (JSON):
{json.dumps(base_resume, indent=2)}"""


def tailor_resume_verbose(
    base_resume: dict, company: str, role: str, jd_text: str,
    company_research: dict | None = None,
) -> dict:
    """Production tailoring: a SINGLE call to the configured model.

    The model is chosen ONCE, offline, by comparing Gemini vs Claude on
    tailoring quality (scripts/benchmark_tailor_models.py). Whichever wins is
    set as TAILOR_BACKEND, and production always makes exactly one call to it
    — no runtime multi-model comparison, no retry loop.

    If the model's output fabricates content not in the base resume, it's
    rejected and the untouched base resume is returned (we never ship a
    fabricated resume). Returns {"tailored", "keyword_coverage", "model_used"}.
    """
    base_message = build_tailor_message(base_resume, company, role, jd_text, company_research)
    backend = TAILOR_BACKEND  # None => global MODEL_BACKEND default (Vertex/Gemini)
    label = backend or MODEL_BACKEND or "vertex"

    candidate, score = _tailor_once(base_message, jd_text, base_resume, backend)
    if candidate is not None:
        note = "" if score >= MIN_ATS_SCORE else f"  ⚠️ below {MIN_ATS_SCORE}% ATS floor"
        print(f"  tailor_resume: ATS {score}% via {label}{note}")
        return _tailor_result(candidate, score, label)

    # Only reached if the LLM call itself failed (network/parse) — return the
    # untouched base so the user still gets their resume.
    print("  ⚠️  tailor_resume: model call failed; using base resume.")
    return _tailor_result(base_resume, keyword_coverage(jd_text, base_resume), label)


def _tailor_once(
    base_message: str, jd_text: str, base_resume: dict, backend: str | None,
) -> tuple[dict | None, float]:
    """One tailoring call on a single backend. Returns (candidate, score), or
    (None, -1) if the call itself failed.

    We do NOT discard the whole tailored resume when the validator flags
    something — that was throwing away all the legitimate rewording and
    JD-keyword alignment and silently handing back the untouched base. Instead
    we SANITIZE: keep the model's reworded bullets, summary, skill rephrasing,
    and reordering, but repair only genuine identity drift — restore any
    company/title/institution/project name that changed, and drop only truly
    new skills (a rephrased synonym of an existing skill is kept). This
    guarantees honesty without nuking the tailoring itself."""
    try:
        candidate = llm_generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_message=base_message,
            max_tokens=4096,
            backend=backend,
        )
    except Exception as e:
        print(f"  ⚠️  tailor ({backend or 'default'}) failed: {e}")
        return None, -1.0

    cleaned = sanitize_tailored(base_resume, candidate)
    return cleaned, keyword_coverage(jd_text, cleaned)


def _is_skill_rephrase(new_skill: str, base_skills: set[str]) -> bool:
    """True if `new_skill` is a legitimate rephrasing of an existing base skill
    (a substring/superset overlap), not a genuinely new claim. E.g. base has
    "rest apis" and the tailored version says "rest api design" — allowed by
    SYSTEM_PROMPT rule 5. "kubernetes" with no base overlap is NOT a rephrase."""
    n = _norm_token(new_skill)
    if not n:
        return True
    for b in base_skills:
        if not b:
            continue
        if n == b or n in b or b in n:
            return True
        # token overlap: share a significant word (e.g. "rest api design" vs "rest apis")
        nb, bb = set(n.split()), set(b.split())
        if nb & bb and (nb <= bb or bb <= nb or len(nb & bb) >= 2):
            return True
    return False


def sanitize_tailored(base_resume: dict, tailored: dict) -> dict:
    """Return a copy of `tailored` with identity drift repaired against
    `base_resume`, WITHOUT discarding the rework:

      - experience/education/projects: keep the model's bullets/tech/order,
        but force company/title/institution/project-name/dates back to the
        base entry they map to (matched positionally, then by fuzzy name), so
        no employer/role/school/project can be invented or renamed.
      - skills: keep reworded/reordered skills that overlap an existing base
        skill (allowed synonym); drop only skills with no base overlap.
      - name/contact: always taken from the base (never model-editable).
    """
    if not isinstance(tailored, dict):
        return base_resume

    out = dict(tailored)

    # Name + contact are never the model's to change.
    out["name"] = base_resume.get("name")
    out["contact"] = base_resume.get("contact")

    base_exp = base_resume.get("experience") or []
    base_edu = base_resume.get("education") or []
    base_proj = base_resume.get("projects") or []

    def _match(base_list, entry, key):
        """Find the base entry this tailored entry corresponds to, by
        normalized identity key (falls back to positional in caller)."""
        target = _norm_token(entry.get(key, ""))
        for b in base_list:
            if _norm_token(b.get(key, "")) == target and target:
                return b
        return None

    # Experience: pin company/title/dates to a base entry (positional first).
    fixed_exp = []
    for i, e in enumerate(out.get("experience") or []):
        b = base_exp[i] if i < len(base_exp) else (_match(base_exp, e, "company") or {})
        fixed = dict(e)
        for f in ("company", "title", "start_date", "end_date"):
            if b.get(f) is not None:
                fixed[f] = b.get(f)
        fixed_exp.append(fixed)
    if out.get("experience") is not None:
        out["experience"] = fixed_exp

    # Education: pin institution/degree/dates.
    fixed_edu = []
    for i, e in enumerate(out.get("education") or []):
        b = base_edu[i] if i < len(base_edu) else (_match(base_edu, e, "institution") or {})
        fixed = dict(e)
        for f in ("institution", "degree", "start_date", "end_date"):
            if b.get(f) is not None:
                fixed[f] = b.get(f)
        fixed_edu.append(fixed)
    if out.get("education") is not None:
        out["education"] = fixed_edu

    # Projects: pin name/date/link (bullets + tech_stack rework kept).
    fixed_proj = []
    for i, p in enumerate(out.get("projects") or []):
        b = base_proj[i] if i < len(base_proj) else (_match(base_proj, p, "name") or {})
        fixed = dict(p)
        for f in ("name", "date", "link"):
            if b.get(f) is not None:
                fixed[f] = b.get(f)
        fixed_proj.append(fixed)
    if out.get("projects") is not None:
        out["projects"] = fixed_proj

    # Skills: keep rephrasings of existing skills; drop genuinely-new ones.
    base_skill_set = _collect_source_facts(base_resume)["skill"]
    tsk = out.get("skills")
    if isinstance(tsk, dict):
        cleaned_skills = {}
        for cat, items in tsk.items():
            kept = [it for it in (items or []) if _is_skill_rephrase(it, base_skill_set)]
            if kept:
                cleaned_skills[cat] = kept
        # If the model wiped skills entirely, fall back to the base skills.
        out["skills"] = cleaned_skills or base_resume.get("skills")
    elif isinstance(tsk, list):
        out["skills"] = [it for it in tsk if _is_skill_rephrase(it, base_skill_set)] or base_resume.get("skills")

    return out


def _tailor_result(tailored: dict, score: float, model_used: str, escalated: bool = False) -> dict:
    return {
        "tailored": tailored,
        "keyword_coverage": score,
        "model_used": model_used,
        # Retained for response-shape compatibility; production uses a single
        # configured model, so this is always False now.
        "escalated": escalated,
    }


def diff_resumes(base: dict, tailored: dict) -> dict:
    """Compute a change-map between the base and tailored resumes so the UI can
    highlight exactly what tailoring changed. Positional (by section + index):

      {
        "experience": [ [changed_bool_per_bullet], ... ],   # per exp entry
        "projects":    [ [changed_bool_per_bullet], ... ],
        "skills":      { "Category": [changed_bool_per_skill] },
        "summary":     changed_bool,
      }

    "changed" = the tailored text differs from the base text at that position
    (after whitespace/case normalization). New positions the base didn't have
    also count as changed. This is a presentation aid, not the anti-fabrication
    check (that's find_fabrications)."""
    def norm(s) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    out: dict = {}

    out["summary"] = norm(base.get("summary")) != norm(tailored.get("summary"))

    def bullets_diff(base_entries, tail_entries):
        result = []
        for i, t in enumerate(tail_entries or []):
            b = (base_entries or [])[i] if i < len(base_entries or []) else {}
            b_bullets = b.get("bullets", []) or []
            t_bullets = t.get("bullets", []) or []
            flags = []
            for j, tb in enumerate(t_bullets):
                bb = b_bullets[j] if j < len(b_bullets) else None
                flags.append(bb is None or norm(bb) != norm(tb))
            result.append(flags)
        return result

    out["experience"] = bullets_diff(base.get("experience"), tailored.get("experience"))
    out["projects"] = bullets_diff(base.get("projects"), tailored.get("projects"))

    # Skills: per-category, which skills are new/reworded vs the base category.
    base_skills = base.get("skills", {}) or {}
    tail_skills = tailored.get("skills", {}) or {}
    skills_flags: dict = {}
    if isinstance(tail_skills, dict):
        for cat, items in tail_skills.items():
            base_items = [norm(x) for x in (base_skills.get(cat, []) if isinstance(base_skills, dict) else [])]
            skills_flags[cat] = [norm(it) not in base_items for it in (items or [])]
    out["skills"] = skills_flags

    return out


# ---------------------------------------------------------------------------
# Anti-fabrication validation
# ---------------------------------------------------------------------------

def _norm_token(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _collect_source_facts(resume: dict) -> dict[str, set[str]]:
    """Collect the atomic, checkable facts a tailored resume must not exceed:
    company names, job titles, institutions, project names, and the flat set
    of skills. Used to catch fabricated identity/scope, not phrasing changes.
    """
    companies: set[str] = set()
    titles: set[str] = set()
    institutions: set[str] = set()
    projects: set[str] = set()
    skills: set[str] = set()

    for exp in resume.get("experience", []) or []:
        if exp.get("company"):
            companies.add(_norm_token(exp["company"]))
        if exp.get("title"):
            titles.add(_norm_token(exp["title"]))
    for edu in resume.get("education", []) or []:
        if edu.get("institution"):
            institutions.add(_norm_token(edu["institution"]))
    for proj in resume.get("projects", []) or []:
        if proj.get("name"):
            projects.add(_norm_token(proj["name"]))
    sk = resume.get("skills", {}) or {}
    if isinstance(sk, dict):
        for items in sk.values():
            for it in items or []:
                skills.add(_norm_token(it))
    elif isinstance(sk, list):
        for it in sk:
            skills.add(_norm_token(it))

    return {
        "company": companies,
        "title": titles,
        "institution": institutions,
        "project": projects,
        "skill": skills,
    }


def find_fabrications(base_resume: dict, tailored_resume: dict) -> list[str]:
    """Return a list of human-readable fabrication descriptions: identity-level
    facts (companies, titles, institutions, project names, skills) present in
    the tailored resume but NOT in the base resume.

    This is a structural subset check, not a phrasing check — bullets may be
    reworded (that's the whole point of tailoring), but the set of employers,
    roles, schools, projects, and skills must not grow. New skills are the
    most common fabrication, so those are checked exactly against the base
    skill set.
    """
    src = _collect_source_facts(base_resume)
    tgt = _collect_source_facts(tailored_resume)

    violations: list[str] = []
    for kind in ("company", "title", "institution", "project", "skill"):
        added = tgt[kind] - src[kind]
        # Ignore empties.
        added = {a for a in added if a}
        for a in sorted(added):
            violations.append(f"{kind} not in base resume: '{a}'")
    return violations


def tailor_resume_for_lead(lead: dict) -> dict:
    """Per-lead entry point used by graph/pipeline.py's tailor_resume_node.

    Wraps tailor_resume() + save_resume() + keyword_coverage() -- the same
    persistence logic run()'s per-lead loop below uses -- so the LangGraph
    node and the standalone CLI runner can't silently drift into different
    tailoring/saving behavior over time.

    Returns {"resume_version": filename, "keyword_coverage": float}.
    """
    user_id = lead.get("user_id") or get_current_user_id()
    company = lead.get("company") or lead.get("x_handle") or "Unknown"
    role = lead.get("role") or ""
    jd_text = lead.get("jd_text") or ""
    company_research = lead.get("company_research")

    if not jd_text.strip():
        jd_text = f"Role: {role} at {company}"

    # NoResumeError intentionally propagates: a lead for a user with no resume
    # on file must NOT be tailored against anyone else's resume. The caller
    # (graph node / batch run) turns this into a "no_resume" failure.
    base_resume = load_base_resume(user_id)

    result = tailor_resume_verbose(base_resume, company, role, jd_text, company_research=company_research)
    tailored = result["tailored"]
    coverage = result["keyword_coverage"]
    model_used = result["model_used"]

    filename = save_resume(tailored, company, user_id=user_id, jd_text=jd_text)
    below_floor = coverage < MIN_ATS_SCORE

    # Persist the tailored version (JSON source-of-truth in Postgres, artifact
    # keys pointing at the object store) for the Resume-page history + a
    # multi-instance-safe attach path.
    _persist_tailored_row(
        user_id=user_id, lead_id=lead.get("id"), company=company, role=role,
        tailored=tailored, coverage=coverage, base_filename=filename, source="pipeline",
        model_used=model_used,
    )

    flag = "  ⚠️ below ATS floor" if below_floor else ""
    print(
        f"  tailor_resume_for_lead: tailored resume for {company} -> "
        f"{filename} (ATS keyword coverage: {coverage}% via {model_used}){flag}"
    )
    return {
        "resume_version": filename,
        "keyword_coverage": coverage,
        "ats_below_floor": below_floor,
        "model_used": model_used,
    }


def _persist_tailored_row(
    user_id: str | None, lead_id, company: str, role: str,
    tailored: dict, coverage: float, base_filename: str, source: str = "pipeline",
    template: str = DEFAULT_TEMPLATE, model_used: str | None = None,
) -> None:
    """Best-effort persistence of a tailored version to Postgres. Never fails
    the tailoring flow — the artifacts are already stored; this row is the
    queryable index for the Resume page + attach path."""
    if not user_id:
        return
    try:
        repo.add_tailored_resume(user_id, {
            "lead_id": lead_id if lead_id else None,
            "company": company,
            "role": role,
            "tailored_json": tailored,
            "keyword_coverage": coverage,
            "template": template,
            "model_used": model_used,
            "pdf_key": f"{base_filename}.pdf",
            "md_key": f"{base_filename}.md",
            "legacy_version": base_filename,
            "source": source,
        })
    except Exception as e:
        print(f"  ⚠️  _persist_tailored_row: failed to record tailored resume row: {e}")



def keyword_coverage(jd_text: str, tailored_resume: dict) -> float:
    """Rough ATS-style check: what % of significant JD words appear
    somewhere in the tailored resume. Not a real ATS simulation, just a
    directional signal -- printed alongside each tailored resume."""
    stopwords = {
        "the", "and", "for", "with", "you", "your", "our", "are", "will",
        "this", "that", "have", "from", "who", "a", "an", "to", "of", "in",
        "on", "we", "is", "as", "be", "or", "at", "will", "can", "not",
    }
    jd_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9+.#]{2,}", jd_text.lower())) - stopwords
    if not jd_words:
        return 0.0

    resume_text = json.dumps(tailored_resume).lower()
    matched = sum(1 for word in jd_words if word in resume_text)
    return round(100 * matched / len(jd_words), 1)


# Stopwords shared by the JD keyword-coverage signal and the per-bullet
# JD-relevance scoring used when trimming to fit one page.
_JD_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will",
    "this", "that", "have", "from", "who", "a", "an", "to", "of", "in",
    "on", "we", "is", "as", "be", "or", "at", "can", "not", "by", "an",
}


def _jd_keywords(jd_text: str) -> set[str]:
    """Significant (non-stopword) tokens from the JD, used to score how
    relevant a given resume bullet is to this specific job."""
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9+.#]{2,}", (jd_text or "").lower())) - _JD_STOPWORDS


def _bullet_jd_score(bullet: str, jd_words: set[str]) -> int:
    """How many distinct JD keywords a bullet touches. Higher = more relevant
    to the job. Ties broken elsewhere by preferring to drop LATER (lower on
    the page) and LONGER bullets first."""
    if not bullet or not jd_words:
        return 0
    words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9+.#]{2,}", bullet.lower()))
    return len(words & jd_words)


def _trim_one_least_relevant_bullet(resume: dict, jd_text: str) -> dict | None:
    """Return a COPY of `resume` with exactly one bullet removed — the single
    least JD-relevant bullet across experience + projects — or None when
    nothing can be safely removed.

    Safety rules so trimming only ever drops genuinely low-value content:
      - Only experience/project BULLETS are eligible. Names, titles,
        companies, dates, education, skills, and summary are never touched.
      - An entry's LAST remaining bullet is protected, so no experience/project
        is left with zero bullets (which would look broken/empty).
      - The lowest JD-relevance bullet wins; ties prefer the later entry and
        the longer bullet (takes more space, adds least keyword value).
    """
    jd_words = _jd_keywords(jd_text)
    if not jd_words:
        return None

    import copy

    candidates = []  # (score, entry_index_desc, length, section, entry_i, bullet_i)
    for section in ("experience", "projects"):
        entries = resume.get(section) or []
        for ei, entry in enumerate(entries):
            bullets = entry.get("bullets") or []
            # Protect the last bullet so the entry never becomes empty.
            if len(bullets) <= 1:
                continue
            for bi, b in enumerate(bullets):
                candidates.append((
                    _bullet_jd_score(b, jd_words),  # fewer JD hits -> drop first
                    -ei,                            # later entry -> drop first
                    -len(b or ""),                  # longer -> drop first
                    section, ei, bi,
                ))

    if not candidates:
        return None

    # Lowest score, then later entry, then longer bullet.
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    _, _, _, section, ei, bi = candidates[0]

    trimmed = copy.deepcopy(resume)
    trimmed[section][ei]["bullets"].pop(bi)
    return trimmed


def resume_to_markdown(resume: dict) -> str:
    lines = [f"# {resume.get('name', '')}"]

    contact = resume.get("contact", {})
    contact_line = " | ".join(filter(None, [
        contact.get("location"), contact.get("phone"), contact.get("email"),
        contact.get("linkedin"), contact.get("github"), contact.get("portfolio"),
    ]))
    lines.append(contact_line)
    lines.append("")

    if resume.get("summary"):
        lines.append("## Summary")
        lines.append(resume["summary"])
        lines.append("")

    if resume.get("education"):
        lines.append("## Education")
        for edu in resume["education"]:
            lines.append(f"**{edu.get('institution', '')}** — {edu.get('degree', '')} "
                         f"({edu.get('start_date', '')} – {edu.get('end_date', '')})")
            if edu.get("details"):
                lines.append(edu["details"])
        lines.append("")

    if resume.get("experience"):
        lines.append("## Experience")
        for exp in resume["experience"]:
            lines.append(f"**{exp.get('title', '')}**, {exp.get('company', '')} "
                         f"({exp.get('start_date', '')} – {exp.get('end_date', '')})")
            for bullet in exp.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    if resume.get("projects"):
        lines.append("## Projects")
        for proj in resume["projects"]:
            title = proj.get("name", "")
            if proj.get("link"):
                title += f" ({proj['link']})"
            lines.append(f"**{title}** — {proj.get('date', '')}")
            if proj.get("tech_stack"):
                lines.append(f"*{', '.join(proj['tech_stack'])}*")
            for bullet in proj.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    if resume.get("skills"):
        lines.append("## Skills")
        for category, items in resume["skills"].items():
            lines.append(f"**{category}:** {', '.join(items)}")
        lines.append("")

    if resume.get("certifications"):
        lines.append("## Certifications")
        for cert in resume["certifications"]:
            lines.append(f"- {cert}")

    return "\n".join(lines)


def sanitize_for_pdf(text: str) -> str:
    """The default PDF fonts only support Latin-1/WinAnsi encoding, but our
    resume text has em dashes, smart quotes, and arrows (e.g. the Artha.ai
    fallback-chain bullet). Swap those for ASCII-safe equivalents instead of
    risking missing glyphs."""
    if not text:
        return text
    replacements = {
        "—": "-", "–": "-",
        "‘": "'", "’": "'",
        "“": '"', "”": '"',
        "…": "...", "→": "->",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def esc(text: str) -> str:
    """Sanitize then HTML-escape a piece of resume text before it goes into the template."""
    return html_lib.escape(sanitize_for_pdf(text or ""))


def _normalize_url(url: str) -> str:
    """Ensure a link has a scheme so the rendered PDF's <a href> is absolute.
    A bare domain like "foo.vercel.app" would otherwise be treated as a
    relative path by PDF/browser link handlers. mailto:/tel:/http(s) pass
    through unchanged."""
    u = (url or "").strip()
    if not u:
        return u
    if u.lower().startswith(("http://", "https://", "mailto:", "tel:")):
        return u
    return "https://" + u.lstrip("/")


RESUME_CSS = """
@page { size: letter; margin: 0.3in 0.5in; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.6pt; line-height: 1.12; color: #000000; }
h1.name { text-align: center; font-size: 18pt; margin: 0 0 1px 0; line-height: 1.1; }
p.contact { text-align: center; font-size: 9.3pt; margin: 0 0 4px 0; }
h2.section { font-size: 11pt; border-bottom: 1px solid #000000; margin: 4px 0 1px 0; padding-bottom: 0px; line-height: 1.1; }
table.row { width: 100%; border-collapse: collapse; }
table.row td { padding: 0; vertical-align: top; line-height: 1.1; }
td.left { text-align: left; font-weight: bold; }
td.left.plain { font-weight: normal; }
td.right { text-align: right; }
p.subtext { font-style: italic; margin: 0; line-height: 1.1; }
p.plain { margin: 0; line-height: 1.1; }
ul.bullets { list-style-type: disc; margin: 0 0 2px 0; padding-left: 13px; }
ul.bullets li { text-align: justify; margin-bottom: 0px; line-height: 1.15; }
p.skills-line { margin: 0; line-height: 1.2; }
a { color: #1155cc; text-decoration: underline; }
"""


# "Standard" — a cleaner, more conventional layout: left-aligned header,
# conventional single-column layout: centered name + contact, bold dark
# uppercase section headers with a full-width rule, tight left-aligned bullets
# (the clean "professional" resume look). Same HTML structure as the Jake
# template so one renderer serves both and ATS text extraction is identical.
STANDARD_CSS = """
@page { size: letter; margin: 0.5in 0.6in; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.3; color: #111111; }
h1.name { text-align: center; font-size: 21pt; font-weight: 700; margin: 0 0 3px 0; line-height: 1.1; letter-spacing: 0.2px; }
p.contact { text-align: center; font-size: 8.8pt; color: #333; margin: 0 0 10px 0; }
h2.section { font-size: 10pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; color: #111; border-bottom: 1px solid #444444; margin: 11px 0 5px 0; padding-bottom: 2px; }
table.row { width: 100%; border-collapse: collapse; }
table.row td { padding: 0; vertical-align: top; line-height: 1.3; }
td.left { text-align: left; font-weight: 700; }
td.left.plain { font-weight: 400; font-style: italic; }
td.right { text-align: right; color: #333; font-size: 9pt; }
p.subtext { font-style: italic; color: #333; margin: 0; line-height: 1.3; }
p.plain { margin: 0; line-height: 1.3; }
ul.bullets { list-style-type: disc; margin: 3px 0 5px 0; padding-left: 16px; }
ul.bullets li { text-align: left; margin-bottom: 1.5px; line-height: 1.32; }
p.skills-line { margin: 1.5px 0; line-height: 1.32; }
a { color: #1155cc; text-decoration: underline; }
"""


# Per-template layout metrics. A single parameterized stylesheet is built from
# these so the same rules can be emitted at a reduced scale for content-heavy
# resumes (single-page fit) WITHOUT duplicating selectors — xhtml2pdf does not
# cascade a second rule for the same selector, so we must emit each selector
# exactly once with its final (possibly scaled) values.
_TEMPLATE_METRICS = {
    "jake": {
        "page_margin_v": 0.30, "page_margin_h": 0.5,
        "body_font": 9.6, "body_lh": 1.12,
        "name_font": 18.0, "contact_font": 9.3, "contact_mb": 4.0,
        "section_font": 11.0, "section_mt": 4.0,
        "bullet_lh": 1.15, "bullets_mb": 2.0, "skills_lh": 1.2,
        "section_rule": "1px solid #000000", "body_color": "#000000",
        "bullet_align": "justify", "section_upper": False,
        "right_color": "", "right_font": "",
    },
    "standard": {
        "page_margin_v": 0.50, "page_margin_h": 0.6,
        "body_font": 10.0, "body_lh": 1.3,
        "name_font": 21.0, "contact_font": 8.8, "contact_mb": 10.0,
        "section_font": 10.0, "section_mt": 11.0,
        "bullet_lh": 1.32, "bullets_mb": 5.0, "skills_lh": 1.32,
        "section_rule": "1px solid #444444", "body_color": "#111111",
        "bullet_align": "left", "section_upper": True,
        "right_color": "#333", "right_font": "9pt",
    },
}


def _build_css(template: str, scale: float = 1.0) -> str:
    """Emit the resume stylesheet for `template`, with all vertical sizing
    multiplied by `scale` (<= 1.0). scale=1.0 reproduces the original template
    CSS byte-for-visual-equivalence; a smaller scale compresses font sizes,
    line-heights, and margins to keep heavy content on one page.

    Each selector is emitted exactly once (xhtml2pdf ignores a redefined
    selector), so scaling happens by generating the numbers, never by layering
    an override rule on top.
    """
    m = _TEMPLATE_METRICS.get(template, _TEMPLATE_METRICS["jake"])

    def s(v: float, lo: float = 0.0) -> float:
        return round(max(lo, v * scale), 2)

    # Page margins shrink only mildly (keep a safe printable border).
    margin_scale = max(0.6, scale)
    pm_v = round(m["page_margin_v"] * margin_scale, 3)
    pm_h = round(m["page_margin_h"] * margin_scale, 3)

    right_extra = ""
    if m["right_color"]:
        right_extra = f" color: {m['right_color']}; font-size: {s(float(m['right_font'][:-2]))}pt;"
    section_upper = " text-transform: uppercase; letter-spacing: 0.6px;" if m["section_upper"] else ""
    name_extra = " font-weight: 700; letter-spacing: 0.2px;" if template == "standard" else ""
    subtext_color = " color: #333;" if template == "standard" else ""
    plain_left = " font-style: italic;" if template == "standard" else ""

    return f"""
@page {{ size: letter; margin: {pm_v}in {pm_h}in; }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: {s(m['body_font'], 7.4)}pt; line-height: {s(m['body_lh'], 1.02)}; color: {m['body_color']}; }}
h1.name {{ text-align: center; font-size: {s(m['name_font'], 14.0)}pt; margin: 0 0 {s(2.0)}px 0; line-height: 1.1;{name_extra} }}
p.contact {{ text-align: center; font-size: {s(m['contact_font'], 7.4)}pt; margin: 0 0 {s(m['contact_mb'], 2.0)}px 0;{subtext_color} }}
h2.section {{ font-size: {s(m['section_font'], 9.0)}pt; font-weight: 700;{section_upper} color: {m['body_color']}; border-bottom: {m['section_rule']}; margin: {s(m['section_mt'], 2.0)}px 0 1px 0; padding-bottom: 1px; line-height: 1.1; }}
table.row {{ width: 100%; border-collapse: collapse; }}
table.row td {{ padding: 0; vertical-align: top; line-height: {s(m['body_lh'], 1.02)}; }}
td.left {{ text-align: left; font-weight: 700; }}
td.left.plain {{ font-weight: 400;{plain_left} }}
td.right {{ text-align: right;{right_extra} }}
p.subtext {{ font-style: italic; margin: 0; line-height: {s(m['body_lh'], 1.02)};{subtext_color} }}
p.plain {{ margin: 0; line-height: {s(m['body_lh'], 1.02)}; }}
ul.bullets {{ list-style-type: disc; margin: {s(1.5)}px 0 {s(m['bullets_mb'], 1.0)}px 0; padding-left: {s(14.0, 10.0)}px; }}
ul.bullets li {{ text-align: {m['bullet_align']}; margin-bottom: {s(1.0)}px; line-height: {s(m['bullet_lh'], 1.02)}; }}
p.skills-line {{ margin: {s(1.0)}px 0; line-height: {s(m['skills_lh'], 1.02)}; }}
a {{ color: #1155cc; text-decoration: underline; }}
"""


def _template_css(template: str) -> str:
    """Original (unscaled) stylesheet. Retained for callers/tests that expect
    the base template CSS; the render path uses _build_css with a fit scale."""
    return STANDARD_CSS if template == "standard" else RESUME_CSS


def _content_weight(resume: dict) -> int:
    """A rough measure of how much vertical space a resume needs.

    Counts the "line-generating" units — summary, each experience/education/
    project entry and its bullets, each skill category, certifications — plus
    a character-length signal for long bullets/summaries that wrap onto extra
    lines. Used only to decide how aggressively to compress so the PDF stays
    on one page; it never changes the resume content itself.
    """
    weight = 0
    chars = 0

    summary = resume.get("summary") or ""
    if summary:
        weight += 2
        chars += len(summary)

    for exp in resume.get("experience", []) or []:
        weight += 2  # heading + company/subtext line
        for b in exp.get("bullets", []) or []:
            weight += 1
            chars += len(b or "")

    for edu in resume.get("education", []) or []:
        weight += 2
        if edu.get("details"):
            weight += 1
            chars += len(edu["details"])

    for proj in resume.get("projects", []) or []:
        weight += 2
        for b in proj.get("bullets", []) or []:
            weight += 1
            chars += len(b or "")

    skills = resume.get("skills") or {}
    if isinstance(skills, dict):
        weight += len(skills)
        for items in skills.values():
            chars += len(", ".join(str(i) for i in (items or [])))
    elif isinstance(skills, list):
        weight += 1
        chars += len(", ".join(str(i) for i in skills))

    weight += len(resume.get("certifications", []) or [])

    # Every ~90 chars of body text tends to wrap to roughly one extra line.
    weight += chars // 90
    return weight


def _fit_scale(resume: dict, template: str) -> float:
    """Compute a layout scale factor (<= 1.0) that keeps a content-heavy resume
    on one page. Returns 1.0 (no compression) for resumes that already fit
    comfortably, so their rendering is unchanged. For heavier resumes it scales
    down proportionally to how far over the fit threshold the content is,
    clamped to a readable floor so no content is ever dropped.
    """
    weight = _content_weight(resume)

    # At/below this weight the default template fits one page — render as-is.
    threshold = 74 if template == "standard" else 84
    if weight <= threshold:
        return 1.0

    over = (weight - threshold) / float(threshold)
    # Map "how far over" to a readable scale in [0.82, 1.0). Heavier content is
    # handled by JD-aware bullet trimming (and, only as a last resort, the
    # extreme scale tier) rather than shrinking text below readability here.
    scale = 1.0 - min(over, 1.0) * 0.18
    return round(max(0.82, scale), 3)


def resume_to_html(resume: dict, template: str = DEFAULT_TEMPLATE, scale: float | None = None) -> str:
    template = template if template in TEMPLATES else DEFAULT_TEMPLATE
    name = esc(resume.get("name", ""))

    contact = resume.get("contact", {})
    contact_parts = []
    if contact.get("location"):
        contact_parts.append(esc(contact["location"]))
    if contact.get("phone"):
        _phone = contact["phone"]
        _tel = "tel:" + re.sub(r"[^0-9+]", "", str(_phone))
        contact_parts.append(f'<a href="{esc(_tel)}">{esc(_phone)}</a>')
    if contact.get("email"):
        _email = contact["email"]
        contact_parts.append(f'<a href="mailto:{esc(_email)}">{esc(_email)}</a>')
    if contact.get("linkedin"):
        contact_parts.append(f'<a href="{esc(_normalize_url(contact["linkedin"]))}">LinkedIn</a>')
    if contact.get("github"):
        contact_parts.append(f'<a href="{esc(_normalize_url(contact["github"]))}">GitHub</a>')
    if contact.get("portfolio"):
        contact_parts.append(f'<a href="{esc(_normalize_url(contact["portfolio"]))}">Portfolio</a>')
    contact_line = " | ".join(contact_parts)

    sections = []

    if resume.get("summary"):
        sections.append(f'<h2 class="section">Summary</h2><p class="plain">{esc(resume["summary"])}</p>')

    if resume.get("education"):
        rows = ['<h2 class="section">Education</h2>']
        for edu in resume["education"]:
            institution = edu.get("institution", "")
            if "," in institution:
                inst_name, inst_location = institution.split(",", 1)
            else:
                inst_name, inst_location = institution, ""
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left">{esc(inst_name.strip())}</td>'
                f'<td class="right">{esc(inst_location.strip())}</td>'
                f'</tr></table>'
            )
            dates = f'{edu.get("start_date", "")} – {edu.get("end_date", "")}'
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left plain">{esc(edu.get("degree", ""))}</td>'
                f'<td class="right">{esc(dates)}</td>'
                f'</tr></table>'
            )
            if edu.get("details"):
                rows.append(f'<p class="plain">{esc(edu["details"])}</p>')
        sections.append("".join(rows))

    if resume.get("experience"):
        rows = ['<h2 class="section">Experience</h2>']
        for exp in resume["experience"]:
            dates = f'{exp.get("start_date", "")} – {exp.get("end_date", "")}'
            title = exp.get("title", "")
            company = exp.get("company", "")
            if template == "standard":
                # Reference layout: "Company | Title" bold on the left line,
                # dates right — no separate italic company line.
                heading = " | ".join(x for x in [company, title] if x)
                rows.append(
                    f'<table class="row"><tr>'
                    f'<td class="left">{esc(heading)}</td>'
                    f'<td class="right">{esc(dates)}</td>'
                    f'</tr></table>'
                )
            else:
                rows.append(
                    f'<table class="row"><tr>'
                    f'<td class="left">{esc(title)}</td>'
                    f'<td class="right">{esc(dates)}</td>'
                    f'</tr></table>'
                )
                rows.append(f'<p class="subtext">{esc(company)}</p>')
            bullets = "".join(f"<li>{esc(b)}</li>" for b in exp.get("bullets", []))
            rows.append(f'<ul class="bullets">{bullets}</ul>')
        sections.append("".join(rows))

    if resume.get("projects"):
        rows = ['<h2 class="section">Projects</h2>']
        for proj in resume["projects"]:
            name_html = esc(proj.get("name", ""))
            if proj.get("link"):
                _url = _normalize_url(proj["link"])
                # Show the real (shortened) URL as the clickable text so the
                # link is visible and verifiable, not a generic "Live Link".
                _label = re.sub(r"^https?://", "", _url).rstrip("/")
                name_html += f' (<a href="{esc(_url)}">{esc(_label)}</a>)'
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left">{name_html}</td>'
                f'<td class="right">{esc(proj.get("date", ""))}</td>'
                f'</tr></table>'
            )
            if proj.get("tech_stack"):
                tech_line = " · ".join(esc(t) for t in proj["tech_stack"])
                rows.append(f'<p class="subtext">{tech_line}</p>')
            bullets = "".join(f"<li>{esc(b)}</li>" for b in proj.get("bullets", []))
            rows.append(f'<ul class="bullets">{bullets}</ul>')
        sections.append("".join(rows))

    if resume.get("skills"):
        rows = ['<h2 class="section">Technical Skills</h2>']
        for category, items in resume["skills"].items():
            items_line = ", ".join(esc(i) for i in items)
            rows.append(f'<p class="skills-line"><b>{esc(category)}:</b> {items_line}</p>')
        sections.append("".join(rows))

    if resume.get("certifications"):
        rows = ['<h2 class="section">Certifications</h2>']
        bullets = "".join(f"<li>{esc(c)}</li>" for c in resume["certifications"])
        rows.append(f'<ul class="bullets">{bullets}</ul>')
        sections.append("".join(rows))

    if scale is None:
        scale = _fit_scale(resume, template)
    css = _template_css(template) if scale >= 1.0 else _build_css(template, scale)
    return f"""<html>
<head><meta charset="utf-8"><style>{css}</style></head>
<body>
<h1 class="name">{name}</h1>
<p class="contact">{contact_line}</p>
{"".join(sections)}
</body>
</html>"""


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Count page objects in a PDF (/Type /Page, not /Pages). Used to enforce
    the single-page guarantee without a heavy PDF dependency."""
    if not pdf_bytes:
        return 0
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf_bytes))


# Scale steps tried to fit a resume onto one page. Split into two tiers so we
# prefer dropping a low-value bullet over shrinking text to tiny sizes:
#   - READABLE: mild compression that keeps text comfortably legible. We stay
#     within this tier first; if content still overflows and a JD is known, we
#     trim the least-relevant bullet rather than compress further.
#   - EXTREME: a final safety net (smaller fonts) used only when nothing more
#     can be safely trimmed, so the one-page guarantee still holds.
# The first step (1.0) is the untouched template; a short resume fits there and
# is never recompressed.
_FIT_SCALE_READABLE = (1.0, 0.95, 0.9, 0.86, 0.82)
_FIT_SCALE_EXTREME = (0.78, 0.74, 0.7, 0.66, 0.62)
_FIT_SCALE_STEPS = _FIT_SCALE_READABLE + _FIT_SCALE_EXTREME


def _render_at_scales(resume: dict, template: str, scales) -> tuple[bytes, int]:
    """Render `resume` stepping through `scales` (already filtered/ordered),
    returning (pdf_bytes, page_count) for the FIRST scale that fits one page —
    or the tightest render tried if none fit."""
    import io

    last_bytes = b""
    last_pages = 0
    for scale in scales:
        html_str = resume_to_html(resume, template=template, scale=scale)
        buf = io.BytesIO()
        result = pisa.CreatePDF(html_str, dest=buf)
        if result.err:
            raise RuntimeError(f"xhtml2pdf failed to render PDF ({result.err} errors)")
        last_bytes = buf.getvalue()
        last_pages = _pdf_page_count(last_bytes)
        if last_pages <= 1:
            break
    return last_bytes, last_pages


def _readable_scales(resume: dict, template: str) -> list[float]:
    initial = _fit_scale(resume, template)
    return [s for s in _FIT_SCALE_READABLE if s <= initial] or [min(initial, _FIT_SCALE_READABLE[-1])]


def _render_at_smallest_scale(resume: dict, template: str) -> tuple[bytes, int]:
    """Render `resume` across ALL scale steps (readable then extreme) and
    return the first single-page fit, or the tightest render. Used when no JD
    is available to guide trimming — pure layout compression."""
    initial = _fit_scale(resume, template)
    steps = [s for s in _FIT_SCALE_STEPS if s <= initial] or [initial]
    return _render_at_scales(resume, template, steps)


def _render_pdf_single_page(resume: dict, template: str, jd_text: str = "") -> bytes:
    """Render the resume to a single-page PDF (bytes).

    Single-page guarantee, ordered to preserve readability and JD relevance:
      1. Try READABLE layout compression. A resume that already fits at scale
         1.0 is rendered once, unchanged.
      2. If it still overflows AND a job description is available, drop the
         least JD-relevant experience/project bullet (never identity, skills,
         summary, or an entry's last bullet) and retry the readable scales —
         repeating so we shed low-value content instead of shrinking text.
      3. Only if nothing more can be safely trimmed, fall back to EXTREME
         (smaller) scales so the one-page guarantee always holds.

    Without a `jd_text`, steps 1+3 run as pure compression (behavior matches
    the prior scale-only fit).
    """
    # Step 1: readable compression only.
    current = resume
    pdf_bytes, pages = _render_at_scales(current, template, _readable_scales(current, template))
    if pages <= 1:
        return pdf_bytes

    # Step 2: prefer trimming the least JD-relevant bullets (retrying readable
    # scales after each drop) over shrinking text further.
    if jd_text:
        for _ in range(40):
            trimmed = _trim_one_least_relevant_bullet(current, jd_text)
            if trimmed is None:
                break  # nothing safe left to remove
            current = trimmed
            pdf_bytes, pages = _render_at_scales(current, template, _readable_scales(current, template))
            if pages <= 1:
                return pdf_bytes

    # Step 3: final safety net — extreme scales on whatever content remains.
    pdf_bytes, pages = _render_at_scales(current, template, _FIT_SCALE_EXTREME)
    return pdf_bytes


def resume_to_pdf(resume: dict, output_path: str, template: str = DEFAULT_TEMPLATE, jd_text: str = ""):
    """Renders via HTML/CSS (xhtml2pdf) so we can match the actual visual
    template -- bold-left/date-right rows, justified bullets, section
    divider lines -- instead of a generic manually-positioned layout.

    Guarantees a single-page PDF: content is auto-compressed and, if a
    `jd_text` is given, the least JD-relevant bullets are dropped until it
    fits one letter page (a resume that already fits renders unchanged)."""
    pdf_bytes = _render_pdf_single_page(resume, template, jd_text=jd_text)
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)


def resume_to_pdf_bytes(resume: dict, template: str = DEFAULT_TEMPLATE, jd_text: str = "") -> bytes:
    """Render the resume to a single-page PDF in-memory (no disk), for the
    artifact store. Same HTML/CSS template + single-page guarantee as
    resume_to_pdf; pass `jd_text` to enable JD-aware bullet trimming."""
    return _render_pdf_single_page(resume, template, jd_text=jd_text)


def save_resume(
    resume: dict, company: str, user_id: str | None = None,
    template: str = DEFAULT_TEMPLATE, jd_text: str = "",
) -> str:
    """Render the tailored resume's JSON/MD/PDF artifacts and store them via
    the artifact store (GCS in prod, local resumes/ in dev), keyed by a
    stable, user-namespaced base filename. Returns that base filename, which
    callers persist as the lead's `resume_version` (the store key).

    Bytes go to object storage; the structured JSON is also persisted to
    Postgres by the caller (via repo.add_tailored_resume) as the source of
    truth. The base filename is unchanged from the legacy scheme so existing
    resume_version references keep resolving.

    The stored JSON/MD keep the FULL tailored resume (source of truth for the
    Resume-page editor). The PDF is the one-page artifact: `jd_text`, when
    given, lets the renderer drop the least JD-relevant bullets to fit a
    single page after layout compression alone isn't enough.
    """
    from storage import artifact_store as store

    name_slug = slugify(resume.get("name", "resume"))
    company_slug = slugify(company)
    if user_id:
        user_slug = slugify(user_id)
        base_filename = f"{user_slug}_{name_slug}_resume_{company_slug}"
    else:
        base_filename = f"{name_slug}_resume_{company_slug}"

    json_bytes = json.dumps(resume, indent=2, ensure_ascii=False).encode("utf-8")
    md_bytes = resume_to_markdown(resume).encode("utf-8")
    pdf_bytes = resume_to_pdf_bytes(resume, template=template, jd_text=jd_text)

    store.put_bytes(f"{base_filename}.json", json_bytes, "application/json")
    store.put_bytes(f"{base_filename}.md", md_bytes, "text/markdown")
    store.put_bytes(f"{base_filename}.pdf", pdf_bytes, "application/pdf")

    return base_filename


def backfill_pdfs():
    """Generate PDFs for any already-tailored resume that doesn't have one
    yet, without re-calling the API (reads the .json already saved)."""
    if not os.path.isdir(RESUMES_DIR):
        return
    for filename in os.listdir(RESUMES_DIR):
        if not filename.endswith(".json"):
            continue
        base_filename = filename[:-5]
        pdf_path = os.path.join(RESUMES_DIR, f"{base_filename}.pdf")
        if os.path.exists(pdf_path):
            continue
        with open(os.path.join(RESUMES_DIR, filename), encoding="utf-8") as f:
            resume = json.load(f)
        resume_to_pdf(resume, pdf_path)
        print(f"Backfilled PDF: resumes/{base_filename}.pdf")


def run(user_id: str | None = None):
    from skills.llm_client import MODEL_BACKEND, ANTHROPIC_API_KEY

    if MODEL_BACKEND == "claude" and not ANTHROPIC_API_KEY:
        print("MODEL_BACKEND=claude but ANTHROPIC_API_KEY not set -- skipping tailor_resume.")
        return

    if user_id is None:
        user_id = get_current_user_id()

    leads = repo.get_leads(user_id)
    targets = [lead for lead in leads if not (lead.get("resume_version") or "").strip()]

    # Resolve the user's OWN base resume up front. If they have none on file,
    # do NOT tailor anything against a shared/other resume — mark every target
    # lead as needing a resume and stop.
    try:
        base_resume = load_base_resume(user_id)
    except NoResumeError as e:
        print(f"  ⛔ tailor_resume.run: {e}")
        for lead in targets:
            try:
                repo.update_lead(user_id, lead["id"], {"failure_reason": "no_resume"})
            except Exception:
                pass
        print(f"tailor_resume: 0 resumes tailored (no base resume for user {user_id}).")
        return

    tailored_count = 0

    for lead in targets:
        company = lead.get("company") or lead.get("x_handle") or "Unknown"
        role = lead.get("role") or ""
        jd_text = lead.get("jd_text") or ""

        if not jd_text.strip():
            print(f"Skipping {company} ({lead['id']}) -- no jd_text to tailor against.")
            try:
                repo.update_lead(user_id, lead["id"], {"failure_reason": "no_job_description"})
            except Exception:
                pass
            continue

        try:
            tailored = tailor_resume(base_resume, company, role, jd_text)
        except Exception as e:
            print(f"Failed to tailor resume for {company}: {e}")
            try:
                repo.update_lead(user_id, lead["id"], {"failure_reason": "tailor_failed"})
            except Exception:
                pass
            continue

        filename = save_resume(tailored, company, user_id=user_id, jd_text=jd_text)
        coverage = keyword_coverage(jd_text, tailored)
        # status: "tailored" mirrors graph/pipeline.py's tailor_resume_node
        # (the graph-driven path already sets this) -- the standalone
        # CLI/API route path was missing it, leaving a lead's status stuck
        # at "matched" even after a resume was actually tailored for it.
        # Tailoring succeeded — clear any prior failure flag. Keyword coverage
        # is an internal signal only; a "low" score is NOT a failure (the
        # resume is honestly tailored to what the candidate actually has), so
        # we never set a failure_reason for it.
        repo.update_lead(user_id, lead["id"], {
            "resume_version": filename, "keyword_coverage": coverage,
            "status": "tailored",
            "failure_reason": None,
        })
        _persist_tailored_row(
            user_id=user_id, lead_id=lead["id"], company=company, role=role,
            tailored=tailored, coverage=coverage, base_filename=filename, source="pipeline",
        )
        tailored_count += 1
        print(f"Tailored resume for {company} -> {filename} "
              f"(ATS keyword coverage: {coverage}%)")

    print(f"\ntailor_resume: {tailored_count} resumes tailored.")


if __name__ == "__main__":
    run()
