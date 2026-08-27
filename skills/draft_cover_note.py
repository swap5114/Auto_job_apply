import os
import sys
import re
import json
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import repository as repo
from db.current_user import get_current_user_id
from skills.llm_client import llm_generate

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

RESUMES_DIR = os.path.join(os.path.dirname(__file__), "..", "resumes")

# Cover notes are the Apply channel's equivalent of skills/draft_outreach.py's
# outreach message -- same candidate, same zero-fabrication discipline, same
# "a real person wrote this in one sitting" bar. Rules 1, 2, 5 (banned
# phrases) below are carried over verbatim from draft_outreach.py's own
# SYSTEM_PROMPT (that list was earned from a real review pass on outreach
# drafts -- cover notes get written by the same kind of candidate to the
# same kind of company, so the same clichés apply and don't need
# re-discovering). Rule 4's word cap is lower and the format is fixed
# (no email/DM branch) since a ~250-300 word ATS cover-note field is a
# different, shorter artifact than an outreach email.
SYSTEM_PROMPT = """You are a cover-letter-drafting assistant for a job candidate. You will be given the candidate's tailored resume (JSON) for one specific job application, plus details about that job. Your job is to draft a short, genuine cover note for that application's ATS cover-note field.

STRICT RULES -- violating any of these is a critical failure:
1. NEVER claim a skill, experience, project, or credential that is not present in the resume JSON given. If the resume has no honest connection to this job description at all, say so plainly in your response instead of inventing one -- respond with exactly the text "NO_HONEST_CONNECTION: " followed by a one-sentence explanation of what's missing, and do not produce a cover note.
2. Do NOT copy resume bullets verbatim -- reference at most 1-2 relevant highlights in natural, conversational language, not resume prose restated.
3. Do NOT claim the resume is attached as a literal file in the note body (it gets attached separately by the application form itself) -- "my tailored resume covers this in more detail" is fine, "please find attached" is not.
4. HARD LENGTH LIMIT: 250-300 words. Count as you write. Most ATS cover-note fields are brief -- this is shorter than a full cover letter, cut anything that isn't earning its place.
5. Write like a real person typed this in one sitting, not like a form letter. Never use: "I came across your opening," "I am writing to express my interest," "I wanted to reach out," "I believe I would be a great fit," "please find attached," "I look forward to hearing from you," or any equivalent throat-clearing. Open with something specific -- a real observation about the company, product, or role -- not a windup.
6. Show hunger and a point of view, not a qualifications checklist. This candidate is ambitious and has a specific reason THIS company/problem excites them -- pull that reason from something real in the job description (what they build, the problem they're solving, a detail only this listing mentions), not a compliment generic enough to paste into any other cover note. If you can't point to what in the JD justifies a line, cut the line.
7. Confident and direct, not desperate, not stiff -- write like someone pitching an idea they actually believe in, to a peer, not petitioning an authority.
8. End with a clear, low-friction close (e.g. happy to discuss further, available to start soon) -- never pushy or presumptuous.
9. Sign off with the candidate's name.

FORMAT: Plain prose, no subject line, no letterhead/date/address block (ATS cover-note fields are just body text). Return ONLY the cover note text (or the NO_HONEST_CONNECTION refusal from rule 1). No prose about your process, no explanation, no markdown code fences."""


def load_tailored_resume(resume_version: str) -> dict:
    path = os.path.join(RESUMES_DIR, f"{resume_version}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def draft_cover_note(tailored_resume: dict, lead: dict) -> str:
    """Draft a cover note for one apply-channel lead.

    Input is deliberately the tailored resume (not the base one) -- same
    reasoning skills/draft_outreach.py's own docstring gives for outreach:
    stay consistent with what's actually being submitted for this
    application, not a generic version of the candidate's background.

    Returns the raw cover note text, OR a string starting with
    "NO_HONEST_CONNECTION: " if the model determined (per rule 1 above)
    that the resume has no honest connection to this job -- callers must
    check for that prefix rather than assuming every return value is a
    usable cover note; this is the zero-fabrication rule made explicit as
    a real refusal, not a caller-side heuristic bolted on afterward.
    """
    company = lead.get("company") or ""
    role = lead.get("role") or ""
    jd_text = lead.get("jd_text") or ""

    user_message = f"""Write a cover note for this application.

Company: {company}
Role: {role}

Job description:
{jd_text}

Candidate's tailored resume for this application (JSON):
{json.dumps(tailored_resume, indent=2)}"""

    raw_text = llm_generate(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=1024,
    )

    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```\w*\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    return raw_text.strip()


def run():
    """CLI entry point (`python -m skills.draft_cover_note`) -- mirrors
    skills/draft_outreach.py's run(): drafts cover notes for the current
    single-operator user's apply-channel leads that have a tailored resume
    but no cover note yet.
    """
    from skills.llm_client import MODEL_BACKEND, ANTHROPIC_API_KEY

    if MODEL_BACKEND == "claude" and not ANTHROPIC_API_KEY:
        print("MODEL_BACKEND=claude but ANTHROPIC_API_KEY not set -- skipping draft_cover_note.")
        return

    user_id = get_current_user_id()
    leads = repo.get_leads(user_id)
    targets = [
        lead for lead in leads
        if "apply" in (lead.get("channel") or [])
        and (lead.get("resume_version") or "").strip()
        and not (lead.get("cover_note") or "").strip()
    ]

    drafted = 0

    for lead in targets:
        label = lead.get("company") or lead["id"]
        resume_version = lead["resume_version"]

        try:
            tailored_resume = load_tailored_resume(resume_version)
        except FileNotFoundError:
            print(f"Skipping {label} ({lead['id']}) -- tailored resume file not found for "
                  f"resume_version '{resume_version}'.")
            continue

        try:
            note = draft_cover_note(tailored_resume, lead)
        except Exception as e:
            print(f"Failed to draft cover note for {label}: {e}")
            continue

        if note.startswith("NO_HONEST_CONNECTION:"):
            print(f"Skipping {label} ({lead['id']}) -- model declined, no honest connection: {note}")
            continue

        # status: "pending_review" mirrors draft_outreach.run()'s own
        # convention for the outreach channel -- a cover note has been
        # generated and is now awaiting human review/approval.
        repo.update_lead(user_id, lead["id"], {"cover_note": note, "status": "pending_review"})
        drafted += 1
        print(f"\nDrafted cover note for {label} [status -> pending_review]:\n{'-' * 60}\n{note}\n{'-' * 60}")

    print(f"\ndraft_cover_note: {drafted} cover notes written.")


if __name__ == "__main__":
    run()
